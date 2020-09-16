"""
kaldo
Anharmonic Lattice Dynamics
"""
from opt_einsum import contract
import ase.units as units
import tensorflow as tf
from sparse import COO
import numpy as np
from kaldo.controllers.dirac_kernel import lorentz_delta, gaussian_delta, triangular_delta
from kaldo.helpers.storage import lazy_property, DEFAULT_STORE_FORMATS
from kaldo.observables.harmonic_with_q import HarmonicWithQ
from kaldo.helpers.logger import get_logger, log_size
logging = get_logger()

MAX_ITERATIONS_SC = 50
EVTOTENJOVERMOL = units.mol / (10 * units.J)
KELVINTOJOULE = units.kB / units.J
KELVINTOTHZ = units.kB / units.J / (2 * np.pi * units._hbar) * 1e-12
MAX_LENGTH_TRESHOLD = 1e15
hbar = 1 / (KELVINTOTHZ * 2 * np.pi)
kb = 1 / KELVINTOJOULE


def calculate_conductivity_per_mode(heat_capacity, velocity, mfp, physical_mode, n_phonons):
    conductivity_per_mode = np.zeros((n_phonons, 3, 3))
    physical_mode = physical_mode.reshape(n_phonons)
    velocity = velocity.reshape((n_phonons, 3))
    conductivity_per_mode[physical_mode, :, :] = \
        heat_capacity[physical_mode, np.newaxis, np.newaxis] * velocity[physical_mode, :, np.newaxis] * \
        mfp[physical_mode, np.newaxis, :]
    return conductivity_per_mode * 1e22


def calculate_diffusivity_dense(omega, flux, diffusivity_bandwidth, physical_mode, alpha, beta, curve, is_diffusivity_including_antiresonant=False):
    # TODO: cache this
    sigma = 2 * (diffusivity_bandwidth[:, np.newaxis] + diffusivity_bandwidth[np.newaxis, :])

    delta_energy = omega[:, np.newaxis] - omega[np.newaxis, :]
    kernel = curve(delta_energy, sigma)
    if is_diffusivity_including_antiresonant:
        sum_energy = omega[:, np.newaxis] + omega[np.newaxis, :]
        kernel += curve(sum_energy, sigma)
    kernel = kernel * np.pi
    kernel[np.isnan(kernel)] = 0
    mu_unphysical = np.argwhere(np.invert(physical_mode)).T
    # flux[mu_unphysical, mu_unphysical] = 0
    kernel[:, :] = kernel / omega[:, np.newaxis]
    kernel[:, :] = kernel[:, :] / omega[np.newaxis, :] / 4
    kernel[mu_unphysical, :] = 0
    kernel[:, mu_unphysical] = 0
    diffusivity = flux[..., alpha] * kernel * flux[..., beta]
    return diffusivity


def calculate_diffusivity_sparse(phonons, s_ij, diffusivity_bandwidth, diffusivity_threshold, curve, is_diffusivity_including_antiresonant=False):
    # TODO: cache this
    if is_diffusivity_including_antiresonant:
        logging.error('is_diffusivity_including_antiresonant not yet implemented for with thresholds and sparse.')


    omega = phonons.omega.reshape(phonons.n_k_points, phonons.n_modes)

    physical_mode = phonons.physical_mode.reshape((phonons.n_k_points, phonons.n_modes))
    physical_mode_2d = physical_mode[:, :, np.newaxis] & \
                       physical_mode[:, np.newaxis, :]
    omegas_difference = np.abs(omega[:, :, np.newaxis] - omega[:, np.newaxis, :])
    condition = (omegas_difference < diffusivity_threshold * 2 * np.pi * diffusivity_bandwidth)

    coords = np.array(np.unravel_index (np.flatnonzero (condition), condition.shape)).T
    sigma = 2 * (diffusivity_bandwidth[coords[:, 0], coords[:, 1]] + diffusivity_bandwidth[coords[:, 0], coords[:, 2]])
    delta_energy = omega[coords[:, 0], coords[:, 1]] - omega[coords[:, 0], coords[:, 2]]
    data = np.pi * curve(delta_energy, sigma)
    lorentz = COO(coords.T, data, shape=(phonons.n_k_points, phonons.n_modes, phonons.n_modes))
    prefactor = 1 / (4 * omega[coords[:, 0], coords[:, 1]] * omega[coords[:, 0], coords[:, 2]])
    prefactor[np.invert(physical_mode_2d[coords[:, 0], coords[:, 1], coords[:, 2]])] = 0
    prefactor = COO(coords.T, prefactor, shape=(phonons.n_k_points, phonons.n_modes, phonons.n_modes))
    shape = np.array([phonons.n_k_points, phonons.n_modes, phonons.n_modes, 3, 3])
    log_size(shape, name='diffusivity')
    diffusivity = np.zeros(shape)
    for alpha in range(3):
        for beta in range(3):
            diffusivity[..., alpha, beta] = (s_ij[alpha] * prefactor * lorentz * s_ij[beta]).todense()
    return diffusivity


def gamma_with_matthiessen(gamma, velocity, length):
    gamma = gamma + 2 * np.abs(velocity) / length
    return gamma


def mfp_matthiessen(gamma, velocity, length, physical_mode):
    lambd_0 = np.zeros_like(velocity)
    for alpha in range(3):
        if length is not None:
            if length[alpha] and length[alpha] != 0:
                gamma = gamma + 2 * abs(velocity[:, alpha]) / length[alpha]
        lambd_0[physical_mode, alpha] = 1 / gamma[physical_mode] * velocity[physical_mode, alpha]
    return lambd_0


def mfp_caltech(lambd, velocity, length, physical_mode):
    reduced_physical_mode = physical_mode.copy() & (velocity[:] != 0)
    lambd[reduced_physical_mode] = lambd[reduced_physical_mode] * \
                                   (1 - np.abs(lambd[reduced_physical_mode]) / (length / 2) *
                                    (1 - np.exp(- length / 2 / np.abs(
                                        lambd[reduced_physical_mode]))))
    return lambd


class Conductivity:
    """ The conductivity object is responsible for mean free path and
    conductivity calculations. It takes a phonons object as a required argument.


    Parameters
    ----------
    phonons : $\kappa$ALDo Phonons Object
        Contains all the information about the calculated phononic properties of the system
    method : string
        Specifies the method used to calculate_second the conductivity. Options
        are 'rta', 'sc', 'qhgk', and 'inverse'. See the theory page for details
        about the assumptions of the system implicit in each method.
    diffusivity_bandwidth : float, method specific
        (QHGK) Specifies the bandwidth to use in the calculation of the flux
        operator in the Allen-Feldman model of the thermal conductivity in
        amorphous systems. If a float is specified, all modes recieve the same
        bandwidth, if `diffusivity_bandwidth = None`, each mode recieves a unique
        bandwidth calculated by 0.5*phonons.bandwith. Units: rad/ps
        Defaults to `None`
    diffusivity_threshold : float, method specific
        (QHGK) Sets to 0 mode diffusivities that are beneath the specified
        threshold. Defaults to `None`
    diffusivity_shape : string, method specific
        (QHGK) Defines the algorithm to use to calculate the diffusivity.
        Available broadenings are `gauss`, `lorentz` and `triangle`. See the
        theory page for more details. Default is `lorentz`.
    is_diffusivity_including_antiresonant : bool, method specific
        (QHGK) Defines if you want to include or not anti-resonant terms in
        diffusivity calculations. Default is `False`.
    tolerance : int, method specific
        (Self-consistent) In the self consistent conductivity calculation, it
        specifies the difference in W/m/K between n and n+1 step, to set as
        the exit/convergence condition. Defaults to 0.1 W/m/K
    n_iterations : int, method specific
        (Self-consistent) Specifies the max number of iterations to set as exit
        condition in the self consistent conductivity. Defaults to 50.
        calculation
    length: 3-tuple, method specific
        (Finite Size) Specifies the length to use in x, y, z to calculate_second
        the finite size conductivity. `0` or `None` values corresponds to the
        infinity length limit. Defaults to (`None`, `None`, `None`)
    finite_length_method : string, method specific
        (Finite Size) Specifies how to calculate_second the finite size
        conductivity. Options are 'matthiessen', 'ms', and 'caltech', which correspond
        to Matthiessen, Mckelvey-Schockley, and Caltech methods. Read more about
        there assumptions here<link_to_theory>. Defaults to 'ms'
    storage : string, optional
        Defines the type of storage used for the simulation.
        The options are 'formatted', 'hdf5', 'numpy', and 'memory'. 'memory' does
        not store any data in the file system, but outputs it verbally. Default
        is `formatted`

    Returns
    -------
    Conductivity
        An instance of the `Conductivity` class.

    Examples
    --------
    Here's an example to calculate_second the inverse conductivity on the phonons object and tracing over the phonons modes

    ```
    Conductivity(phonons=phonons, method='inverse', storage='memory').conductivity.sum(axis=0))
    ```
    """

    def __init__(self, **kwargs):
        self.phonons = kwargs.pop('phonons')
        self.method = kwargs.pop('method', 'rta')
        self.storage = kwargs.pop('storage', 'formatted')
        if self.method == 'rta':
            self.n_iterations = 0
        else:
            self.n_iterations = kwargs.pop('n_iterations', None)
        self.length = kwargs.pop('length', np.array([None, None, None]))
        self.finite_length_method = kwargs.pop('finite_length_method', 'ms')
        self.tolerance = kwargs.pop('tolerance', 0.1)
        self.folder = self.phonons.folder
        self.kpts = self.phonons.kpts
        self.n_k_points = self.phonons.n_k_points
        self.n_modes = self.phonons.n_modes
        self.n_phonons = self.phonons.n_phonons
        self.temperature = self.phonons.temperature
        self.is_classic = self.phonons.is_classic
        self.third_bandwidth = self.phonons.third_bandwidth

        self.diffusivity_bandwidth = kwargs.pop('diffusivity_bandwidth', None)
        self.diffusivity_threshold = kwargs.pop('diffusivity_threshold', None)
        self.is_diffusivity_including_antiresonant = kwargs.pop('is_diffusivity_including_antiresonant', False)
        self.diffusivity_shape = kwargs.pop('diffusivity_shape', 'lorentz')



    @lazy_property(label='<diffusivity_bandwidth>/<diffusivity_threshold>/<temperature>/<statistics>/<third_bandwidth>/<method>/<length>/<finite_length_method>')
    def conductivity(self):
        """Calculate the thermal conductivity per mode in W/m/K as a 3 x 3 matrix
        where element $c_{\alpha \beta}$ represents the conductivity in direction
        $\alpha$ due to an applied temperature gradient in direction $\beta$.
        pass

        Returns
        -------
        conductivity : np array (phonons.n_k_points, phonons.n_modes, 3, 3)
        """
        method = self.method
        other_avail_methods = ['rta', 'sc', 'inverse', 'relaxon']
        if (method == 'qhgk'):
            cond = self.calculate_conductivity_qhgk().reshape((self.n_phonons, 3, 3))
        elif method in other_avail_methods:
            lambd = self.mean_free_path
            conductivity_per_mode = calculate_conductivity_per_mode(self.phonons.heat_capacity.reshape((self.n_phonons)),
                                                                    self.phonons.velocity, lambd, self.phonons.physical_mode,
                                                                    self.n_phonons)

            volume = np.linalg.det(self.phonons.atoms.cell)
            cond = conductivity_per_mode / (volume * self.n_k_points)
        else:
            logging.error('Conductivity method not implemented')

        # folder = get_folder_from_label(phonons, '<temperature>/<statistics>/<third_bandwidth>')
        # save('cond', folder + '/' + method, cond.reshape(phonons.n_k_points, phonons.n_modes, 3, 3), \
        #      format=phonons.store_format['conductivity'])
        sum = (cond.imag).sum()
        if sum > 1e-3:
            logging.warning('The conductivity has an immaginary part. Sum(Im(k)) = ' + str(sum))
        logging.info('Conductivity calculated')
        return cond.real


    @lazy_property(label='<diffusivity_bandwidth>/<diffusivity_threshold>/<temperature>/<statistics>/<third_bandwidth>/<method>/<length>/<finite_length_method>')
    def mean_free_path(self):
        """Calculate the mean_free_path per mode in $\AA$

        Returns
        -------
        mfp : np array(phonons.n_k_points, phonons.n_modes)
        """
        method = self.method

        if (method == 'qhgk'):
            logging.error('Mean free path not available for ' + str(method))
        elif method == 'rta':
            cond = self._calculate_mfp_sc()
        elif method == 'sc':
            cond = self._calculate_mfp_sc()
        elif (method == 'inverse'):
            cond = self.calculate_mfp_inverse()
        elif (method == 'evect'):
            cond = self.calculate_mfp_evect()
        else:
            logging.error('Conductivity method not implemented')

        # folder = get_folder_from_label(phonons, '<temperature>/<statistics>/<third_bandwidth>')
        # save('cond', folder + '/' + method, cond.reshape(phonons.n_k_points, phonons.n_modes, 3, 3), \
        #      format=phonons.store_format['conductivity'])
        sum = (cond.imag).sum()
        if sum > 1e-3:
            logging.warning('The conductivity has an immaginary part. Sum(Im(k)) = ' + str(sum))
        return cond.real


    @property
    def diffusivity(self):
        """Calculate the diffusivity, for each k point in k_points and each mode
        in $mm^2/s$

        Returns
        -------
        diffusivity : np.array(phonons.n_k_points, phonons.n_modes)
        """
        try:
            return self._diffusivity
        except AttributeError:
            logging.info('You need to calculate the conductivity QHGK first.')



    @lazy_property(label='<diffusivity_bandwidth>')
    def flux_dense(self):
        """Calculate the flux, for each couple of k point in k_points/modes.

        Returns
        -------
        flux : np.array(phonons.n_k_points, phonons.n_modes, phonons.n_k_points, phonons.n_modes, 3)
        """
        q_points = self.phonons._main_q_mesh
        if self.phonons._is_amorphous:
            type = np.float
        else:
            type = np.complex
        sij = np.zeros((self.n_k_points, self.n_modes, self.n_modes, 3), dtype=type)
        for ik in range(len(q_points)):
            q_point = q_points[ik]
            phonon = HarmonicWithQ(q_point,
                                   self.phonons.forceconstants.second_order,
                                   distance_threshold=self.phonons.forceconstants.distance_threshold,
                                   storage=self.phonons.storage)
            sij[ik] = phonon.calculate_sij()

        return sij


    @lazy_property(label='<diffusivity_bandwidth>/<diffusivity_threshold>')
    def flux_sparse(self):
        """Calculate the flux, for each couple of k point in k_points/modes.

        Returns
        -------
        flux : np.array(phonons.n_k_points, phonons.n_modes, phonons.n_k_points, phonons.n_modes, 3)
        """
        sij = self.calculate_sij_sparse()
        return sij


    @property
    def _scattering_matrix_without_diagonal(self):
        frequency = self._keep_only_physical(self.phonons.frequency.reshape((self.n_phonons)))
        _ps_gamma_and_gamma_tensor = self.phonons._ps_gamma_and_gamma_tensor
        gamma_tensor = self._keep_only_physical(_ps_gamma_and_gamma_tensor[:, 2:])
        scattering_matrix_without_diagonal = 1 / frequency.reshape(-1, 1) * gamma_tensor * frequency.reshape(1, -1)
        return scattering_matrix_without_diagonal


    def _keep_only_physical(self, operator):
        physical_mode = self.phonons.physical_mode.reshape(self.n_phonons)
        if operator.shape == (self.n_phonons, self.n_phonons):
            index = np.outer(physical_mode, physical_mode)
            return operator[index].reshape((physical_mode.sum(), physical_mode.sum()))
        elif operator.shape == (self.n_phonons, 3):
            return operator[physical_mode, :]
        else:
            return operator[physical_mode]


    def calculate_sij_sparse(self):
        phonons = self.phonons
        # TODO: do not pass the whole phonons object
        # TODO move this into second like the dense version
        diffusivity_threshold = self.diffusivity_threshold
        if self.diffusivity_bandwidth is not None:
            diffusivity_bandwidth = self.diffusivity_bandwidth * np.ones((phonons.n_k_points, phonons.n_modes))
        else:
            diffusivity_bandwidth = phonons.bandwidth.reshape((phonons.n_k_points, phonons.n_modes)).copy() / 2.
        omega = phonons.omega.reshape(phonons.n_k_points, phonons.n_modes)
        omegas_difference = np.abs(omega[:, :, np.newaxis] - omega[:, np.newaxis, :])
        condition = (omegas_difference < diffusivity_threshold * 2 * np.pi * diffusivity_bandwidth)
        coords = np.array(np.unravel_index(np.flatnonzero(condition), condition.shape)).T
        s_ij = [COO(coords.T, self.flux_dense[..., 0][coords[:, 0], coords[:, 1], coords[:, 2]],
                    shape=(phonons.n_k_points, phonons.n_modes, phonons.n_modes)),
                COO(coords.T, self.flux_dense[..., 1][coords[:, 0], coords[:, 1], coords[:, 2]],
                    shape=(phonons.n_k_points, phonons.n_modes, phonons.n_modes)),
                COO(coords.T, self.flux_dense[..., 2][coords[:, 0], coords[:, 1], coords[:, 2]],
                    shape=(phonons.n_k_points, phonons.n_modes, phonons.n_modes))]
        return s_ij


    def calculate_2d_heat_capacity(self, k_index):
        """Calculates the factor for the diffusivity which resembles the heat
        capacity in units of J/K.
        Using classical mechanics: $K_b$
        Using quantum mechanics: $C_{nm}=\hbar \frac{\omega_n \omega_m}{T}
        \frac{n_n-n_m}{\omega_m \omega_n)$

        Returns
        -------
        c_v : np.array(phonons.n_k_points,phonons.modes, phonons.n_modes) float
        """
        phonons = self.phonons
        if (phonons.is_classic):
            c_v = np.zeros((phonons.n_modes, phonons.n_modes))
            c_v[:, :] = KELVINTOJOULE
        else:
            frequencies = phonons.frequency.reshape((phonons.n_k_points, phonons.n_modes))
            temperature = phonons.temperature * KELVINTOTHZ
            heat_capacity = phonons.heat_capacity.reshape((phonons.n_k_points, phonons.n_modes))
            physical_mode = phonons.physical_mode.reshape((phonons.n_k_points, phonons.n_modes))
            f_be = phonons.population.reshape((phonons.n_k_points, phonons.n_modes))
            c_v_omega = (f_be[k_index, :, np.newaxis] - f_be[k_index, np.newaxis, :])
            diff_omega = (frequencies[k_index, :, np.newaxis] - frequencies[k_index, np.newaxis, :])
            mask_degeneracy = np.where(diff_omega == 0, True, False)

            # value to do the division
            diff_omega[mask_degeneracy] = 1
            divide_omega = -1 / diff_omega
            freq_sq = frequencies[k_index, :, np.newaxis] * frequencies[k_index, np.newaxis, :]

            # remember here f_n-f_m/ w_m-w_n index reversed
            c_v = freq_sq * c_v_omega * divide_omega
            c_v = KELVINTOJOULE * c_v / temperature

            #Degeneracy part: let us substitute the wrong elements
            heat_capacity_deg_2d = (heat_capacity[k_index, :, np.newaxis]
                                    + heat_capacity[k_index, np.newaxis, :]) / 2
            c_v = np.where(mask_degeneracy, heat_capacity_deg_2d, c_v)

            #Physical modes
            mask = physical_mode[k_index, :, np.newaxis] * physical_mode[k_index, np.newaxis, :]
            c_v = c_v * mask
        return c_v


    def calculate_conductivity_qhgk(self):
        """Calculates the conductivity of each mode using the :ref:'Quasi-Harmonic-Green-Kubo Model'.
        The tensor is returned individual modes along the first axis and has units of W/m/K.
        Will be made a private function in future relases.

        Returns
        -------
        conductivity_per_mode : np.array(phonons.n_phonons, 3, 3)
        """
        phonons = self.phonons
        omega = phonons.omega.reshape((phonons.n_k_points, phonons.n_modes))
        volume = np.linalg.det(phonons.atoms.cell)
        q_points = phonons._main_q_mesh
        physical_mode = phonons.physical_mode
        conductivity_per_mode = np.zeros((self.phonons.n_k_points, self.phonons.n_modes, 3, 3))
        diffusivity_with_axis = np.zeros_like(conductivity_per_mode)
        if self.diffusivity_shape == 'lorentz':
            logging.info('Using Lorentzian diffusivity_shape')
            curve = lorentz_delta
        elif self.diffusivity_shape == 'gauss':
            logging.info('Using Gaussian diffusivity_shape')
            curve = gaussian_delta
        elif self.diffusivity_shape == 'triangle':
            logging.info('Using triangular diffusivity_shape')
            curve = triangular_delta
        else:
            logging.error('Diffusivity shape not implemented')

        is_diffusivity_including_antiresonant = self.is_diffusivity_including_antiresonant

        if self.diffusivity_bandwidth is not None:
            logging.info('Using diffusivity bandwidth from input')
            diffusivity_bandwidth = self.diffusivity_bandwidth * np.ones((phonons.n_k_points, phonons.n_modes))
        else:
            diffusivity_bandwidth = self.phonons.bandwidth.reshape((phonons.n_k_points, phonons.n_modes)).copy() / 2.

        if self.diffusivity_threshold is None:
            logging.info('Start calculation diffusivity dense')

            for k_index in range(len(q_points)):
                heat_capacity = self.calculate_2d_heat_capacity(k_index)

                phonon = HarmonicWithQ(q_points[k_index],
                                       self.phonons.forceconstants.second_order,
                                       distance_threshold=self.phonons.forceconstants.distance_threshold,
                                       folder=self.folder,
                                       storage=self.storage)
                sij = phonon.calculate_sij()

                if phonons.n_modes > 100:
                    logging.info('calculating conductivity for ' + str(q_points[k_index]))
                for alpha in range(3):
                    for beta in range(3):
                        diffusivity = calculate_diffusivity_dense(omega[k_index], sij,
                                                                  diffusivity_bandwidth[k_index],
                                                                  physical_mode[k_index], alpha, beta, curve, is_diffusivity_including_antiresonant)
                        conductivity_per_mode[k_index, :, alpha, beta] = np.sum(heat_capacity *
                                                                                diffusivity, axis=-1) \
                                                                         / (volume * phonons.n_k_points)
                        diffusivity_with_axis[k_index, :, alpha, beta] = np.sum(diffusivity, axis=-1).real
        else:
            #TODO: migrate this part to tf, currently only numpy
            logging.info('Start calculation diffusivity sparse')
            sij = self.flux_sparse
            diffusivity = calculate_diffusivity_sparse(phonons, sij, diffusivity_bandwidth, self.diffusivity_threshold, curve,
                                                       is_diffusivity_including_antiresonant)
            heat_capacity = np.zeros((phonons.n_k_points, phonons.n_modes, phonons.n_modes))
            for index_k in range(phonons.n_k_points):
                heat_capacity[index_k] = self.calculate_2d_heat_capacity(index_k)
            conductivity_per_mode = contract('knm,knmab->knab', heat_capacity, diffusivity)
            conductivity_per_mode = conductivity_per_mode.reshape((phonons.n_phonons, 3, 3))
            conductivity_per_mode = conductivity_per_mode / (volume * phonons.n_k_points)
            diffusivity_with_axis = contract('knmab->knab', diffusivity)

        self._diffusivity = 1 / 3 * 1 / 100 * contract('knaa->kn', diffusivity_with_axis)

        return conductivity_per_mode * 1e22


    def calculate_mfp_inverse(self):
        """This method calculates the inverse of the mean free path for each phonon.
        The matrix returns k vectors for each mode and has units of inverse Angstroms.
        Will be made a private function in future relases.

        Returns
        -------
        lambda : np array(phonons.n_k_points, phonons.n_modes)

        """
        length = self.length
        phonons = self.phonons
        finite_size_method = self.finite_length_method
        physical_mode = phonons.physical_mode.reshape(phonons.n_phonons)
        velocity = phonons.velocity.real.reshape((phonons.n_phonons, 3))
        lambd = np.zeros_like(velocity)
        for alpha in range (3):
            scattering_matrix = - 1 * self._scattering_matrix_without_diagonal
            gamma = phonons.bandwidth.reshape(phonons.n_phonons)
            if finite_size_method == 'ms':
                if length is not None:
                    if length[alpha]:
                        gamma = gamma_with_matthiessen(gamma, velocity[:, alpha],
                                                       length[alpha])

            scattering_matrix += np.diag(gamma[physical_mode])
            scattering_inverse = np.linalg.inv(scattering_matrix)
            lambd[physical_mode, alpha] = scattering_inverse.dot(velocity[physical_mode, alpha])
            if finite_size_method == 'caltech':
                if length is not None:
                    if length[alpha]:
                        lambd[:, alpha] = mfp_caltech(lambd[:, alpha], velocity[:, alpha], length[alpha], physical_mode)
            if finite_size_method == 'matthiessen':
                if (self.length[alpha] is not None) and (self.length[alpha] != 0):
                    lambd[physical_mode, alpha] = 1 / (
                            np.sign(velocity[physical_mode, alpha]) / lambd[physical_mode, alpha] + 1 /
                            np.array(self.length)[np.newaxis, alpha]) * np.sign(velocity[physical_mode, alpha])
                else:
                    lambd[physical_mode, alpha] = 1 / (
                            np.sign(velocity[physical_mode, alpha]) / lambd[physical_mode, alpha]) * np.sign(
                        velocity[physical_mode, alpha])

                lambd[velocity[:, alpha] == 0, alpha] = 0
        return lambd


    def calculate_mfp_evect(self):
        """This calculates the mean free path of evect. In materials where most scattering events conserve momentum
        'Relaxon Theory Section' (e.g. in two dimensional materials or three dimensional materials at extremely low
        temparatures), this quantity can be used to calculate thermal conductivity.

        Returns
	    -------
        lambda : np array
            (phonons.n_k_points, phonons.n_modes, 3)
        """
        phonons = self.phonons
        velocity = self._keep_only_physical(phonons.velocity.real.reshape((phonons.n_phonons, 3)))
        scattering_matrix = -1 * self._scattering_matrix_without_diagonal
        gamma = self._keep_only_physical(self.phonons.bandwidth.reshape((self.n_phonons)))
        _scattering_matrix = scattering_matrix + np.diag(gamma)
        evals, evects = np.linalg.eig(_scattering_matrix)

        neg_diag = (_scattering_matrix.diagonal() < 0).sum()
        logging.info('negative on diagonal : ' + str(neg_diag))
        logging.info('negative eigenvals : ' + str((evals < 0).sum()))

        # TODO: find a better way to filter states
        new_physical_states = np.argwhere(evals >= 0)[0, 0]
        reduced_evects = evects[new_physical_states:, new_physical_states:]
        reduced_evals = evals[new_physical_states:]
        log_size(_scattering_matrix.shape, name='reduced_scattering')
        reduced_scattering_inverse = np.zeros_like(_scattering_matrix)
        reduced_scattering_inverse[new_physical_states:, new_physical_states:] = reduced_evects.dot(np.diag(1/reduced_evals)).dot(np.linalg.inv(reduced_evects))
        scattering_inverse = reduced_scattering_inverse
        # e, v = np.linalg.eig(a)
        # a = v.dot(np.diag(e)).dot(np.linalg.inv(v))

        lambd = scattering_inverse.dot(velocity[:, :])
        return lambd


    def _calculate_mfp_sc(self):
        phonons = self.phonons
        finite_size_method = self.finite_length_method
        physical_mode = phonons.physical_mode.reshape(phonons.n_phonons)
        velocity = phonons.velocity.real.reshape ((phonons.n_k_points, phonons.n_modes, 3))
        velocity = velocity.reshape((phonons.n_phonons, 3))

        if finite_size_method == 'ms':
            lambd_n = self._calculate_sc_mfp(matthiessen_length=self.length)
        else:
            lambd_n = self._calculate_sc_mfp()
        if finite_size_method == 'caltech':
            for alpha in range(3):
                lambd_n[:, alpha] = mfp_caltech(lambd_n[:, alpha], velocity[:, alpha], self.length[alpha], physical_mode)
        if finite_size_method == 'matthiessen':
            mfp = lambd_n.copy()
            for alpha in range(3):
                if (self.length[alpha] is not None) and (self.length[alpha] != 0):
                    lambd_n[physical_mode, alpha] = 1 / (np.sign(velocity[physical_mode, alpha]) / mfp[physical_mode, alpha] + 1 / np.array(self.length)[np.newaxis, alpha]) * np.sign(velocity[physical_mode, alpha])
                else:
                    lambd_n[physical_mode, alpha] = 1 / (np.sign(velocity[physical_mode, alpha]) / mfp[physical_mode, alpha]) * np.sign(velocity[physical_mode, alpha])

                lambd_n[velocity[:, alpha]==0, alpha] = 0
        return lambd_n


    def _calculate_sc_mfp(self, matthiessen_length=None):
        tolerance = self.tolerance
        n_iterations = self.n_iterations
        phonons = self.phonons
        if n_iterations is None:
            n_iterations = MAX_ITERATIONS_SC
        velocity = phonons.velocity.real.reshape ((phonons.n_k_points, phonons.n_modes, 3))
        velocity = velocity.reshape((phonons.n_phonons, 3))
        physical_mode = phonons.physical_mode.reshape(phonons.n_phonons)
        gamma = phonons.bandwidth.reshape(phonons.n_phonons)
        lambd_0 = mfp_matthiessen(gamma, velocity, matthiessen_length, physical_mode)
        if n_iterations == 0:
            return lambd_0
        else:
            lambd_n = np.zeros_like(lambd_0)
            avg_conductivity = None
            n_iteration = 0
            scattering_matrix = self._scattering_matrix_without_diagonal
            for n_iteration in range (n_iterations):
                conductivity_per_mode = calculate_conductivity_per_mode(phonons.heat_capacity.reshape((phonons.n_phonons)),
                                                                        velocity, lambd_n, physical_mode, phonons.n_phonons)
                new_avg_conductivity = np.diag (np.sum (conductivity_per_mode, 0)).mean ()
                if avg_conductivity:
                    if tolerance is not None:
                        if np.abs (avg_conductivity - new_avg_conductivity) < tolerance:
                            break
                avg_conductivity = new_avg_conductivity
                delta_lambd = 1 / phonons.bandwidth.reshape ((phonons.n_phonons))[physical_mode, np.newaxis] \
                              * scattering_matrix.dot (lambd_n[physical_mode, :])
                lambd_n[physical_mode, :] = lambd_0[physical_mode, :] + delta_lambd[:, :]
            logging.info('Number of self-consistent iterations: ' + str(n_iteration))
            return lambd_n

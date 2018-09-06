import numpy as np
from ballistico.constants import *
from ballistico.interpolation_controller import interpolator #,fourier_interpolator
import ballistico.atoms_helper as ath
from ballistico.tools import is_folder_present
from ballistico.constants import *
from ballistico.ShengbteHelper import ShengbteHelper
from sparse import tensordot,COO
import scipy

FREQUENCY_K_FILE = 'frequency_k.npy'
VELOCITY_K_FILE = 'velocity_k.npy'
EIGENVALUES_FILE = 'eigenvalues.npy'
EIGENVECTORS_FILE = 'eigenvectors.npy'
BUFFER_PLOT = .2


class Phonons (object):
    def __init__(self, system, k_size, is_classic=False):
        
        self.system = system
        self.is_classic = is_classic

        self.k_size = k_size
        self.folder = str(self.system) + '/'
        is_folder_present(self.folder)
        
        # Create k mesh
        # TODO: for some reason k-mesh comes with axis swapped
        
        self._frequencies = None
        self._velocities = None
        self._eigenvalues = None
        self._eigenvectors = None
        self._occupations = None


    @property
    def frequencies(self):
        return self._frequencies
    
    @frequencies.getter
    def frequencies(self):
        if self._frequencies is None:
            self.calculate_second_all_grid ()
    
            # try:
            #     self._frequencies = np.load (self.folder + FREQUENCY_K_FILE)
            # except FileNotFoundError as e:
            #     print(e)
            #     self.calculate_second_all_grid ()
            #     np.save (self.folder + FREQUENCY_K_FILE, self._frequencies)
            #     np.save (self.folder + VELOCITY_K_FILE, self._velocities)

        return self._frequencies
    
    @frequencies.setter
    def frequencies(self, new_frequencies):
        self._frequencies = new_frequencies

    @property
    def velocities(self):
        return self._velocities
    
    @velocities.getter
    def velocities(self):
        if self._velocities is None:
            self.calculate_second_all_grid ()
            # try:
            #     self._velocities = np.load (self.folder + VELOCITY_K_FILE)
            # except IOError as e:
            #     self.calculate_second_all_grid ()
            #     np.save (self.folder + VELOCITY_K_FILE, self._velocities)
            #     np.save (self.folder + FREQUENCY_K_FILE, self._frequencies)

        return self._velocities
    
    @velocities.setter
    def velocities(self, new_velocities):
        self._velocities = new_velocities
    
    @property
    def eigenvalues(self):
        return self._eigenvalues
    
    @eigenvalues.getter
    def eigenvalues(self):
        if self._eigenvalues is None:
            self.calculate_second_all_grid ()
    
            # try:
            #     self._eigenvalues = np.load (self.folder + EIGENVALUES_FILE)
            # except IOError as e:
            #     self.calculate_second_all_grid ()
            #     np.save (self.folder + EIGENVALUES_FILE, self._eigenvalues)
        return self._eigenvalues

    @eigenvalues.setter
    def eigenvalues(self, new_eigenvalues):
        self._eigenvalues = new_eigenvalues
    
    @property
    def eigenvectors(self):
        return self._eigenvectors
    
    @eigenvectors.setter
    def eigenvectors(self, new_eigenvectors):
        self._eigenvectors = new_eigenvectors
    
    @eigenvectors.getter
    def eigenvectors(self):
        if self._eigenvectors is None:
            self.calculate_second_all_grid ()
    
            # try:
            #     self._eigenvectors = np.load (self.folder + EIGENVECTORS_FILE)
            # except IOError as e:
            #     self.calculate_second_all_grid ()
            #     np.save (self.folder + EIGENVECTORS_FILE, self._eigenvectors)
        return self._eigenvectors
    
    @eigenvectors.setter
    def eigenvectors(self, new_eigenvectors):
        self._eigenvectors = new_eigenvectors
    
    @property
    def occupations(self):
        return self._occupations
    
    @occupations.getter
    def occupations(self):
        if self._occupations is None:
            self.calculate_occupations ()
        return self._occupations
    
    @occupations.setter
    def occupations(self, new_occupations):
        self._occupations = new_occupations
    
    
    
    def lorentzian_line_broadening(self, delta, width, threshold=2.):
        # TODO: maybe we want to normalize the energy among the used states. In order to conserve that
        
        # threshold is the number of widths that we keep as interacting
        out = np.zeros (delta.shape)
        out[delta < threshold * width] = 0.5 / np.pi * width / (
        delta[delta < threshold * width] ** 2 + (.5 * width) ** 2)
        if out.size == 0:
            return 0.
        return out
    
    def triangle_line_broadening(self, delta, width):
        out = np.zeros (delta.shape)
        out[delta < width] = 1. / width * (1 - delta[delta < width] / width)
        if out.size == 0:
            return 0.
        return out
    
    def delta_energy(self, eigthz_0, eigthz_1, eigthz_2, width=.1, is_plus=True):
        if is_plus:
            delta = np.abs (eigthz_0 - eigthz_1 - eigthz_2)
        else:
            delta = np.abs (eigthz_0 + eigthz_1 - eigthz_2)
        return self.lorentzian_line_broadening (delta, width)
    
    def interpolate_second_order_k(self, k_list):
        n_modes = self.system.configuration.positions.shape[0] * 3
        frequency = np.zeros ((k_list.shape[0], n_modes))
        for mode in range (n_modes):
            frequency[:, mode] = interpolator (k_list, self.frequencies[:, :, :, mode])
        return frequency
    
    def diagonalize_second_order_k(self, klist):
        is_single_k = (len(klist.shape) == 1)
        if is_single_k:
            return self.diagonalize_second_order_single_k(klist)
        else:
            frequencies = []
            eigenvals = []
            velocities = []
            eigenvects = []
            for qvec in klist:
                # TODO: The logic is a bit messy here and we can only support this for the path and not the grid
                freq, evalue, evect, vels = self.diagonalize_second_order_single_k(qvec)
                frequencies.append(freq)
                velocities.append(vels)
                eigenvects.append(evect)
                eigenvals.append(evalue)
            return np.array(frequencies), np.array(eigenvals), np.array(eigenvects), np.array(velocities)
    
    def diagonalize_second_order_single_k(self, qvec):
        
        # make sure q is between -.5 and .5
        # qvec -= np.round(qvec)
        #TODO: this could probably be expanded a bit
        if (qvec[0] == 0 and qvec[1] == 0 and qvec[2]==0):
            calculate_eigenvec = scipy.linalg.lapack.zheev
            # calculate_eigenvec = np.linalg.eigh
        else:
            calculate_eigenvec = scipy.linalg.lapack.zheev
            # calculate_eigenvec = np.linalg.eigh
        # dynmat = self.system.dynamical_matrix
        
        list_of_replicas = self.system.list_of_replicas
        geometry = self.system.configuration.positions
        n_particles = geometry.shape[0]
        n_replicas = list_of_replicas.shape[0]
        dyn_s = np.zeros ((n_particles * 3, n_particles * 3)).astype (complex)
        ddyn_s = np.zeros ((3, 3 * n_particles, n_particles * 3)).astype (complex)
        # dynbase = np.zeros ((n_particles, 3, n_particles, 3)).astype (complex)
        # perturb = np.zeros ((3, n_particles, 3, n_particles, 3)).astype (complex)
        
        unit_cell_inv = np.linalg.inv (self.system.configuration.cell)
        cell = self.system.configuration.cell
        rlatticevec = np.linalg.inv (cell) * np.linalg.det (cell)
        V = np.abs (rlatticevec[0].dot (cell[0]))
        rlatticevec = 2 * np.pi / V * rlatticevec
        toTHz = 20670.687
        bohr2nm = 0.052917721092
        
        for i_at in range (n_particles):
            for j_at in range (n_particles):
                for id_replica in range (n_replicas):
                    # print (self.system.list_of_indices[id_replica] % self.k_size + 1)
                    for i_pol in range(3):
                        for j_pol in range (3):

                            # self.system.list_of_replicas[id_replica] / bohroverangstrom
                            # dxij =  (geometry[j_at] + list_of_replicas[id_replica]) - geometry[i_at]
                            # dxij = (ath.apply_boundary (self.system.replicated_configuration, dxij))
                            dxij = list_of_replicas[id_replica]
                            # phase = 2j * np.pi * list_of_replicas[id_replica].dot ((unit_cell_inv).dot(qvec))
        
                            kpoints = (rlatticevec).dot (qvec)
                            kt = dxij.dot (kpoints)
                            phase = -1j * kt
                            # second_order[self.system.index_first_cell, 1, :, self.system.index_first_cell, 0, :]

                            i_dim = (i_at ) * 3 + i_pol
                            j_dim = (j_at ) * 3 + j_pol
                            
                            # print(qvec, l, t, s)
                            # print(phase)
                            
                            # sheng
                            # self.system.second_order[self.system.index_first_cell, j_at, :, id_replica, i_at,:] / evoverdlpoly / rydbergoverev * (bohroverangstrom ** 2)
                            
                            # TODO: here i and j are swapped
                            # dynbase[i_at, :, j_at, :] += self.system.second_order[self.system.index_first_cell, i_at, :, id_replica, j_at, :] * np.exp (phase)
                            mass_i = self.system.configuration.get_masses ()[i_at]
                            mass_j = self.system.configuration.get_masses ()[j_at]
                            massfactor = 1.8218779 * 6.022e-4
                            mass = np.sqrt (mass_i * mass_j) / massfactor
                            
                            # mass = 25598.9578654481
                            # mass = 1
                            ifc = self.system.second_order[self.system.index_first_cell, j_at, j_pol, id_replica,i_at, i_pol]
                            prefactor =  1 / evoverdlpoly / rydbergoverev * (bohroverangstrom ** 2) * np.exp (phase) / mass
            
                            dyn_s[i_dim, j_dim] += prefactor * ifc
                            # print(i_dim + 1, j_dim + 1, self.system.list_of_indices[id_replica] % self.k_size + 1)
                            # print(dyn_s[i_dim, j_dim])
                            for alpha in range (3):
                                # perturb[alpha, i_at, :, j_at, :] += 1j * dxij[alpha] * dynmat[self.system.index_first_cell, j_at, :, id_replica, i_at, :] * np.exp (phase)
                                ddyn_s[alpha, i_dim, j_dim] += -1j * prefactor * ifc * self.system.list_of_replicas[ id_replica][alpha] / bohroverangstrom #*toTHz*bohr2nm
                            # print(id_replica, i_pol,j_pol,i_at,j_at,ddyn_s[:,i_at, i_pol, j_at, j_pol])

                            # print('')
        

        is_classical = False
        sh_par = {'classical': is_classical, 'convergence': True, 'only_gamma': False}
        k_mesh = np.array ([3, 3, 3])
        shl = ShengbteHelper (self.system, k_mesh, sh_par)
        dyn_k, ddyn_k = shl.read_file ()
        ddyn_k *= toTHz*bohr2nm
        
        
        # dyn = dyn_s.swapaxes(0,2).swapaxes(1,3)
        dyn = dyn_s.reshape(n_particles * 3, n_particles * 3)
        # ddyn = ddyn_s.swapaxes(1,3).swapaxes(2,4)
        ddyn = ddyn_s.reshape(3,n_particles * 3, n_particles * 3)

        out = calculate_eigenvec (dyn.reshape (n_particles * 3, n_particles * 3))
        eigenvals, eigenvects = out[0], out[1]
        # idx = eigenvals.argsort ()
        # eigenvals = eigenvals[idx]
        # eigenvects = eigenvects[:, idx]
        
        
        frequencies = np.abs (eigenvals) ** .5 * np.sign(eigenvals) / (np.pi * 2.)


        velocities = np.zeros((frequencies.shape[0], 3))
        for alpha in range (3):
            # perturbdx = perturb[alpha, :, :, :, :].reshape (n_particles * 3, n_particles * 3)

            # np.real (np.dot (eigenvects[:, 0],
            #                  np.matmul (ddyn_s[0, :, :, :, :].reshape (3 * n_particles, 3 * n_particles),
            #                             eigenvects[:, 0])))

            for i in range(3 * n_particles):
                vel = (eigenvects[:, i].conj()).dot (np.matmul (ddyn[alpha, :, :], eigenvects[:, i])).real
    
                if frequencies[i] != 0:
    
                    velocities[i, alpha] = vel / (2 * (2 * np.pi) * frequencies[i])
    
        return frequencies * toTHz, eigenvals, eigenvects, velocities*toTHz*bohr2nm

    
    def density_of_states(self, frequencies):
        n_k_points = np.prod (self.k_size)
        n_modes = frequencies.shape[-1]
        # increase_factor = 3
        omega_kl = np.zeros(( n_k_points, n_modes))
        for mode in range(n_modes):
            omega_kl[:, mode] = frequencies[:,:,:,mode].flatten()
        delta = 1.
        # Energy axis and dos
        omega_e = np.linspace (0., np.amax (omega_kl) + 5e-3, num=100)
        dos_e = np.zeros_like (omega_e)
        
        # Sum up contribution from all q-points and branches
        for omega_l in omega_kl:
            diff_el = (omega_e[:, np.newaxis] - omega_l[np.newaxis, :]) ** 2
            dos_el = 1. / (diff_el + (0.5 * delta) ** 2)
            dos_e += dos_el.sum (axis=1)
        
        dos_e *= 1. / (n_k_points * np.pi) * 0.5 * delta
        return omega_e, dos_e
        
    
    def calculate_second_all_grid(self):
        n_k_points = np.prod(self.k_size)
        n_unit_cell = self.system.second_order.shape[1]
        frequencies = np.zeros((n_k_points, n_unit_cell * 3))
        eigenvalues = np.zeros((n_k_points, n_unit_cell * 3))
        eigenvectors = np.zeros((n_k_points, n_unit_cell * 3, n_unit_cell * 3)).astype(np.complex)
        velocities = np.zeros((n_k_points, n_unit_cell * 3, 3))

        unit_cell_inv = np.linalg.inv (self.system.configuration.cell)
        cell = self.system.configuration.cell
        rlatticevec = np.linalg.inv (cell) * np.linalg.det (cell)
        V = np.abs (rlatticevec[0].dot (cell[0]))
        rlatticevec = 2 * np.pi / V * rlatticevec
        
        for index_k in range(np.prod(self.k_size)):
            # print(q_vec)
            k_point = np.unravel_index(index_k, self.k_size)
            # k_point = np.array([k_0/(1. * self.k_size[0]), k_1/(1. * self.k_size[1]), k_2/(1. * self.k_size[2])])
            freq, eval, evect, vels = self.diagonalize_second_order_k (k_point / self.k_size)
            frequencies[index_k, :] = freq
            eigenvalues[index_k, :] = eval
            eigenvectors[index_k, :, :] = evect
            velocities[index_k, :, :] = vels


        
        self._frequencies = frequencies
        self._eigenvalues = eigenvalues
        # self._velocities = np.flip(velocities, axis=4)
        self._velocities = velocities
        self._eigenvectors = eigenvectors


    
    
    
    
    def calculate_occupations(self):
        omegaK = 1.4387752

        # 1 / cm --> K
        temp = self.system.temperature
        
        # thz to 1/cm
        energies = self.frequencies.squeeze()
        eigenvalues = energies / 2.997924580e-2
        ndim = eigenvalues.shape[0]
        occupation = np.zeros (ndim)
        occupaclas = np.zeros (ndim)
        for i in range (ndim):
            occupation[i] = 1. / (np.exp (eigenvalues[i] * omegaK / temp) - 1.)
            occupaclas[i] = temp / eigenvalues[i] / omegaK
        if self.is_classic == True:
            self.occupations = occupaclas
        else:
            self.occupations = occupation
    
    def calculate_single_gamma(self, domega, index_phonons, in_ph, delta='triangular'):
        if delta == 'triangular':
            conservation_delta = self.triangular_delta
        else:
            conservation_delta = self.gaussian_delta
        energies = self.frequencies.squeeze()
        n_phonons = energies.shape[0]
        gamma_plus = 0
        gamma_minus = 0
        sigma = domega / 4.135
        
        # print (index_phonons)
        single_en = energies[index_phonons]
        en_p = energies[:, np.newaxis]
        en_pp = energies[np.newaxis, :]
        dens_p = self.occupations[:, np.newaxis]
        dens_pp = self.occupations[np.newaxis, :]
        
        delta_e_plus = np.abs (single_en - en_p - en_pp)
        coords_plus = np.array (np.argwhere ((delta_e_plus < sigma)), dtype=int)
        coords_plus = coords_plus[((coords_plus[:, 0] >= in_ph) & (coords_plus[:, 1] >= in_ph))].T
        
        delta_e_minus = np.abs (single_en + en_p - en_pp)
        coords_minus = np.array (np.argwhere ((delta_e_minus < sigma)), dtype=int)
        coords_minus = coords_minus[((coords_minus[:, 0] >= in_ph) & (coords_minus[:, 1] >= in_ph))].T
        
        if (coords_plus.size != 0) | (coords_minus.size != 0):
            third_sparse_plus, third_sparse_minus = self.project_third (index_phonons, coords_plus, coords_minus)
        
        if (coords_plus.size != 0):
            phase_space_value_plus = conservation_delta ([delta_e_plus, sigma])
            indexes = (coords_plus[0], coords_plus[1])
            vol_plus = 0.5 * ((1 + dens_p + dens_pp) / (en_p * en_pp))
            delta_plus = COO (coords_plus, vol_plus[indexes] * phase_space_value_plus[indexes],
                              shape=(n_phonons, n_phonons))
            third_sparse_plus = third_sparse_plus ** 2 * delta_plus / 16 / np.pi ** 4
            gamma_plus += third_sparse_plus.sum (axis=1).sum (axis=0)
        
        if (coords_minus.size != 0):
            phase_space_value_minus = conservation_delta ([delta_e_minus, sigma])
            indexes = (coords_minus[0], coords_minus[1])
            vol_minus = ((dens_p - dens_pp) / (en_p * en_pp))
            delta_minus = COO (coords_minus, vol_minus[indexes] * phase_space_value_minus[indexes],
                               shape=(n_phonons, n_phonons))
            third_sparse_minus = third_sparse_minus ** 2 * delta_minus / 16 / np.pi ** 4
            gamma_minus += third_sparse_minus.sum (axis=1).sum (axis=0)
        
        hbar = 6.35075751
        coeff = hbar ** 2 * np.pi / 4. / 9.648538 / energies[index_phonons]
        return gamma_minus * coeff, gamma_plus * coeff
    
    
    def gaussian_delta(self, params):
        # alpha is a factor that tells whats the ration between the width of the gaussian and the width of allowed phase space
        alpha = 2
        
        delta_energy = params[0]
        # allowing processes with width sigma and creating a gaussian with width sigma/2 we include 95% (erf(2/sqrt(2)) of the probability of scattering. The erf makes the total area 1
        sigma = params[1] / alpha
        return 1 / np.sqrt (2 * np.pi * sigma ** 2) * np.exp (- delta_energy ** 2 / (2 * sigma ** 2)) / np.erf(alpha / np.sqrt(2))
    
    
    def triangular_delta(self, params):
        deltaa = np.abs (params[0])
        domega = params[1]
        return 1. / domega * (1 - deltaa / domega)
    
    
    def project_third(self, phonon_index, coords_plus, coords_minus):
        energies = self.frequencies.squeeze()
        n_phonons = energies.shape[0]
        n_atoms = int (n_phonons / 3)
        evects = self.eigenvectors.squeeze()
        
        sparse_third = self.system.third_order.dot (evects[:, phonon_index])
        
        # TODO: Maybe we need to replace (phonon_index % n_atoms) with int(phonon_index / 3)
        atom_mass = self.system.configuration.get_masses ()[phonon_index % n_atoms]
        sparse_third /= np.sqrt (atom_mass)
        sparse_third = sparse_third.reshape ((n_atoms, 3, n_atoms, 3))
        
        masses_i = self.system.configuration.get_masses ()[:, np.newaxis]
        masses_j = self.system.configuration.get_masses ()[np.newaxis, :]
        sqrt_masses = np.sqrt (masses_i * masses_j)
        sparse_third[:, :, :, :] /= sqrt_masses[:, np.newaxis, :, np.newaxis]
        sparse_third = sparse_third.reshape ((n_phonons, n_phonons))
        
        sparse_third = evects.T.dot (sparse_third).dot (evects)
        coords_minus = (coords_minus[0], coords_minus[1])
        coords_plus = (coords_plus[0], coords_plus[1])
        sparse_plus = COO (coords_plus, sparse_third[coords_plus], shape=(n_phonons, n_phonons))
        sparse_minus = COO (coords_minus, sparse_third[coords_minus], shape=(n_phonons, n_phonons))
        return sparse_plus, sparse_minus
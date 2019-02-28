import numpy as np
from scipy.sparse import csc_matrix

LENGTH_THREESHOLD = 1e20
THREESHOLD = 1e-20
MAX_ITERATIONS_SC = 1000



def calculate_transmission(phonons, velocities, length):
    prefactor = csc_matrix ((1. / velocities, (range(phonons.n_phonons), range(phonons.n_phonons))), shape=(phonons.n_phonons, phonons.n_phonons),
                             dtype=np.float32)
    gamma_unitless = prefactor.dot (phonons.scattering_matrix)
    matthiesen_correction = csc_matrix ((np.sign (velocities)/length, (range(phonons.n_phonons), range(phonons.n_phonons))), shape=(phonons.n_phonons, phonons.n_phonons),
                             dtype=np.float32)
    gamma_unitless_tilde = gamma_unitless + matthiesen_correction
    
    transmission = np.linalg.inv (gamma_unitless_tilde.toarray())
    
    # gamma_unitless = np.diag (length / np.abs(velocities)).dot (gamma)
    # kn = np.linalg.inv(gamma_unitless)
    # func = lambda x : (1. - 1. / x * (1. - np.exp(-1. *  x))) * 1. / x
    # transmission = function_of_operator(func, gamma_unitless)
    
    # gamma_unitless = np.diag (length / np.abs(velocities)).dot (gamma)
    # kn = np.linalg.inv(gamma_unitless)
    # one = np.identity(phonons.n_phonons())
    # transmission = (one - kn.dot(one - expm(-gamma_unitless))).dot(kn)
    
    return (transmission / length)

def exact_conductivity(phonons, is_classical=False, l_x=LENGTH_THREESHOLD, l_y=LENGTH_THREESHOLD,
                       l_z=LENGTH_THREESHOLD, alpha=0, beta=0):
    volume = np.linalg.det(phonons.atoms.cell) / 1000.

    length = np.array([l_x, l_y, l_z])
    conductivity_per_mode = np.zeros ((phonons.n_phonons))
    # gamma_full = np.diag (1. / (phonons.tau_zero + THREESHOLD)) - np.array (phonons.gamma.toarray ()) +
    # THREESHOLD
    # gamma_full = np.array (phonons.gamma.toarray ())
    
    transmission = phonons.calculate_transmission (phonons.velocities[:, alpha], length[alpha]) * length[alpha]
    
    conductivity_per_mode[:] = phonons.c_v * (phonons.velocities[:, beta].dot(transmission))
    
    conductivity = np.sum (conductivity_per_mode, 0) / phonons.n_k_points / volume
    return conductivity

def transmission_matthiesen(phonons, rate, velocity, length):
    # TODO: this is not exacly a transmission function, change the names to match the right units.
    # trans =  (rates + abs (velocity) / length) ** (-1)
    # return trans
    trans = (rate + abs (velocity) / length) ** (-1)
    return trans


def transmission_infinite(rate, velocity, length):
    return 1. / (rate + THREESHOLD)

def transmission_caltech(phonons, rate, velocity, length):
    kn = abs (velocity / (length * rate))
    trans = (1 - kn * (1 - np.exp (- 1. / kn))) * kn
    return trans * length / abs (velocity)

def calculate_conductivity(phonons, length_thresholds=None):
    volume = np.linalg.det(phonons.atoms.cell) / 1000
    velocities = phonons.velocities.real.reshape((phonons.n_k_points, phonons.n_modes, 3), order='C')
    velocities /= 10

    velocities = velocities.reshape((phonons.n_phonons, 3), order='C')
    c_v = phonons.c_v.reshape((phonons.n_phonons), order='C')

    frequencies = phonons.frequencies.reshape((phonons.n_k_points * phonons.n_modes), order='C')
    physical_modes = frequencies > phonons.energy_threshold

    index = np.outer(physical_modes, physical_modes)

    conductivity_per_mode = np.zeros((phonons.n_phonons, 3, 3))

    for alpha in range(3):
        # TODO: here we can probably avoid allocating the tensor new everytime
        scattering_matrix = np.zeros((phonons.n_phonons, phonons.n_phonons))
        scattering_matrix[index] = -1 * phonons.scattering_matrix.reshape((phonons.n_phonons,
                                                                                phonons.n_phonons), order='C')[index]
        scattering_matrix += np.diag(phonons.gamma.flatten(order='C'))
        scattering_matrix = scattering_matrix[index].reshape((physical_modes.sum(), physical_modes.sum()), order='C')
        if length_thresholds:
            if length_thresholds[alpha]:
                scattering_matrix[:, :] += np.diag(np.abs(velocities[physical_modes, alpha]) / length_thresholds[
                    alpha])

        gamma_inv = np.linalg.inv(scattering_matrix)

        gamma_inv = 1 / (frequencies[physical_modes, np.newaxis]) * (gamma_inv * frequencies[np.newaxis, physical_modes])

        # plt.show()
        for beta in range(3):
            lambd = gamma_inv.dot(velocities[physical_modes, beta])
            
            conductivity_per_mode[physical_modes, alpha, beta] = 1 / (volume * phonons.n_k_points) * c_v[physical_modes] *\
                                                                     velocities[physical_modes, alpha] * lambd
            
    return conductivity_per_mode


def calculate_conductivity_sc(phonons, tolerance=0.01, length_thresholds=None, is_rta=False):
    volume = np.linalg.det(phonons.atoms.cell) / 1000
    velocities = phonons.velocities.real.reshape((phonons.n_k_points, phonons.n_modes, 3), order='C')
    velocities /= 10
    if not is_rta:
        # TODO: clean up the is_rta logic
        scattering_matrix = phonons.scattering_matrix.reshape((phonons.n_phonons,
                                                                    phonons.n_phonons), order='C')
    F_n_0 = np.zeros((phonons.n_k_points * phonons.n_modes, 3))
    velocities = velocities.reshape((phonons.n_phonons, 3), order='C')
    frequencies = phonons.frequencies.reshape((phonons.n_phonons), order='C')
    physical_modes = (frequencies > phonons.energy_threshold)

    for alpha in range(3):
        gamma = np.zeros(phonons.n_phonons)

        for mu in range(phonons.n_phonons):
            if length_thresholds:
                if length_thresholds[alpha]:
                    gamma[mu] = phonons.gamma.reshape((phonons.n_phonons), order='C')[mu] + \
                                np.abs(velocities[mu, alpha]) / length_thresholds[alpha]
                else:
                    gamma[mu] = phonons.gamma.reshape((phonons.n_phonons), order='C')[mu]

            else:
                gamma[mu] = phonons.gamma.reshape((phonons.n_phonons), order='C')[mu]
        tau_zero = np.zeros_like(gamma)
        tau_zero[gamma > phonons.gamma_cutoff] = 1 / gamma[gamma > phonons.gamma_cutoff]
        F_n_0[:, alpha] = tau_zero[:] * velocities[:, alpha] * 2 * np.pi * frequencies[:]
    c_v = phonons.c_v.reshape((phonons.n_phonons), order='C')
    F_n = F_n_0.copy()
    conductivity_per_mode = np.zeros((phonons.n_phonons, 3, 3))
    avg_conductivity = 0
    for n_iteration in range(MAX_ITERATIONS_SC):
        for alpha in range(3):
            for beta in range(3):
                conductivity_per_mode[physical_modes, alpha, beta] = 1 / (volume * phonons.n_k_points) * c_v[
                    physical_modes] / (2 * np.pi * frequencies[physical_modes]) * velocities[
                                                                         physical_modes, alpha] * F_n[
                                                                         physical_modes, beta]

        if is_rta:
            return conductivity_per_mode
        
        new_avg_conductivity = np.diag(np.sum(conductivity_per_mode, 0)).mean()
        if avg_conductivity:
            if np.abs(avg_conductivity - new_avg_conductivity) < tolerance:
                return conductivity_per_mode
        avg_conductivity = new_avg_conductivity
    
        # If the tolerance has not been reached update the state
        tau_zero = tau_zero.reshape((phonons.n_phonons), order='C')
        # calculate the shift in mft
        DeltaF = scattering_matrix.dot(F_n)

        for alpha in range(3):
            F_n[:, alpha] = F_n_0[:, alpha] + tau_zero[:] * DeltaF[:, alpha]

    for alpha in range(3):
        for beta in range(3):
            conductivity_per_mode[physical_modes, alpha, beta] = 1 / (volume * phonons.n_k_points) * c_v[physical_modes] / (2 * np.pi * frequencies[physical_modes]) * velocities[physical_modes, alpha] * F_n[physical_modes, beta]

    conductivity = conductivity_per_mode
    if n_iteration == (MAX_ITERATIONS_SC - 1):
        print('Convergence not reached')
    return conductivity

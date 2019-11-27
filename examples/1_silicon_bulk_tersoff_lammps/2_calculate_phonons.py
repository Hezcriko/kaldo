from ballistico.finitedifference import FiniteDifference
from ballistico.phonons import Phonons
import matplotlib.pyplot as plt
import ballistico.controllers.conductivity as bac
from ase.io import read
import numpy as np

supercell = np.array([3, 3, 3])
# finite_difference = FiniteDifference.import_from_dlpoly_folder('si-dlpoly', supercell)
folder = '.'
config_file = str(folder) + '/replicated_coords.lmp'
dynmat_file = str(folder) + '/dynmat.dat'
third_file = str(folder) + '/third.bin'
atoms = read(config_file, format='lammps-data', style='atomic')

atomic_numbers = atoms.get_atomic_numbers()
atomic_numbers[atomic_numbers == 1] = 14
atoms.set_atomic_numbers(atomic_numbers)

finite_difference = FiniteDifference.import_from_files(atoms, dynmat_file, third_file, folder, supercell)


k = 5
kpts = [k, k, k]
is_classic = False
temperature = 300

# # Create a phonon object
phonons = Phonons(finite_difference=finite_difference,
                  kpts=kpts,
                  is_classic=is_classic,
                  temperature=temperature)

print('AF conductivity')
print(bac.conductivity(phonons, method='qhgk').sum(axis=0))

plt.scatter(phonons.frequencies.flatten()[3:], phonons.gamma.flatten()[3:], s=5)
plt.ylabel('gamma_THz', fontsize=16, fontweight='bold')
plt.xlabel("$\\nu$ (Thz)", fontsize=16, fontweight='bold')
plt.show()

plt.scatter(phonons.frequencies.flatten()[3:], phonons.ps.flatten()[3:], s=5)
plt.ylabel('ps', fontsize=16, fontweight='bold')
plt.xlabel("$\\nu$ (Thz)", fontsize=16, fontweight='bold')
plt.show()
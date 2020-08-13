from kaldo.observables.forceconstant import ForceConstant
from ase import Atoms
import os
import ase.io
import numpy as np
from kaldo.interface.eskm_io import import_from_files
import kaldo.interface.shengbte_io as shengbte_io
from kaldo.controllers.displacement import calculate_second
from kaldo.helpers.logger import get_logger
logging = get_logger()

SECOND_ORDER_FILE = 'second.npy'




def acoustic_sum_rule(dynmat):
    n_unit = dynmat[0].shape[0]
    sumrulecorr = 0.
    for i in range(n_unit):
        off_diag_sum = np.sum(dynmat[0, i, :, :, :, :], axis=(-2, -3))
        dynmat[0, i, :, 0, i, :] -= off_diag_sum
        sumrulecorr += np.sum(off_diag_sum)
    logging.info('error sum rule: ' + str(sumrulecorr))
    return dynmat


class SecondOrder(ForceConstant):
    def __init__(self, *kargs, **kwargs):
        ForceConstant.__init__(self, *kargs, **kwargs)
        try:
            self.is_acoustic_sum = kwargs['is_acoustic_sum']
        except KeyError:
            self.is_acoustic_sum = False

        self.value = kwargs['value']
        if self.is_acoustic_sum:
            self.value = acoustic_sum_rule(self.value)
        self.n_modes = self.atoms.positions.shape[0] * 3
        self._list_of_replicas = None


    @classmethod
    def from_supercell(cls, atoms, grid_type, supercell=None, value=None, is_acoustic_sum=False, folder='kALDo'):
        if value is not None and is_acoustic_sum is not None:
            value = acoustic_sum_rule(value)
        ifc = super(SecondOrder, cls).from_supercell(atoms, supercell, grid_type, value, folder)
        return ifc


    @classmethod
    def load(cls, folder, supercell=(1, 1, 1), format='numpy', is_acoustic_sum=False):
        if format == 'numpy':
            if folder[-1] != '/':
                folder = folder + '/'
            replicated_atoms_file = 'replicated_atoms.xyz'
            config_file = folder + replicated_atoms_file
            replicated_atoms = ase.io.read(config_file, format='extxyz')

            n_replicas = np.prod(supercell)
            n_total_atoms = replicated_atoms.positions.shape[0]
            n_unit_atoms = int(n_total_atoms / n_replicas)
            unit_symbols = []
            unit_positions = []
            for i in range(n_unit_atoms):
                unit_symbols.append(replicated_atoms.get_chemical_symbols()[i])
                unit_positions.append(replicated_atoms.positions[i])
            unit_cell = replicated_atoms.cell / supercell

            atoms = Atoms(unit_symbols,
                          positions=unit_positions,
                          cell=unit_cell,
                          pbc=[1, 1, 1])

            _second_order = np.load(folder + SECOND_ORDER_FILE, allow_pickle=True)
            second_order = SecondOrder(atoms=atoms,
                                       replicated_positions=replicated_atoms.positions,
                                       supercell=supercell,
                                       value=_second_order,
                                       is_acoustic_sum=is_acoustic_sum,
                                       folder=folder)

        elif format == 'eskm' or format == 'lammps':
            dynmat_file = str(folder) + "/Dyn.form"
            if format == 'eskm':
                config_file = str(folder) + "/CONFIG"
                replicated_atoms = ase.io.read(config_file, format='dlp4')
            elif format == 'lammps':
                config_file = str(folder) + "/replicated_atoms.xyz"
                replicated_atoms = ase.io.read(config_file, format='extxyz')
            n_replicas = np.prod(supercell)
            n_total_atoms = replicated_atoms.positions.shape[0]
            n_unit_atoms = int(n_total_atoms / n_replicas)
            unit_symbols = []
            unit_positions = []
            for i in range(n_unit_atoms):
                unit_symbols.append(replicated_atoms.get_chemical_symbols()[i])
                unit_positions.append(replicated_atoms.positions[i])
            unit_cell = replicated_atoms.cell / supercell

            atoms = Atoms(unit_symbols,
                          positions=unit_positions,
                          cell=unit_cell,
                          pbc=[1, 1, 1])


            _second_order, _ = import_from_files(replicated_atoms=replicated_atoms,
                                                 dynmat_file=dynmat_file,
                                                 supercell=supercell)
            second_order = SecondOrder(atoms=atoms,
                                       replicated_positions=replicated_atoms.positions,
                                       supercell=supercell,
                                       value=_second_order,
                                       is_acoustic_sum=is_acoustic_sum,
                                       folder=folder)
        elif format == 'shengbte' or format == 'shengbte-qe':

            config_file = folder + '/' + 'CONTROL'
            try:
                atoms, supercell = shengbte_io.import_control_file(config_file)
            except FileNotFoundError as err:
                config_file = folder + '/' + 'POSCAR'
                logging.info('\nTrying to open POSCAR')
                atoms = ase.io.read(config_file)

            # Create a finite difference object
            # TODO: we need to read the grid type here
            is_qe_input = (format == 'shengbte-qe')
            n_replicas = np.prod(supercell)
            n_unit_atoms = atoms.positions.shape[0]
            if is_qe_input:
                filename = folder + '/espresso.ifc2'
                second_order, supercell = shengbte_io.read_second_order_qe_matrix(filename)
                second_order = second_order.reshape((n_unit_atoms, 3, n_replicas, n_unit_atoms, 3))
                second_order = second_order.transpose(3, 4, 2, 0, 1)
                grid_type = 'F'
            else:
                second_order = shengbte_io.read_second_order_matrix(folder, supercell)
                second_order = second_order.reshape((n_unit_atoms, 3, n_replicas, n_unit_atoms, 3))
                grid_type = 'C'
            second_order = SecondOrder.from_supercell(atoms=atoms,
                                                      grid_type=grid_type,
                                                      supercell=supercell,
                                                      value=second_order[np.newaxis, ...],
                                                      is_acoustic_sum=True,
                                                      folder=folder)



        elif format == 'hiphive':
            filename = 'atom_prim.xyz'
            # TODO: add replicated filename in example
            replicated_filename = 'replicated_atoms.xyz'
            try:
                import kaldo.interface.hiphive_io as hiphive_io
            except ImportError:
                logging.error('In order to use hiphive along with kaldo, hiphive is required. \
                      Please consider installing hihphive. More info can be found at: \
                      https://hiphive.materialsmodeling.org/')

            atom_prime_file = str(folder) + '/' + filename
            replicated_atom_prime_file = str(folder) + '/' + replicated_filename
            # TODO: Make this independent of replicated file
            atoms = ase.io.read(atom_prime_file)
            replicated_atoms = ase.io.read(replicated_atom_prime_file)

            # Create a finite difference object
            if 'model2.fcs' in os.listdir(str(folder)):
                _second_order = hiphive_io.import_second_from_hiphive(folder, np.prod(supercell),
                                                                      atoms.positions.shape[0])
                second_order = SecondOrder(atoms=atoms,
                                           replicated_positions=replicated_atoms.positions,
                                           supercell=supercell,
                                           value=_second_order,
                                           folder=folder)


        else:
            raise ValueError
        return second_order


    def calculate(self, calculator, delta_shift=1e-3, is_storing=True, is_verbose=False):
        atoms = self.atoms
        replicated_atoms = self.replicated_atoms
        atoms.set_calculator(calculator)
        replicated_atoms.set_calculator(calculator)

        if is_storing:
            try:
                self.value = SecondOrder.load(folder=self.folder, supercell=self.supercell, format='numpy',
                                                is_acoustic_sum=self.is_acoustic_sum).value

            except FileNotFoundError:
                logging.info('Second order not found. Calculating.')
                self.value = calculate_second(atoms, replicated_atoms, delta_shift, is_verbose)
                self.save('second')
                ase.io.write(self.folder + '/replicated_atoms.xyz', self.replicated_atoms, 'extxyz')
            else:
                logging.info('Reading stored second')
        else:
            self.value = calculate_second(atoms, replicated_atoms, delta_shift, is_verbose)
            self.save('second')
            ase.io.write('/replicated_atoms.xyz', self.replicated_atoms, 'extxyz')
        if self.is_acoustic_sum:
            self.value = acoustic_sum_rule(self.value)

    def __str__(self):
        return 'second'
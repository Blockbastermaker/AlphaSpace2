import nglview as nv
import numpy as np
from mdtraj import shrake_rupley

from AS_Cluster import AS_D_Pocket
from AS_Config import AS_Config
from AS_Funct import screen_by_contact
from AS_Struct import AS_Structure


# noinspection PyAttributeOutsideInit,PyAttributeOutsideInit,PyAttributeOutsideInit,PyAttributeOutsideInit,PyAttributeOutsideInit,PyAttributeOutsideInit
class AS_Universe(object):
    def __init__(self, receptor=None, binder=None, guess_receptor_binder=True, guess_by_order=True, config=None):
        """
        Container for an AlphaSpace session, have child container receptor and binder
        :param receptor: object
        :param binder: object
        :param guess_by_order: book
        :param guess_receptor_binder: bool, guess is based on molecule size
        :param config: object,AS_config
        """

        if config is not None:
            self.config = config
        else:
            self.config = AS_Config()

        self.set_receptor(receptor)
        self.set_binder(binder)

        if guess_receptor_binder and receptor:
            self.guess_receptor_binder(receptor, guess_by_order)

        self.others = None
        self.view = None

        self._d_pockets = {}

    def __repr__(self):
        return "Receptor of {} residues {} atoms | Binder of {} residues {} atoms".format(self.receptor.n_residues,
                                                                                          self.receptor.n_atoms,
                                                                                          self.binder.n_residues,
                                                                                          self.binder.n_atoms)
    @property
    def _data(self):
        return self.receptor._data
    @property
    def frames(self):
        for i in range(self.n_frames):
            yield i

    # @property
    # def clusters(self):
    #     """
    #     return list of clusters
    #     :return: list
    #     """
    #     return self.receptor.clusters

    @property
    def n_frames(self):
        if self.receptor is None:
            return 0
        else:
            return self.receptor.trajectory.n_frames

    @property
    def n_atoms(self) -> int:
        """
        return the total number of atoms in receptor and binders
        :return: int
        """
        return self.receptor.n_atoms + self.binder.n_atoms

    @property
    def n_residues(self):
        """
        return the total number of residues in the receptor and binder
        :return: int
        """
        return self.receptor.n_residues + self.binder.n_residues

    @property
    def molecules(self):
        """
        iterate over receptor and binder, if there is any
        :return: iter
        """
        for m in self.receptor, self.binder:
            if m is not None:
                yield m
            else:
                continue

    @property
    def d_pockets(self) -> AS_D_Pocket:
        """
        calculate the d pockets and give a iterator os AS_D_Pocket
        :return: object, AS_D_Pocket
        """
        if not self._d_pockets:
            self._d_pockets = list(self.receptor._gen_d_pockets())
        for p in self._d_pockets:
            yield p

    def d_pocket(self, i) -> AS_D_Pocket:
        if not self._d_pockets:
            self._d_pockets = self.receptor._gen_d_pockets()
        return self._d_pockets[i]

    # def _is_processed(self, snapshot_idx: int) -> bool:
    #     if snapshot_idx in self.receptor._clusters:
    #         return True
    #     else:
    #         return False

    def pockets(self, snapshot_idx):
        for pocket in self.receptor.pockets(snapshot_idx):
            yield pocket

    # def cluster(self, snapshot_idx: int = 0) -> object:
    #     """
    #     return list of clusters
    #     :param snapshot_idx: int
    #     :return: object, AS_Cluster
    #     """
    #     return self.receptor._clusters[snapshot_idx]

    def guess_receptor_binder(self, traj, by_order: bool = True) -> bool:
        """
        Divide receptor trajectory based on connectivity, set larger molecule as receptor.
        This process automatically removes water and other solvents
        :param traj: target trajectory
        :param by_order: bool, if False, guess by appearances in file
        :return: bool, if any macro molecule were found.
        """
        if traj is None:
            raise Exception("Cannot guess receptor and binder, no structure detected")
        molecule_list = []
        # remove solvent and divide into molecules. This will guess which one is the
        for molecule in traj.topology.find_molecules():
            if len(molecule) > 1 and not next(iter(molecule)).residue.is_water:
                molecule_list.append(molecule)
            else:
                continue

        if not by_order:
            molecule_list.sort(key=len, reverse=True)
        if len(molecule_list) > 1:
            self.set_receptor(traj.atom_slice([atom.index for atom in molecule_list[0]]))
            self.set_binder(traj.atom_slice([atom.index for atom in molecule_list[1]]))
            return True
        elif len(molecule_list) == 1:
            self.set_receptor(traj.atom_slice([atom.index for atom in molecule_list[0]]))
            self.binder = None
            return True
        else:
            return False

    def set_binder(self, structure: object, append=False):
        """
        set binder (ligand) in session
        :param structure: object, trajectory
        :param append: Bool, if the new binder should be appended to the preview one, default overwritten.
        :return:
        """
        if structure is None:
            self.binder = None
            return
        if append and (self.binder is not None):
            x = self.binder.trajectory + structure
            self.binder.trajectory = x
        else:
            self.binder = AS_Structure(structure, structure_type=1, parent=self)

    def set_receptor(self, structure: object, append=False):
        """
        set receptor (protein) in session
        :param structure: object, trajectory
        :param append: Bool, if the new binder should be appended to the preview one, default overwritten.
        :return:
        """
        if structure is None:
            self.receptor = None
            return

        if append and (self.receptor is not None):
            x = self.receptor.trajectory + structure
            self.receptor.trajectory = x

        else:
            self.receptor = AS_Structure(structure, structure_type=0, parent=self)

    def run_alphaspace(self):
        data_list = []
        for i in range(self.n_frames):
            data_list.append(self.receptor._tessellation(self.config,i))
        self.receptor._combine_data(data_list)
        self.receptor._gen_pockets()

    def run_alphaspace_mp(self):

        import multiprocessing as mp
        from AS_Funct import _tessellation

        def multiprocess(function, argslist, ncpu):
            total = len(argslist)
            done = 0
            result_queue = mp.Queue(ncpu)
            jobs = []
            res = []
            while argslist != []:
                p = mp.Process(target=function, args=(result_queue, argslist.pop(),))
                jobs.append(p)
                p.start()
                done += 1
                # print("\r", float(done) / total * 100, "%")  # here is to keep track
            tmp = [result_queue.get() for p in jobs]
            for r in tmp:
                res.append(r)
            return res

        snapshots = [self.receptor.traj[i] for i in range(self.n_frames)]
        config = [self.config for i in range(self.n_frames)]
        snapshot_indices = range(self.n_frames)
        is_polar = [self.receptor.is_polar for _ in range(self.n_frames)]
        arglist = list(zip(snapshots,config,snapshot_indices,is_polar))

        data_list = multiprocess(_tessellation,arglist,mp.cpu_count())

        self.receptor._combine_data(data_list)


    def _get_face_atoms(self):
        """
        Calculate the snapshot interface atom.
        The interface atom is defined as whose ASA is reduced with introduction of ligand.
        :param snapshot_idx: int
        :return: numpy.array
        """
        receptor_snapshot = self.receptor.traj

        complex_snapshot = receptor_snapshot.stack(self.binder.traj)

        receptor_snapshot_sasa = shrake_rupley(receptor_snapshot)

        complex_snapshot_sasa = shrake_rupley(complex_snapshot)

        sasa_diff = receptor_snapshot_sasa - complex_snapshot_sasa[:,:len(receptor_snapshot_sasa)]

        return np.where((sasa_diff > 0).any(axis=0))[0]

    def screen_pockets(self):
        assert len(list(self.receptor._data.snapshots)) == self.n_frames
        data = self.receptor._data
        data.activate(data.all_idx)

        if self.config.screen_by_lig_cntct:
            screen_by_contact(data, self.binder.trajectory.xyz, self.config.contact_threshold)
            contact_alpha_row = data[data[:,12] == 1]
            contact_pocket_idx = np.unique(contact_alpha_row[:,[1,13]],axis=0)
            ss_pocket_data = data[:,[1,13]]
            data.activate(data.all_idx)
            all_active_pocket_alpha_idx = []
            for pocket_idx in contact_pocket_idx:
                deactive_pocket_alpha_idx =np.where((ss_pocket_data == pocket_idx).all(axis=1))[0]
                all_active_pocket_alpha_idx.extend(deactive_pocket_alpha_idx)
            data.deactivate(all_active_pocket_alpha_idx)

        if self.config.screen_by_face:
            interface_atom_idx = np.sort(self._get_face_atoms())
            for snapshot_idx in range(self.n_frames):
                for pocket in self.pockets(snapshot_idx):
                    if len(np.intersect1d(pocket.lining_atoms,interface_atom_idx,True)) == 0:
                        data[pocket.alphas,11] = 0


        if self.config.screen_by_score:
            assert self.config.min_score > 0
            for snapshot_idx in range(self.n_frames):
                for pocket in self.pockets(snapshot_idx):
                    if pocket.total_score < self.config.min_score:
                        pocket.deactivate()

    """
    Visualization methods
    """

    def view_snapshot(self, snapshot_idx: int = 0) -> object:
        self.show_receptor(snapshot_idx)
        self.show_binder(snapshot_idx)
        self.show_pocket(snapshot_idx)
        return self.view

    def show_receptor(self, snapshot_idx=0):
        self.view = nv.show_mdtraj(self.receptor.trajectory[snapshot_idx], gui=True)
        self.receptor_view = self.view.component_0
        self.receptor_view.clear_representations()
        self.receptor_view.add_surface(selection='protein', opacity=1, color='white')

    def show_pocket_label(self):
        self.view.component_2.add_representation(repr_type='label', lableType='residueindex', color='residueindex')

    def show_binder(self, snapshot_idx=0):
        self.binder_view = self.view.add_trajectory(self.binder.trajectory[snapshot_idx])

    def show_pocket(self, snapshot_idx=0):
        self.pocket_view = self.view.add_trajectory(self.receptor.cluster(snapshot_idx).traj)
        self.pocket_view.clear_representations()
        self.pocket_view.add_representation(repr_type='ball+stick', selection='all', color='residueindex')


if __name__ == '__main__':
    import mdtraj
    import sys

    test_receptor_path = sys.argv[1]
    test_binder_path = sys.argv[2]

    lig_traj = mdtraj.load(test_binder_path)
    prot_traj = mdtraj.load(test_receptor_path)

    complex = AS_Universe()
    complex.set_receptor(prot_traj)
    complex.set_binder(lig_traj)
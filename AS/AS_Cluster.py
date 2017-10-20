import numpy as np
from scipy.spatial import Voronoi,Delaunay
from scipy.cluster.hierarchy import linkage,fcluster
from AS.AS_Funct import *
from mdtraj.core.topology import Topology,Residue,Atom
from mdtraj.core.trajectory import Trajectory
from mdtraj.core.element import *
from mdtraj import shrake_rupley


# noinspection PyAttributeOutsideInit,PyAttributeOutsideInit,PyAttributeOutsideInit,PyAttributeOutsideInit,PyAttributeOutsideInit,PyAttributeOutsideInit,PyTypeChecker
class AS_Cluster(object):
    def __init__(self,receptor,snapshot_idx=0):
        """
        Container for alpha, beta atoms and pocket
        :param receptor: AS_Struct
        :param snapshot_idx: int
        """
        self.snapshot_idx = snapshot_idx

        # Parent receptor attribute reference
        self.parent = receptor
        self.receptor_top = receptor.top
        self.receptor_snapshot = self.parent.trajectory[snapshot_idx]
        self.config = receptor.config
        self.is_polar = receptor.is_polar

        # Initialize Container of topology and coordinate for pockets and alpha atoms
        self.top = self.pockets = Topology()
        self.top.add_chain()
        self.top.add_residue(name='ASC',chain=self.top.chain(0))
        self.traj = Trajectory(np.zeros([1,0,3]),self.top)

        # container for coordinate in located in the trajectory object, 0 frame
        self.xyz = self.traj.xyz

        # Link pocket name change to trajectory object
        self.n_alpha = self.top.n_atoms
        self.n_pockets = self.top.n_residues
        self.alphas = self.top.atoms
        self.pockets = self.top.residues
        self.alpha = self.top.atom
        self.pocket = self.top.residue

        # Initialize storage array
        self.contact = np.empty(self.n_alpha,int)
        self.polar_score = np.empty(self.n_alpha,float)
        self.nonpolar_score = np.empty(self.n_alpha,float)
        self.total_score = np.empty(self.n_alpha,float)

        self._tessellation(self.config)
        if self.parent.structure_type == 0:
            self.oppsite_struct = self.parent.parent.binder
        elif self.parent.structure_type == 1:
            self.oppsite_struct = self.parent.parent.receptor
        else:
            self.oppsite_struct = None

    def __repr__(self):
        return "Alpha Atom cluster of #{} frame".format(self.snapshot_idx)

    def _tessellation(self,config):
        """
        perform tessellation in order to generate the cluster of alpha atoms.
        :param config: object
        """
        # Generate Raw Tessellation vertices
        raw_alpha_lining = Delaunay(self.receptor_snapshot.xyz[0]).simplices
        raw_alpha_xyz = Voronoi(self.receptor_snapshot.xyz[0]).vertices
        raw_lining_xyz = np.take(self.receptor_snapshot.xyz[0],raw_alpha_lining[:,0].flatten(),axis=0)

        # Calculate Raw alpha sphere radii
        raw_alpha_sphere_radii = np.linalg.norm(raw_lining_xyz - raw_alpha_xyz,axis=1)

        # Filter the data based on radii
        filtered_idx = np.where(np.logical_and(config.min_r / 10.0 <= raw_alpha_sphere_radii,
                                               raw_alpha_sphere_radii <= config.max_r / 10.0))[0]
        filtered_lining = np.take(raw_alpha_lining,filtered_idx,axis=0)

        self.alpha_lining = filtered_lining

        filtered_xyz = np.take(raw_alpha_xyz,filtered_idx,axis=0)

        # cluster the remaining vertices to assign index of belonging pockets
        zmat = linkage(filtered_xyz,method='average')
        cluster = fcluster(zmat,self.config.pocket_cluster_distance / 10,criterion='distance')  # /10 turn A to nm

        self.alpha_pocket_index = cluster - 1  # because cluster index start from 1

        # Reorganize into list of pockets
        self.pocket_alpha_atoms = [[] for _ in range(max(self.alpha_pocket_index) + 1)]
        for alpha_cluster_i,alpha_atom_idx in sorted(
                zip(self.alpha_pocket_index, range(len(self.alpha_pocket_index)))):
            self.pocket_alpha_atoms[alpha_cluster_i].append(alpha_atom_idx)


        # Generate Residue container for pockets and add in atoms as AAC
        for _ in self.pocket_alpha_atoms[1:]:
            residue = self.top.add_residue(name='ASC',chain=self.top.chain(0))
        for i,pocket_index in enumerate(self.alpha_pocket_index):
            atom = self.top.add_atom('AAC', None, self.top.residue(self.alpha_pocket_index[i]), i)


        update_atom_methods(Atom)
        update_residue_method(Residue)

        for pocket in self.pockets:
            alpha_index = [alpha.index for alpha in pocket.get_alphas()]
            pocket.lining_atom_idx = self._get_lining_atoms(alpha_index)
            pocket.lining_residue_idx = self._get_lining_residues(alpha_index)
        # Load trajectories
        self.traj.xyz = np.expand_dims(filtered_xyz,axis=0)
        filtered_lining_xyz = np.take(self.receptor_snapshot.xyz[0], self.alpha_lining, axis=0)
        # calculate the polarity of alpha atoms
        self.total_score = np.array([getTetrahedronVolume(i) for i in filtered_lining_xyz])

        pocket_sasa = np.take(self._get_SASA(), self.alpha_lining)

        polar_ratio = np.average(np.take(self.is_polar, self.alpha_lining), axis=1, weights=pocket_sasa)

        self.polar_score = self.total_score * polar_ratio

        self.nonpolar_score = self.total_score - self.polar_score

        self.contact = np.zeros(self.top.n_atoms,dtype=int)

    def _get_SASA(self):
        """
        Calculate the absolute solvent accessible surface area.
        First calculate the SASA of the receptor by itself, then subtract it with sasa with the AAC.
        AAC are set to resemble Carbon with a radii - 0.17
        :return: np.array. The difference.
        """

        joined_traj = self.parent.trajectory[self.snapshot_idx].stack(self.traj)
        parent_sasa = shrake_rupley(self.parent.trajectory[self.snapshot_idx])[0]

        joined_sasa = shrake_rupley(joined_traj,change_radii={'VS': 0.17})[0][:len(parent_sasa)]
        return parent_sasa - joined_sasa

    def _get_contact_list(self,binder_traj=None):
        """
        get list of alpha atom contact as bool
        :param binder_traj: object
        :return: np.array
        """
        if binder_traj is None:
            binder_traj = self.oppsite_struct.traj
        contact_matrix  = getContactMatrix(self.traj.xyz[0],binder_traj.xyz[0],
                                        threshold=self.config.contact_threshold / 10)
        self.contact = np.array(np.any(contact_matrix,axis=1))
        return self.contact

    def _get_contact_space(self):
        """
        :return array
        """
        self._get_contact_list(self.oppsite_struct.traj)
        contact_space = self.contact * self.total_score
        return contact_space

    def _slice(self,alpha_indices: list) -> None:
        """
        This updates the alpha atom indexing after removing noncontact ones
        :param alpha_indices: list or set
        :return: None
        """
        if type(alpha_indices) != list:
            alpha_indices = list(alpha_indices)
        alpha_indices.sort()
        self.traj.atom_slice(alpha_indices,inplace=True)
        self.top = self.traj.top

        for pocket_idx,pocket in enumerate(self.pockets):
            pocket.index = pocket_idx
        for atom_idx,atom in enumerate(self.alphas):
            atom.index = atom_idx
        # self.alpha_atom_pocket_index = [atom.residue.index for atom in self.top.atoms]
        # self.alpha_atom_lining = np.take(self.alpha_atom_lining, index_list, axis=0)

        # update array storage
        self.contact = np.take(self.contact,alpha_indices,axis=0)
        self.total_score = np.take(self.total_score,alpha_indices,axis=0)
        self.polar_score = np.take(self.polar_score,alpha_indices,axis=0)
        self.nonpolar_score = np.take(self.nonpolar_score,alpha_indices,axis=0)

    def _get_lining_atoms(self,index_list: list) -> np.array:
        """
        get a set of surface lining atoms in the given cluster of alpha atoms
        :type index_list: alpha atom list
        """
        return np.unique(np.take(self.alpha_lining, index_list).flatten())

    def _get_pocket_lining_atoms(self,pocket):

        return self._get_lining_atoms([atom.index for atom in pocket.alpha_atoms])

    def _get_lining_residues(self,index_list):
        # lining_atom_idx = np.take(self.alpha_atom_lining, index_list).flatten()

        lining_atom = [self.receptor_top.atom(i) for i in self._get_lining_atoms(index_list)]
        lining_residue_idx = [atom.residue.index for atom in lining_atom]

        return np.unique(lining_residue_idx)

    def _get_pocket_lining_residue(self,pocket):
        return self._get_lining_residues([atom.index for atom in pocket.alpha_atoms])

    def _get_cluster_centroid(self,cluster):
        xyz = np.take(self.traj.xyz[0],cluster,axis=0)
        return np.mean(xyz,axis=0)


class AS_DPocket:
    def __init__(self,universe):
        self.universe = universe
        self._pocket_list = []

        self.index = -1

    def __getitem__(self,key):
        return self._pocket_list[key]

    def __contains__(self,pocket):
        return any(p == pocket for p in self._pocket_list)

    def __iter__(self):
        for i in self._pocket_list:
            yield i

    def add(self,pocket):
        """
        add a pocket to this dpocket
        :param pocket: object, AS_Pocket
        :return: bool, if the pocket isn't already in the dpocket list
        """
        if any(p == pocket for p in self._pocket_list):
            return False
        else:
            self._pocket_list.append(pocket)
            return True

    def pop(self,key):
        """
        pop a pocket
        :param key: int
        :return: AS_Pocket
        """
        return self._pocket_list.pop(key)

    def n_pockets(self):
        """
        total number of pockets
        :return: int
        """
        return len(self._pocket_list)

    def get_snapshots(self):
        """
        covered snapshot indices in a set
        :return: set
        """
        return iter(set([pocket.snapshot_idx for pocket in self]))

    def n_snapshot(self):
        """
        total number of covered snapshot
        :return:
        """
        return len(list(self.get_snapshots()))

    def pocket_center_xyz(self):
        """
        get the centroid of the each pockets
        :return: numpy array n_pockets * 3
        """
        return np.array([pocket.get_centroid for pocket in self])

    def alpha_atom_xyz(self):
        """
        get the xyz of each alpha_atoms in each pockets
        :return: np.array N * 3
        """
        return np.concatenate([pocket.xyz for pocket in self],axis=0)


import os
import numpy as np
import rdkit
import rdkit.Chem
import rdkit.Chem as Chem

from kgcnn.data.base import DownloadDataset, MemoryGeometricGraphDataset
from kgcnn.mol.molgraph import MolecularGraphRDKit, OneHotEncoder
from kgcnn.utils.data import load_json_file


class MuleculeNetDataset(DownloadDataset, MemoryGeometricGraphDataset):
    r"""Base class for downloading deepchem molecule datasets. The base class provides properties and methods for
    making graph features from smiles. The graph structure matches the molecular graph. The atomic coordinates
    are generated by a conformer guess. Since this require some computation time, it is only done once and the
    molecular coordinate or mol-blocks stored in a json-file named in :obj:`MuleculeNetDataset.mol_filename`.
    The selection of smiles and whether conformers should be generated is handled by sub-classes.

    """

    mol_filename = "mol.json"

    def __init__(self, reload=False, verbose=1):

        DownloadDataset.__init__(self, reload=reload, verbose=verbose)
        MemoryGeometricGraphDataset.__init__(self, verbose=verbose)

        if self.fits_in_memory:
            self.read_in_memory(verbose=verbose)

    @classmethod
    def _smiles_to_mol_list(cls, smiles: list, add_hydrogen: bool = True, sanitize: bool = True,
                            make_conformers: bool = True, verbose: int = 1):
        """Convert a list of smiles as string into a list of mol-information, namely mol-block as string.

        Args:
            smiles (list): A list of smiles for each molecule in dataset.
            add_hydrogen (bool): Whether to add H after smile translation.
            sanitize (bool): Whether sanitize molecule.
            make_conformers (bool): Trey to generate 3D coordinates
            verbose (int): Print progress or info for processing, where 0 is silent. Default is 1.

        Returns:
            list: A list of mol-block information as sting.
        """
        if len(smiles) == 0:
            print("Error:kgcnn: Can not translate smiles, received empty list for %s." % cls.dataset_name)
        if verbose > 0:
            print("INFO:kcnn: Generating molecules and store %s to disk..." % cls.mol_filename, end='', flush=True)
        molecule_list = []
        for i, sm in enumerate(smiles):
            mg = MolecularGraphRDKit(add_hydrogen=add_hydrogen)
            mg.from_smiles(sm, sanitize=sanitize)
            if make_conformers:
                _ = mg.node_coordinates  # Force to generate 3D coordinates
            molecule_list.append(mg.to_mol_block())
        if verbose > 0:
            print("done")
        return molecule_list

    def read_in_memory(self, has_conformers: bool = True, verbose: int = 1):
        """Load list of molecules from json-file named in :obj:`MuleculeNetDataset.mol_filename` into memory. And
        already extract basic graph information. No further attributes are computed as default.

        Args:
            has_conformers (bool): If molecules have 3D coordinates pre-computed.
            verbose (int): Print progress or info for processing where 0=silent. Default is 1.

        Returns:
            self
        """
        mol_path = os.path.join(self.data_main_dir, self.data_directory, self.mol_filename)
        if not os.path.exists(mol_path):
            raise FileNotFoundError("ERROR:kgcnn: Can not load molecules for dataset %s" % self.dataset_name)

        mols = load_json_file(mol_path)
        atoms = []
        coords = []
        number = []
        edgind = []
        for x in mols:
            mg = MolecularGraphRDKit(add_hydrogen=True).from_mol_block(x, sanitize=True)
            atoms.append(mg.node_symbol)
            if has_conformers:
                coords.append(mg.node_coordinates)
            number.append(mg.node_number)
            edgind.append(mg.edge_indices)
        self.node_symbol = atoms
        self.node_coordinates = coords if has_conformers else None
        self.node_number = number
        self.graph_size = [len(x) for x in atoms]
        self.edge_indices = edgind
        return self

    def set_attributes(self,
                       nodes=None,
                       edges=None,
                       graph=None,
                       encoder_nodes=None,
                       encoder_edges=None,
                       encoder_graph=None,
                       add_hydrogen: bool = False,
                       verbose: int = 1):
        """Set further molecular attributes or features by string identifier. Requires :obj:`MolecularGraphRDKit`.
        Reset edges and nodes with new attributes and edge indices. Default values are features that has been used
        by `Luo et al (2019)<https://doi.org/10.1021/acs.jmedchem.9b00959>`_.

        Args:
            nodes (list): A list of node attributes
            edges (list): A list of edge attributes
            graph (list): A list of graph attributes.
            encoder_nodes (dict): A dictionary of callable encoder where the key matches the attribute.
            encoder_edges (dict): A dictionary of callable encoder where the key matches the attribute.
            encoder_graph (dict): A dictionary of callable encoder where the key matches the attribute.
            add_hydrogen (bool): Whether to remove hydrogen.
            verbose (int): Print progress or info for processing where 0=silent. Default is 1.

        Returns:
            self
        """
        # We have to reload the dataset here to start fresh
        self.read_in_memory(verbose=verbose)

        mol_path = os.path.join(self.data_main_dir, self.data_directory, self.mol_filename)
        if not os.path.exists(mol_path):
            raise FileNotFoundError("ERROR:kgcnn: Can not load molecules for dataset %s" % self.dataset_name)

        if verbose > 0:
            print("INFO:kgcnn: Making attributes...", end='', flush=True)

        mols = load_json_file(mol_path)

        # Choose default values here:
        if nodes is None:
            nodes = ['Symbol', 'TotalDegree', 'FormalCharge', 'NumRadicalElectrons', 'Hybridization',
                     'IsAromatic', 'IsInRing', 'TotalNumHs', 'CIPCode', "ChiralityPossible", "ChiralTag"]
        if edges is None:
            edges = ['BondType', 'IsAromatic', 'IsConjugated', 'IsInRing', "Stereo"]
        if graph is None:
            graph = ['ExactMolWt', 'NumAtoms']
        if encoder_nodes is None:
            encoder_nodes = {
                "Symbol": OneHotEncoder(['B', 'C', 'N', 'O', 'F', 'Si', 'P', 'S', 'Cl', 'As', 'Se', 'Br', 'Te', 'I', 'At']),
                "Hybridization": OneHotEncoder([Chem.rdchem.HybridizationType.SP,
                                                Chem.rdchem.HybridizationType.SP2,
                                                Chem.rdchem.HybridizationType.SP3,
                                                Chem.rdchem.HybridizationType.SP3D,
                                                Chem.rdchem.HybridizationType.SP3D2]),
                "TotalDegree": OneHotEncoder([0, 1, 2, 3, 4, 5], add_others=False),
                "TotalNumHs": OneHotEncoder([0, 1, 2, 3, 4], add_others=False),
                "CIPCode": OneHotEncoder(['R', 'S'], add_others=False)
            }
        if encoder_edges is None:
            encoder_edges = {
                "BondType": OneHotEncoder([Chem.rdchem.BondType.SINGLE,
                                           Chem.rdchem.BondType.DOUBLE,
                                           Chem.rdchem.BondType.TRIPLE,
                                           Chem.rdchem.BondType.AROMATIC], add_others=False),
                "Stereo": OneHotEncoder([Chem.rdchem.BondStereo.STEREONONE,
                                         Chem.rdchem.BondStereo.STEREOANY,
                                         Chem.rdchem.BondStereo.STEREOZ,
                                         Chem.rdchem.BondStereo.STEREOE], add_others=False),
            }
        if encoder_graph is None:
            encoder_graph = {}

        # Reset all attributes
        graph_attributes = []
        node_attributes = []
        edge_attributes = []
        edge_indices = []
        node_coordinates = []
        node_symbol = []
        node_number = []

        for i, sm in enumerate(mols):
            mg = MolecularGraphRDKit(add_hydrogen=add_hydrogen).from_mol_block(sm, sanitize=True)
            node_attributes.append(np.array(mg.node_attributes(nodes, encoder_nodes), dtype="float32"))
            edge_attributes.append(np.array(mg.edge_attributes(edges, encoder_edges)[1], dtype="float32"))
            edge_indices.append(np.array(mg.edge_indices, dtype="int64"))
            graph_attributes.append(np.array(mg.graph_attributes(graph, encoder_graph), dtype="float32"))
            node_symbol.append(mg.node_symbol)
            node_coordinates.append(np.array(mg.node_coordinates, dtype="float32"))
            node_number.append(mg.node_number)

        self.graph_size = [len(x) for x in node_attributes]
        self.graph_attributes = graph_attributes
        self.node_attributes = node_attributes
        self.edge_attributes = edge_attributes
        self.edge_indices = edge_indices
        self.node_coordinates = node_coordinates
        self.node_symbol = node_symbol
        self.node_number = node_number

        if verbose > 0:
            print("done")
            for key, value in encoder_nodes.items():
                print("INFO:kgcnn: OneHotEncoder", key, "found", value.found_values)
            for key, value in encoder_edges.items():
                print("INFO:kgcnn: OneHotEncoder", key, "found", value.found_values)
            for key, value in encoder_graph.items():
                print("INFO:kgcnn: OneHotEncoder", key, "found", value.found_values)

        return self

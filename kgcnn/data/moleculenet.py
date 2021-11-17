import os
import numpy as np
import pandas as pd

from kgcnn.data.base import MemoryGeometricGraphDataset
from kgcnn.utils.data import save_json_file, load_json_file
from kgcnn.mol.molgraph import MolecularGraphRDKit, OneHotEncoder


class MoleculeNetDataset(MemoryGeometricGraphDataset):
    r"""Class for using molecule datasets. The concept is to load a table of smiles and corresponding targets and
    convert them into a tensors representation for graph networks.

    The class provides properties and methods for making graph features from smiles.
    The typical input is a `csv` or `excel` file with smiles and corresponding graph labels.

    The graph structure matches the molecular graph, i.e. the chemical structure. The atomic coordinates
    are generated by a conformer guess. Since this require some computation time, it is only done once and the
    molecular coordinate or mol-blocks stored in a single SDF file with the base-name of the csv :obj:``file_name``.

    The selection of smiles and whether conformers should be generated is handled by sub-classes or specified in the
    the methods :obj:`prepare_data()` and :obj:`read_in_memory()`, see the documentation of the methods
    for further details.
    """

    def __init__(self, data_directory: str = None, dataset_name: str = None, file_name: str = None,
                 verbose=1):
        r"""Initialize a `MoleculeNetDataset` with information on the dataset location on disk.

        Args:
            file_name (str): Filename for reading into memory. This must be the name of the '.csv' file.
                Default is None.
            data_directory (str): Full path to directory containing all dataset files. Default is None.
            dataset_name (str): Name of the dataset. Important for naming. Default is None.
            verbose (int): Print progress or info for processing, where 0 is silent. Default is 1.
        """
        MemoryGeometricGraphDataset.__init__(self, data_directory=data_directory, dataset_name=dataset_name,
                                             file_name=file_name, verbose=verbose)
        self.data_keys = None

    def _smiles_to_mol_list(self, smiles: list, add_hydrogen: bool = True, sanitize: bool = True,
                            make_conformers: bool = True, verbose: int = 1):
        r"""Convert a list of smiles as string into a list of mol-information, namely mol-block as string.

        Args:
            smiles (list): A list of smiles for each molecule in dataset.
            add_hydrogen (bool): Whether to add hydrogen after smile translation.
            sanitize (bool): Whether to sanitize molecule.
            make_conformers (bool): Try to generate 3D coordinates
            verbose (int): Print progress or info for processing, where 0 is silent. Default is 1.

        Returns:
            list: A list of mol-block information as sting.
        """
        self.verbose = verbose
        mol_filename = "".join(self.file_name.split(".")[:-1]) + ".json"
        if len(smiles) == 0:
            print("ERROR:kgcnn: Can not translate smiles, received empty list for %s." % self.dataset_name)

        self._log("INFO:kgcnn: Generating molecules and store %s to disk..." % mol_filename)
        molecule_list = []
        max_number = len(smiles)
        for i, sm in enumerate(smiles):
            mg = MolecularGraphRDKit(add_hydrogen=add_hydrogen, make_conformers=make_conformers)
            mg.from_smiles(sm, sanitize=sanitize)
            molecule_list.append(mg.to_mol_block())
            if i % 1000 == 0:
                self._log(" ... converted molecules {0} from {1}".format(i, max_number))
        self._log("done")
        return molecule_list

    def prepare_data(self, overwrite: bool = False, smiles_column_name: str = "smiles",
                     make_conformers: bool = True, add_hydrogen: bool = True, **kwargs):
        r"""Pre-computation of molecular structure information and optionally conformers.

        Args:
            overwrite (bool): Overwrite existing database mol-json file. Default is False.
            smiles_column_name (str): Column name where smiles are given in csv-file. Default is "smiles".
            make_conformers (bool): Whether to make conformers. Default is True.
            add_hydrogen (bool): Whether to add H after smile translation. Default is True.

        Returns:
            self
        """
        mol_filename = self._get_mol_filename()
        if os.path.exists(os.path.join(self.data_directory, mol_filename)) and not overwrite:
            self._log("INFO:kgcnn: Found rdkit %s of pre-computed structures." % mol_filename)
            return self
        filepath = os.path.join(self.data_directory, self.file_name)
        data = pd.read_csv(filepath)
        # print(data)
        smiles = data[smiles_column_name].values
        # We need to parallelize this.
        mb = self._smiles_to_mol_list(smiles, add_hydrogen=add_hydrogen, sanitize=True,
                                      make_conformers=make_conformers,
                                      verbose=self.verbose)

        save_json_file(mb, os.path.join(self.data_directory, mol_filename))

        return self

    def read_in_memory(self, has_conformers: bool = True, label_column_name: str = None,
                       add_hydrogen: bool = True):
        r"""Load list of molecules from cached json-file in into memory. And
        already extract basic graph information. No further attributes are computed as default.

        Args:
            has_conformers (bool): If molecules need 3D coordinates pre-computed.
            label_column_name (str): Column name in the csv-file where to take graph labels from.
                For multi-targets you can supply a list of column names or positions. Also a slice can be provided
                for selecting columns as graph labels. Default is None.
            add_hydrogen (bool): Whether to keep hydrogen after reading the mol-information. Default is True.

        Returns:
            self
        """
        # Read the data from a csv-file.
        data = pd.read_csv(os.path.join(self.data_directory, self.file_name))

        # Find columns to take graph labels from.
        self.data_keys = data.columns
        if isinstance(label_column_name, str):
            graph_labels_all = np.expand_dims(np.array(data[label_column_name]), axis=-1)
        elif isinstance(label_column_name, list):
            graph_labels_all = []
            for x in label_column_name:
                if isinstance(x, int):
                    x_col = np.array(data.iloc[:, x])
                elif isinstance(x, str):
                    x_col = np.array(data[x])
                else:
                    raise ValueError("ERROR:kgcnn: Column list must contain name or position but got %s" % x)
                if len(x_col.shape) <= 1:
                    x_col = np.expand_dims(x_col, axis=-1)
                graph_labels_all.append(x_col)
            graph_labels_all = np.concatenate(graph_labels_all, axis=-1)
        elif isinstance(label_column_name, slice):
            graph_labels_all = np.array(data.iloc[:, label_column_name])
        else:
            raise ValueError("ERROR:kgcnn: Column label definition must be list or string, got %s" % label_column_name)

        mol_filename = self._get_mol_filename()
        mol_path = os.path.join(self.data_directory, mol_filename)
        if not os.path.exists(mol_path):
            raise FileNotFoundError("ERROR:kgcnn: Can not load molecules for dataset %s" % self.dataset_name)

        self._log("INFO:kgcnn: Read mol-blocks from %s of pre-computed structures..." % mol_filename)
        mols = load_json_file(mol_path)

        # Main loop to read molecules from mol-block
        atoms = []
        coords = []
        number = []
        edgind = []
        edge_number = []
        num_mols = len(mols)
        graph_labels = []
        counter_iter = 0
        for i, x in enumerate(mols):
            mg = MolecularGraphRDKit(add_hydrogen=add_hydrogen).from_mol_block(x, sanitize=True)
            if mg.mol is None:
                self._log(" ... skip molecule {0} as it could not be converted to mol-object".format(i))
                continue
            temp_edge = mg.edge_number
            if len(temp_edge[0]) == 0:
                self._log(" ... skip molecule {0} as it has 0 edges.".format(i))
                continue
            if has_conformers:
                temp_xyz = mg.node_coordinates
                if len(temp_xyz) == 0:
                    self._log(" ... skip molecule {0} as it has no conformer.".format(i))
                    continue
                coords.append(np.array(temp_xyz, dtype="float32"))

            # Append all valid tensor quantities
            edgind.append(temp_edge[0])
            edge_number.append(np.array(temp_edge[1], dtype="int"))
            atoms.append(mg.node_symbol)
            number.append(mg.node_number)
            graph_labels.append(graph_labels_all[i])
            counter_iter += 1
            if i % 1000 == 0:
                self._log(" ... read molecules {0} from {1}".format(i, num_mols))

        self.node_symbol = atoms
        self.node_coordinates = coords if has_conformers else None
        self.node_number = number
        self.graph_size = [len(x) for x in atoms]
        self.edge_indices = edgind
        self.length = counter_iter
        self.graph_labels = graph_labels
        self.edge_number = edge_number

        self._log("done")

        return self

    def set_attributes(self,
                       nodes=None,
                       edges=None,
                       graph=None,
                       encoder_nodes=None,
                       encoder_edges=None,
                       encoder_graph=None,
                       add_hydrogen: bool = False,
                       has_conformers: bool = True,
                       verbose: int = 1):
        r"""Set further molecular attributes or features by string identifier. Requires :obj:`MolecularGraphRDKit`.
        Reset edges and nodes with new attributes and edge indices. Default values are features that has been used
        by `Luo et al (2019) <https://doi.org/10.1021/acs.jmedchem.9b00959>`_.

        Args:
            nodes (list): A list of node attributes
            edges (list): A list of edge attributes
            graph (list): A list of graph attributes.
            encoder_nodes (dict): A dictionary of callable encoder where the key matches the attribute.
            encoder_edges (dict): A dictionary of callable encoder where the key matches the attribute.
            encoder_graph (dict): A dictionary of callable encoder where the key matches the attribute.
            add_hydrogen (bool): Whether to remove hydrogen.
            has_conformers (bool): If molecules needs 3D coordinates pre-computed.
            verbose (int): Print progress or info for processing where 0=silent. Default is 1.

        Returns:
            self
        """
        mol_filename = self._get_mol_filename()
        mol_path = os.path.join(self.data_directory, mol_filename)
        if not os.path.exists(mol_path):
            raise FileNotFoundError("ERROR:kgcnn: Can not load molecules for dataset %s" % self.dataset_name)

        self._log("INFO:kgcnn: Making attributes...")

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
                "Symbol": OneHotEncoder(
                    ['B', 'C', 'N', 'O', 'F', 'Si', 'P', 'S', 'Cl', 'As', 'Se', 'Br', 'Te', 'I', 'At'], dtype="str"),
                "Hybridization": OneHotEncoder([2, 3, 4, 5, 6]),
                "TotalDegree": OneHotEncoder([0, 1, 2, 3, 4, 5], add_unknown=False),
                "TotalNumHs": OneHotEncoder([0, 1, 2, 3, 4], add_unknown=False),
                "CIPCode": OneHotEncoder(['R', 'S'], add_unknown=False, dtype="str")
            }
        if encoder_edges is None:
            encoder_edges = {
                "BondType": OneHotEncoder([1, 2, 3, 12], add_unknown=False),
                "Stereo": OneHotEncoder([0, 1, 2, 3], add_unknown=False),
            }
        if encoder_graph is None:
            encoder_graph = {}

        for key, value in encoder_nodes.items():
            encoder_nodes[key] = self._deserialize_encoder(value)
        for key, value in encoder_edges.items():
            encoder_edges[key] = self._deserialize_encoder(value)
        for key, value in encoder_graph.items():
            encoder_graph[key] = self._deserialize_encoder(value)

        # Reset all attributes
        graph_attributes = []
        node_attributes = []
        edge_attributes = []
        edge_number = []
        edge_indices = []
        node_coordinates = []
        node_symbol = []
        node_number = []
        num_mols = len(mols)
        counter_iter = 0
        for i, sm in enumerate(mols):
            mg = MolecularGraphRDKit(add_hydrogen=add_hydrogen).from_mol_block(sm, sanitize=True)
            if mg.mol is None:
                self._log(" ... skip molecule {0} as it could not be converted to mol-object".format(i))
                continue
            temp_edge = mg.edge_number
            if len(temp_edge[0]) == 0:
                self._log(" ... skip molecule {0} as it has 0 edges.".format(i))
                continue
            if has_conformers:
                temp_xyz = mg.node_coordinates
                if len(temp_xyz) == 0:
                    self._log(" ... skip molecule {0} as it has no conformer as requested.".format(i))
                    continue
                node_coordinates.append(np.array(temp_xyz, dtype="float32"))

            # Append all valid tensor properties
            edge_indices.append(np.array(temp_edge[0], dtype="int64"))
            edge_number.append(np.array(temp_edge[1], dtype="int"))
            node_attributes.append(np.array(mg.node_attributes(nodes, encoder_nodes), dtype="float32"))
            edge_attributes.append(np.array(mg.edge_attributes(edges, encoder_edges)[1], dtype="float32"))
            graph_attributes.append(np.array(mg.graph_attributes(graph, encoder_graph), dtype="float32"))
            node_symbol.append(mg.node_symbol)
            node_number.append(mg.node_number)
            counter_iter += 1
            if i % 1000 == 0:
                self._log(" ... read molecules {0} from {1}".format(i, num_mols))

        self.graph_size = [len(x) for x in node_attributes]
        self.graph_attributes = graph_attributes
        self.node_attributes = node_attributes
        self.edge_attributes = edge_attributes
        self.edge_indices = edge_indices
        self.node_coordinates = node_coordinates
        self.node_symbol = node_symbol
        self.node_number = node_number
        self.length = counter_iter

        if verbose > 0:
            print("done")
            for key, value in encoder_nodes.items():
                if hasattr(value, "found_values"):
                    print("INFO:kgcnn: OneHotEncoder", key, "found", value.found_values)
            for key, value in encoder_edges.items():
                if hasattr(value, "found_values"):
                    print("INFO:kgcnn: OneHotEncoder", key, "found", value.found_values)
            for key, value in encoder_graph.items():
                if hasattr(value, "found_values"):
                    print("INFO:kgcnn: OneHotEncoder", key, "found", value.found_values)

        return self

    @staticmethod
    def _deserialize_encoder(encoder_identifier):
        """Serialization. Will maybe include keras in the future.

        Args:
            encoder_identifier: Identifier, class or function of an encoder.

        Returns:
            obj: Deserialized encoder.
        """
        if isinstance(encoder_identifier, dict):
            if encoder_identifier["class_name"] == "OneHotEncoder":
                return OneHotEncoder.from_config(encoder_identifier["config"])
        elif hasattr(encoder_identifier, "__call__"):
            return encoder_identifier
        else:
            raise ValueError("ERROR:kgcnn: Unable to deserialize encoder %s " % encoder_identifier)

    def _get_mol_filename(self):
        """Try to determine a file name for the mol information to store."""
        return "".join(self.file_name.split(".")[:-1]) + ".json"

    def _flexible_csv_file_name(self):
        pass


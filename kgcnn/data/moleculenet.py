import os
import numpy as np
import pandas as pd

from typing import Dict, Callable, Union
from collections import defaultdict

from kgcnn.data.base import MemoryGraphDataset
from kgcnn.mol.module_rdkit import MolecularGraphRDKit
from kgcnn.mol.encoder import OneHotEncoder
from kgcnn.mol.io import write_mol_block_list_to_sdf, read_mol_list_from_sdf_file
from kgcnn.mol.convert import MolConverter


class MoleculeNetDataset(MemoryGraphDataset):
    r"""Class for using molecule datasets. The concept is to load a table of smiles and corresponding targets and
    convert them into a tensor representation for graph networks.

    The class provides properties and methods for making graph features from smiles.
    The typical input is a `csv` or `excel` file with smiles and corresponding graph labels.

    The graph structure matches the molecular graph, i.e. the chemical structure. The atomic coordinates
    are generated by a conformer guess. Since this require some computation time, it is only done once and the
    molecular coordinate or mol-blocks stored in a single SDF file with the base-name of the csv :obj:``file_name``.
    Conversion is using the :obj:`MolConverter` class.

    The selection of smiles and whether conformers should be generated is handled by subclasses or specified in
    the methods :obj:`prepare_data` and :obj:`read_in_memory`, see the documentation of the methods
    for further details.

    Attribute generation is carried out via the :obj:`MolecularGraphRDKit` class and requires RDKit as backend.
    """

    DEFAULT_NODE_ATTRIBUTES = ['Symbol', 'TotalDegree', 'FormalCharge', 'NumRadicalElectrons', 'Hybridization',
                               'IsAromatic', 'IsInRing', 'TotalNumHs', 'CIPCode', "ChiralityPossible", "ChiralTag"]
    DEFAULT_NODE_ENCODERS = {
        'Symbol': OneHotEncoder(
            ['B', 'C', 'N', 'O', 'F', 'Si', 'P', 'S', 'Cl', 'As', 'Se', 'Br', 'Te', 'I', 'At'],
            dtype="str"
        ),
        'Hybridization': OneHotEncoder([2, 3, 4, 5, 6]),
        'TotalDegree': OneHotEncoder([0, 1, 2, 3, 4, 5], add_unknown=False),
        'TotalNumHs': OneHotEncoder([0, 1, 2, 3, 4], add_unknown=False),
        'CIPCode': OneHotEncoder(['R', 'S'], add_unknown=False, dtype='str'),
        "ChiralityPossible": OneHotEncoder(["1"], add_unknown=False, dtype='str'),
    }
    DEFAULT_EDGE_ATTRIBUTES = ['BondType', 'IsAromatic', 'IsConjugated', 'IsInRing', 'Stereo']
    DEFAULT_EDGE_ENCODERS = {
        'BondType': OneHotEncoder([1, 2, 3, 12], add_unknown=False),
        'Stereo': OneHotEncoder([0, 1, 2, 3], add_unknown=False)
    }
    DEFAULT_GRAPH_ATTRIBUTES = ['ExactMolWt', 'NumAtoms']
    DEFAULT_GRAPH_ENCODERS = {}

    DEFAULT_LOOP_UPDATE_INFO = 1000

    def __init__(self, data_directory: str = None, dataset_name: str = None, file_name: str = None,
                 verbose: int = 10):
        r"""Initialize a :obj:`MoleculeNetDataset` with information of the dataset location on disk.

        Args:
            file_name (str): Filename for reading into memory. This must be the name of the '.csv' file.
                Default is None.
            data_directory (str): Full path to directory containing all dataset files. Default is None.
            dataset_name (str): Name of the dataset. Important for naming. Default is None.
            verbose (int): Logging level. Default is 10.
        """
        MemoryGraphDataset.__init__(self, data_directory=data_directory, dataset_name=dataset_name,
                                    file_name=file_name, verbose=verbose)

    @property
    def file_path_mol(self):
        """Try to determine a file path for the mol information to store."""
        return os.path.splitext(self.file_path)[0] + ".sdf"

    def _smiles_to_mol_list(self, smiles: list, add_hydrogen: bool = True, sanitize: bool = True,
                            make_conformers: bool = True, optimize_conformer: bool = True,
                            external_program: dict = None, num_workers: int = None):
        r"""Convert a list of smiles as string into a list of mol-information, namely mol-block as string.
        Conversion is done via the :obj:`MolConverter` class.

        Args:
            smiles (list): A list of smiles for each molecule in dataset.
            add_hydrogen (bool): Whether to add hydrogen after smile translation.
            sanitize (bool): Whether to sanitize molecule.
            make_conformers (bool): Try to generate 3D coordinates
            optimize_conformer (bool): Whether to optimize conformer via force field.
                Only possible with :obj:`make_conformers`. Default is True.
            external_program (dict): External program for translating smiles. Default is None.
                If you want to use an external program you have to supply a dictionary of the form:
                {"class_name": "balloon", "config": {"balloon_executable_path": ..., ...}}.
                Note that usually the parameters like :obj:`add_hydrogen` are ignored. And you need to control the
                SDF file generation within `config` of the :obj:`external_program`.
            num_workers (int): Parallel execution for translating smiles.

        Returns:
            list: A list of mol-block information as sting.
        """
        if len(smiles) == 0:
            self.error("Can not translate smiles, received empty list for %s." % self.dataset_name)

        self.info("Generating molecules and store %s to disk..." % self.file_path_mol)
        molecule_list = []
        conv = MolConverter(base_path=self.data_directory,
                            add_hydrogen=add_hydrogen, sanitize=sanitize,
                            make_conformers=make_conformers, optimize_conformer=optimize_conformer,
                            external_program=external_program, num_workers=num_workers)
        for i in range(0, len(smiles), self.DEFAULT_LOOP_UPDATE_INFO):
            mg = conv.smile_to_mol(smiles[i:i + self.DEFAULT_LOOP_UPDATE_INFO])
            molecule_list = molecule_list + mg
            self.info(" ... converted molecules {0} from {1}".format(i + len(mg), len(smiles)))

        return molecule_list

    def prepare_data(self, overwrite: bool = False, smiles_column_name: str = "smiles",
                     add_hydrogen: bool = True, sanitize: bool = True,
                     make_conformers: bool = True, optimize_conformer: bool = True,
                     external_program: dict = None, num_workers: int = None):
        r"""Pre-computation of molecular structure information and optionally conformers. This function reads smiles
        from the csv-file given by :obj:`file_name` and creates a single SDF File of generated mol-blocks with the same
        file name. The function requires :obj:`RDKit` and (optionally) :obj:`OpenBabel`.
        Smiles that are not compatible with both RDKit and OpenBabel result in an empty mol-block in the SDF file to
        keep the number of molecules the same.

        Args:
            overwrite (bool): Overwrite existing database mol-json file. Default is False.
            smiles_column_name (str): Column name where smiles are given in csv-file. Default is "smiles".
            add_hydrogen (bool): Whether to add H after smile translation. Default is True.
            sanitize (bool): Whether to sanitize molecule.
            make_conformers (bool): Whether to make conformers. Default is True.
            optimize_conformer (bool): Whether to optimize conformer via force field.
                Only possible with :obj:`make_conformers`. Default is True.
            external_program (dict): External program for translating smiles. Default is None.
                If you want to use an external program you have to supply a dictionary of the form:
                {"class_name": "balloon", "config": {"balloon_executable_path": ..., ...}}.
                Note that usually the parameters like :obj:`add_hydrogen` are ignored. And you need to control the
                SDF file generation within `config` of the :obj:`external_program`.
            num_workers (int): Parallel execution for translating smiles.

        Returns:
            self
        """
        if os.path.exists(self.file_path_mol) and not overwrite:
            self.info("Found SDF %s of pre-computed structures." % self.file_path_mol)
            return self

        self.read_in_table_file()
        smiles = self.data_frame[smiles_column_name].values

        mb = self._smiles_to_mol_list(smiles,
                                      add_hydrogen=add_hydrogen, sanitize=sanitize,
                                      make_conformers=make_conformers, optimize_conformer=optimize_conformer,
                                      external_program=external_program, num_workers=num_workers)

        write_mol_block_list_to_sdf(mb, self.file_path_mol)
        return self

    def _map_molecule_callbacks(self,
                                callbacks: Dict[str, Callable[[MolecularGraphRDKit, pd.Series], None]],
                                custom_transform: Callable[[MolecularGraphRDKit], MolecularGraphRDKit] = None,
                                add_hydrogen: bool = False,
                                make_directed: bool = False
                                ):
        r"""This method loads the list of molecules from the SDF file, as well as the data of the original CSV file.
        It then iterates over all the molecules / CSV rows and invokes the callbacks for each.

        The "callbacks" parameter is supposed to be a dictionary whose keys are string names of attributes which are
        supposed to be derived from the molecule / csv data and the values are function objects which define how to
        derive that data. Those callback functions get passed two parameters:

            - mg: The :obj:`MolecularGraphRDKit` instance for the current molecule
            - ds: A pandas data series that match data in the CSV file for the specific molecule.

        The string keys of the "callbacks" directory are also the string names which are later used to assign the
        properties of the underlying :obj:`GraphList`. This means that each element of the dataset will then have a
        field with the same name.

        .. note::

            If a molecule cannot be properly loaded by :obj:`MolecularGraphRDKit`, then for all attributes
            "None" is added without invoking the callback!

        Before calling this function, the ".sdf" molecule data file needs to exist, which means it is important to
        have called the "prepare_data" method before, or add a suitable SDF file manually.

        Example:

        .. code-block:: python

            mol_net = MoleculeNetDataset()
            mol_net.prepare_data()

            mol_net._map_molecule_callbacks(callbacks={
                'graph_size': lambda mg, dd: len(mg.node_number),
                'index': lambda mg, dd: dd['index']
            })

            mol: dict = mol_net[0]
            assert 'graph_size' in mol.keys()
            assert 'index' in mol.keys()


        Args:
            callbacks (dict): Dictionary of callbacks to perform on MolecularGraph object and table entries.
            add_hydrogen (bool): Whether to add hydrogen when making a :obj:`MolecularGraphRDKit` instance.
            custom_transform (Callable): Custom transformation function to modify the generated
                :obj:`MolecularGraphRDKit` before callbacks are carried out. The function must take a single
                :obj:`MolecularGraphRDKit` instance as argument and return a (new) :obj:`MolecularGraphRDKit` instance.

        Returns:
            self.
        """
        if not os.path.exists(self.file_path_mol):
            raise FileNotFoundError("Can not load molecules for dataset %s" % self.dataset_name)

        # Loading the molecules and the csv data
        mols = read_mol_list_from_sdf_file(self.file_path_mol)
        data = pd.read_csv(os.path.join(self.data_directory, self.file_name))

        # Dictionaries values are lists, one for each attribute defines in "callbacks" and each value in those
        # lists corresponds to one molecule in the dataset.
        value_lists = defaultdict(list)
        for index, sm in enumerate(mols):
            mg = MolecularGraphRDKit(make_directed=make_directed).from_mol_block(
                sm, keep_hs=add_hydrogen)

            if custom_transform is not None:
                mg = custom_transform(mg)

            for name, callback in callbacks.items():
                if mg.mol is None:
                    value_lists[name].append(None)
                else:
                    data_dict = data.loc[index]
                    value = callback(mg, data_dict)
                    value_lists[name].append(value)
            if index % self.DEFAULT_LOOP_UPDATE_INFO == 0:
                self.info(" ... read molecules {0} from {1}".format(index, len(mols)))

        # The string key names of the original "callbacks" dict are also used as the names of the properties which are
        # assigned
        for name, values in value_lists.items():
            self.assign_property(name, values)

        return self

    def read_in_memory(self, label_column_name: Union[str, list] = None,
                       add_hydrogen: bool = True,
                       make_directed: bool = False,
                       has_conformers: bool = True,
                       custom_transform: Callable[[MolecularGraphRDKit], MolecularGraphRDKit] = None):
        """Load list of molecules from cached SDF-file in into memory. File name must be given in :obj:`file_name` and
        path information in the constructor of this class. Extract basic graph information from mol-blocks.
        No further attributes are computed as default. Use :obj:`set_attributes` for this purpose.
        It further checks the csv-file for graph labels specified by :obj:`label_column_name`.
        Labels that do not have valid smiles or molecule in the SDF-file are also skipped, but added as `None` to
        keep the index and the molecule assignment.

        Args:
            label_column_name (str): Column name in the csv-file where to take graph labels from.
                For multi-targets you can supply a list of column names or positions. A slice can be provided
                for selecting columns as graph labels. Default is None.
            add_hydrogen (bool): Whether to keep hydrogen after reading the mol-information. Default is True.
            has_conformers (bool): Whether to add node coordinates from conformer. Default is True.
            make_directed (bool): Whether to have directed or undirected bonds. Default is False.
            custom_transform (Callable): Custom transformation function to modify the generated
                :obj:`MolecularGraphRDKit` before callbacks are carried out. The function must take a single
                :obj:`MolecularGraphRDKit` instance as argument and return a (new) :obj:`MolecularGraphRDKit` instance.

        Returns:
            self
        """
        callbacks = {
            'node_symbol': lambda mg, ds: mg.node_symbol,
            'node_number': lambda mg, ds: mg.node_number,
            'edge_indices': lambda mg, ds: mg.edge_number[0],
            'edge_number': lambda mg, ds: np.array(mg.edge_number[1], dtype='int'),
            'graph_labels': lambda mg, ds: ds[label_column_name],
            'graph_size': lambda mg, ds: len(mg.node_number)
        }
        if has_conformers:
            callbacks.update({'node_coordinates': lambda mg, ds: mg.node_coordinates})

        self._map_molecule_callbacks(callbacks, add_hydrogen=add_hydrogen, custom_transform=custom_transform,
                                     make_directed=make_directed)

        return self

    def set_attributes(self, nodes: list = None,
                       edges: list = None,
                       graph: list = None,
                       encoder_nodes: dict = None,
                       encoder_edges: dict = None,
                       encoder_graph: dict = None,
                       add_hydrogen: bool = False,
                       make_directed: bool = False,
                       has_conformers: bool = True,
                       additional_callbacks: Dict[str, Callable[[MolecularGraphRDKit, dict], None]] = None,
                       custom_transform: Callable[[MolecularGraphRDKit], MolecularGraphRDKit] = None
                       ):
        """Set further molecular attributes or features by string identifier. Requires :obj:`MolecularGraphRDKit`.
        Reset edges and nodes with new attributes and edge indices. Default values are features that has been used
        by `Luo et al (2019) <https://doi.org/10.1021/acs.jmedchem.9b00959>`_.

        The argument :obj:`additional_callbacks` allows adding custom properties to each element of the dataset. It is
        a dictionary whose string keys are the names of the properties and the values are callable function objects
        which define how the property is derived from either the :obj:`MolecularGraphRDKit` or the corresponding
        row of the original CSV file. Those callback functions accept two parameters:

            * mg: The :obj:`MolecularGraphRDKit` instance of the molecule
            * ds: A pandas data series that match data in the CSV file for the specific molecule.

        Example:

        .. code-block:: python

            csv = "index,name,label,smiles\n1,Propanolol,1,[Cl].CC(C)NCC(O)COc1cccc2ccccc12"
            with open('/tmp/moleculenet_example.csv', mode='w') as file:
                file.write(csv)

            dataset = MoleculeNetDataset('/tmp', 'example', 'moleculenet_example.csv')
            dataset.prepare_data(smiles_column_name='smiles')
            dataset.read_in_memory(label_column_name='label')
            dataset.set_attributes(
                nodes=['Symbol'],
                encoder_nodes={'Symbol': OneHotEncoder(['C', 'O'], dtype='str'),
                edges=['BondType'],
                encoder_edges={'BondType': int},
                additional_callbacks: {
                    # It is important that the callbacks return a numpy array, even if it is just a single element.
                    'name': lambda mg, ds: np.array(ds['name'], dtype='str')
                }
            )

            mol: dict = dataset[0]
            mol['node_attributes']  # np array of one hot encoded atom type per node
            mol['edge_attributes']  # int value representing the bond type
            mol['name']  # Array of a single string which is the name from the original CSV data


        Args:
            nodes (list): A list of node attributes as string. In place of names also functions can be added.
            edges (list): A list of edge attributes as string. In place of names also functions can be added.
            graph (list): A list of graph attributes as string. In place of names also functions can be added.
            encoder_nodes (dict): A dictionary of callable encoder where the key matches the attribute.
            encoder_edges (dict): A dictionary of callable encoder where the key matches the attribute.
            encoder_graph (dict): A dictionary of callable encoder where the key matches the attribute.
            add_hydrogen (bool): Whether to remove hydrogen.
            make_directed (bool): Whether to have directed or undirected bonds. Default is False
            has_conformers (bool): Whether to add node coordinates from conformer. Default is True.
            additional_callbacks (dict): A dictionary whose keys are string attribute names which the elements of the
                dataset are supposed to have and the elements are callback function objects which implement how those
                attributes are derived from the :obj:`MolecularGraphRDKit` of the molecule in question or the
                row of the CSV file.
            custom_transform (Callable): Custom transformation function to modify the generated
                :obj:`MolecularGraphRDKit` before callbacks are carried out. The function must take a single
                :obj:`MolecularGraphRDKit` instance as argument and return a (new) :obj:`MolecularGraphRDKit` instance.

        Returns:
            self
        """
        # May put this in a decorator with a copy or just leave as default arguments.
        # If e.g. nodes is not modified there is no problem with having mutable defaults.
        nodes = nodes if nodes is not None else self.DEFAULT_NODE_ATTRIBUTES
        edges = edges if edges is not None else self.DEFAULT_EDGE_ATTRIBUTES
        graph = graph if graph is not None else self.DEFAULT_GRAPH_ATTRIBUTES
        encoder_nodes = encoder_nodes if encoder_nodes is not None else self.DEFAULT_NODE_ENCODERS
        encoder_edges = encoder_edges if encoder_edges is not None else self.DEFAULT_EDGE_ENCODERS
        encoder_graph = encoder_graph if encoder_graph is not None else self.DEFAULT_GRAPH_ENCODERS
        additional_callbacks = additional_callbacks if additional_callbacks is not None else {}

        # Deserializing encoders
        for encoder in [encoder_nodes, encoder_edges, encoder_graph]:
            for key, value in encoder.items():
                encoder[key] = self._deserialize_encoder(value)

        callbacks = {
            'node_symbol': lambda mg, ds: mg.node_symbol,
            'node_number': lambda mg, ds: mg.node_number,
            'node_attributes': lambda mg, ds: np.array(mg.node_attributes(nodes, encoder_nodes), dtype='float32'),
            'edge_indices': lambda mg, ds: mg.edge_number[0],
            'edge_number': lambda mg, ds: np.array(mg.edge_number[1], dtype='int'),
            'edge_attributes': lambda mg, ds: np.array(mg.edge_attributes(edges, encoder_edges)[1], dtype='float32'),
            'graph_size': lambda mg, ds: len(mg.node_number),
            'graph_attributes': lambda mg, ds: np.array(mg.graph_attributes(graph, encoder_graph), dtype='float32'),
        }
        if has_conformers:
            callbacks.update({'node_coordinates': lambda mg, ds: mg.node_coordinates})
        callbacks.update(additional_callbacks)

        self._map_molecule_callbacks(callbacks, add_hydrogen=add_hydrogen, custom_transform=custom_transform,
                                     make_directed=make_directed)

        if self.logger.getEffectiveLevel() < 20:
            for encoder in [encoder_nodes, encoder_edges, encoder_graph]:
                for key, value in encoder.items():
                    if hasattr(value, "report"):
                        value.report(name=key)
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
            raise ValueError("Unable to deserialize encoder %s " % encoder_identifier)

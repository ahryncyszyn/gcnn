import logging
import numpy as np
import tensorflow as tf
import pandas as pd
import os

from kgcnn.utils.adj import get_angle_indices, coordinates_to_distancematrix, invert_distance, \
    define_adjacency_from_distance, sort_edge_indices, get_angle, add_edges_reverse_indices, \
    rescale_edge_weights_degree_sym, add_self_loops_to_edge_indices, compute_reverse_edges_index_map
from kgcnn.utils.data import save_pickle_file, load_pickle_file, ragged_tensor_from_nested_numpy

# Module logger
logging.basicConfig()
module_logger = logging.getLogger(__name__)
module_logger.setLevel(logging.INFO)


class NumpyContainer:
    r"""Container to store named numpy arrays in a dictionary.
    The naming convention is not restricted. The class is supposed to be handled just as a python dictionary.
    When assigning items, they are cast into a numpy array.


    """

    def __init__(self, graph: dict = None):
        # Data for graph list.
        self._dict = {}
        if graph is None:
            self._dict = {}
        if isinstance(graph, (dict, list)):
            in_dict = dict(graph)
            self._dict = {key: np.array(value) for key, value in in_dict.items()}
        if isinstance(graph, NumpyContainer):
            self._dict = {key: np.array(value) for key, value in graph._dict.items()}

    def assign_property(self, key, value):
        if value is not None:
            self._dict.update({key: np.array(value)})

    def obtain_property(self, key):
        if key in self._dict:
            return self._dict[key]

    def __getitem__(self, item):
        return self._dict[item]

    def __setitem__(self, item, value):
        self._dict[item] = np.array(value)

    def __str__(self):
        return str(self._dict)

    def __repr__(self):
        return "GraphNumpyContainer(" + str(self._dict) + ")"


class GraphNumpyContainer(NumpyContainer):
    r"""Extends :obj:`NumpyContainer` with

    """

    def __init__(self, **kwargs):
        super(GraphNumpyContainer, self).__init__(**kwargs)

    def _find_graph_properties(self, prop_prefix):
        return [x for x in self._dict if prop_prefix == x[:len(prop_prefix)]]

    def _operate_on_edges(self, operation, prefix_attributes: str = "edge_", **kwargs):
        r"""Wrapper to run a certain function on all edge related properties. The indices attributes must be defined
        and must be composed of :obj:`prefix_attributes` and 'indices'.

        Args:
              operation (callable): Function to apply to a list of all edge arrays.
                First entry is assured to be indices.
              prefix_attributes (str): Prefix for attributes to identify as edges.
              kwargs: Kwargs for operation function call.
        """
        if prefix_attributes + "indices" not in self._dict or self._dict[prefix_attributes + "indices"] is None:
            raise ValueError("Can not operate on %s, as indices are not defined." % prefix_attributes)
        # Determine all linked edge attributes, that are not None.
        edge_linked = self._find_graph_properties(prefix_attributes)
        # Edge indices is always at first position!
        edge_linked = [prefix_attributes + "indices"] + [x for x in edge_linked if x != prefix_attributes + "indices"]
        no_nan_edge_prop = [x for x in edge_linked if self._dict[x] is not None]
        non_nan_edge = [self._dict[x] for x in no_nan_edge_prop]
        new_edges = operation(*non_nan_edge, **kwargs)
        # If dataset only has edge indices, fun_operation is expected to only return array not list!
        # This restricts the type of fun_operation used with this method.
        if len(no_nan_edge_prop) == 1:
            new_edges = [new_edges]
        # Set all new edge attributes.
        for i, at in enumerate(no_nan_edge_prop):
            self._dict[at] = new_edges[i]
        return self

    def set_edge_indices_reverse(self, prefix_attributes: str = "edge_"):
        r"""Computes the index map of the reverse edge for each of the edges if available. This can be used by a model
        to directly select the corresponding edge of :math:`(j, i)` which is :math:`(i, j)`.
        Does not affect other edge-properties, only creates a map on edge indices. Edges that do not have a reverse
        pair get a `nan` as map index. If there are multiple edges, the first encounter is assigned.

        .. warning::
            Reverse maps are not recomputed if you use e.g. :obj:`sort_edge_indices` or redefine edges.

        Args:
            prefix_attributes (str): Prefix for attributes to identify as edges.

        Returns:
            self
        """
        if prefix_attributes + "indices" not in self._dict or self._dict[prefix_attributes + "indices"] is None:
            raise ValueError("Can not operate on %s, as indices are not defined." % prefix_attributes)
        self._dict[prefix_attributes + "indices_reverse"] = np.expand_dims(
            compute_reverse_edges_index_map(self._dict[prefix_attributes + "indices"]), axis=-1)
        return self

    def make_undirected_edges(self, prefix_attributes="edge_", remove_duplicates: bool = True,
                              sort_indices: bool = True):
        r"""Add edges :math:`(j, i)` for :math:`(i, j)` if there is no edge :math:`(j, i)`.
        With :obj:`remove_duplicates` an edge can be added even though there is already and edge at :math:`(j, i)`.
        For other edge tensors, like the attributes or labels, the values of edge :math:`(i, j)` is added in place.
        Requires that :obj:`edge_indices` property is assigned.

        Args:
            prefix_attributes (str): Prefix for attributes to identify as edges.
            remove_duplicates (bool): Whether to remove duplicates within the new edges. Default is True.
            sort_indices (bool): Sort indices after adding edges. Default is True.

        Returns:
            self
        """
        self._operate_on_edges(add_edges_reverse_indices, prefix_attributes=prefix_attributes,
                               remove_duplicates=remove_duplicates, sort_indices=sort_indices)
        return self

    def add_edge_self_loops(self, prefix_attributes="edge_", remove_duplicates: bool = True, sort_indices: bool = True,
                            fill_value: int = 0):
        r"""Add self loops to the each graph property. The function expects the property :obj:`edge_indices`
        to be defined. By default the edges are also sorted after adding the self-loops.
        All other edge properties are filled with :obj:`fill_value`.

        Args:
            prefix_attributes (str): Prefix for attributes to identify as edges.
            remove_duplicates (bool): Whether to remove duplicates. Default is True.
            sort_indices (bool): To sort indices after adding self-loops. Default is True.
            fill_value (in): The fill_value for all other edge properties.

        Returns:
            self
        """
        self._operate_on_edges(add_self_loops_to_edge_indices, prefix_attributes=prefix_attributes,
                               remove_duplicates=remove_duplicates, sort_indices=sort_indices, fill_value=fill_value)
        return self

    def sort_edge_indices(self, prefix_attributes="edge_"):
        r"""Sort edge indices and all edge-related properties. The index list is sorted for the first entry.

        Args:
            prefix_attributes (str): Prefix for attributes to identify as edges.

        Returns:
            self
        """
        self._operate_on_edges(sort_edge_indices, prefix_attributes=prefix_attributes)
        return self

    def normalize_edge_weights_sym(self, prefix_attributes="edge_"):
        r"""Normalize :obj:`edge_weights` using the node degree of each row or column of the adjacency matrix.
        Normalize edge weights as :math:`\tilde{e}_{i,j} = d_{i,i}^{-0.5} \, e_{i,j} \, d_{j,j}^{-0.5}`.
        The node degree is defined as :math:`D_{i,i} = \sum_{j} A_{i, j}`. Requires the property :obj:`edge_indices`.
        Does not affect other edge-properties and only sets :obj:`edge_weights`.

        Args:
            prefix_attributes (str): Prefix for attributes to identify as edges.

        Returns:
            self
        """
        if prefix_attributes + "indices" not in self._dict or self._dict[prefix_attributes + "indices"] is None:
            raise ValueError("Can not operate on %s, as indices are not defined." % prefix_attributes)
        if prefix_attributes + "weights" not in self._dict or self.obtain_property(prefix_attributes + "weights") is None:
            self._dict[prefix_attributes + "weights"] = np.ones((len(self.obtain_property(prefix_attributes + "indices")), 1))
        self._dict[prefix_attributes + "weights"] = rescale_edge_weights_degree_sym(
            self._dict[prefix_attributes + "indices"], self._dict[prefix_attributes + "weights"])
        return self

    def set_range_from_edges(self, prefix_attributes="edge_", do_invert_distance: bool = False):
        r"""Assigns range indices and attributes (distance) from the definition of edge indices. This operations
        requires the attributes :obj:`node_coordinates` and :obj:`edge_indices` to be set. That also means that
        :obj:`range_indices` will be equal to :obj:`edge_indices`.

        Args:
            prefix_attributes (str): Prefix for attributes to identify as edges.
            do_invert_distance (bool): Invert distance when computing  :obj:`range_attributes`. Default is False.

        Returns:
            self
        """
        if prefix_attributes + "indices" not in self._dict or self._dict[prefix_attributes + "indices"] is None:
            raise ValueError("Can not operate on %s, as indices are not defined." % prefix_attributes)
        self._dict["range_indices"] = self._dict["edge_indices"]  # We make a copy.

        if "node_coordinates" not in self._dict or self._dict["node_coordinates"] is None:
            print("Coordinates are not set in `GraphNumpyContainer`. Can not make graph.")
            return self
        xyz = self._dict["node_coordinates"]
        idx = self._dict["range_indices"]
        dist = np.sqrt(np.sum(np.square(xyz[idx[:, 0]] - xyz[idx[:, 1]]), axis=-1, keepdims=True))
        if do_invert_distance:
            dist = invert_distance(dist)
        self._dict["range_attributes"] = dist
        return self

    def set_range(self, max_distance: float = 4.0, max_neighbours: int = 15,
                  do_invert_distance: bool = False, self_loops: bool = False, exclusive: bool = True):
        r"""Define range in euclidean space for interaction or edge-like connections. The number of connection is
        determines based on a cutoff radius and a maximum number of neighbours or both.
        Requires :obj:`node_coordinates` and :obj:`edge_indices` to be set.
        The distance is stored in :obj:`range_attributes`.

        Args:
            max_distance (float): Maximum distance or cutoff radius for connections. Default is 4.0.
            max_neighbours (int): Maximum number of allowed neighbours for a node. Default is 15.
            do_invert_distance (bool): Whether to invert the the distance. Default is False.
            self_loops (bool): If also self-interactions with distance 0 should be considered. Default is False.
            exclusive (bool): Whether both max_neighbours and max_distance must be fulfilled. Default is True.

        Returns:
            self
        """
        if "node_coordinates" not in self._dict or self._dict["node_coordinates"] is None:
            print("Coordinates are not set in `GraphNumpyContainer`. Can not make graph.")
            return self
        # Compute distance matrix here. May be problematic for too large graphs.
        dist = coordinates_to_distancematrix(self._dict["node_coordinates"])
        cons, indices = define_adjacency_from_distance(dist, max_distance=max_distance,
                                                       max_neighbours=max_neighbours,
                                                       exclusive=exclusive, self_loops=self_loops)
        mask = np.array(cons, dtype="bool")
        dist_masked = dist[mask]
        if do_invert_distance:
            dist_masked = invert_distance(dist_masked)
        # Need one feature dimension.
        if len(dist_masked.shape) <= 1:
            dist_masked = np.expand_dims(dist_masked, axis=-1)
        # Assign attributes to instance.
        self._dict["range_attributes"] = dist_masked
        self._dict["range_indices"] = indices
        return self

    def set_angle(self, prefix_indices: str = "range_", allow_multi_edges: bool = False, compute_angles: bool = True):
        r"""Find possible angles between geometric range connections defined by :obj:`range_indices`.
        Which edges form angles is stored in :obj:`angle_indices`.
        One can also change :obj:`prefix_indices` to `edge` to compute angles between edges instead
        of range connections.

        .. warning::
            Angles are not recomputed if you use :obj:`set_range` or redefine edges.

        Args:
            prefix_indices (str): Prefix for edge-like attributes to pick indices from. Default is `range`.
            allow_multi_edges (bool): Whether to allow angles between 'i<-j<-i', which gives 0 degree angle, if they
                the nodes are unique. Default is False.
            compute_angles (bool): Whether to also compute angles

        Returns:
            self
        """
        if prefix_indices + "indices" not in self._dict or self._dict[prefix_indices + "indices"] is None:
            raise ValueError("Can not operate on %s, as indices are not defined." % prefix_indices)
        # Compute angles
        _, a_triples, a_indices = get_angle_indices(self._dict[prefix_indices+"indices"],
                                                    allow_multi_edges=allow_multi_edges)
        self._dict["angle_indices"] = a_indices
        self._dict["angle_indices_nodes"] = a_triples
        # Also compute angles
        if compute_angles:
            if "node_coordinates" not in self._dict or self._dict["node_coordinates"] is None:
                print("Coordinates are not set in `GraphNumpyContainer`. Can not make graph.")
                return self
            self._dict["angle_attributes"] = get_angle(self._dict["node_coordinates"], a_triples)
        return self


class MemoryGraphList:
    r"""Class to store a list of graphs containers in memory. Simply wraps a python list.
    The graph properties are defined by tensor-like numpy arrays for indices, attributes, labels, symbol etc. .
    They are added in form of a list of numpy arrays to the instance of this class.
    Graph related properties must have a special prefix to be noted as graph property and passed to
    the :obj:`GraphNumpyContainer` directly, which is generated for each item of this list.
    Prefix are `node_`, `edge_` and `graph_` for their node, edge and graph properties, respectively.
    The range-attributes and range-indices are just like edge-indices but refer to a geometric annotation. This allows
    to have geometric range-connections and topological edges separately. The label 'range' is synonym for a geometric
    edge. They are characterized by the prefix `range_` and `angle_` and are also
    checked for length when assigning attributes to the instances of this class.

    .. code-block:: python

        from kgcnn.data.base import MemoryGraphList
        data = MemoryGraphList()
        data.edge_indices = [np.array([[0, 1], [1, 0]])]
        data.node_labels = [np.array([[0], [1]])]
        print(data.edge_indices, data.node_labels)
        data.node_coordinates = [np.array([[1, 0, 0], [0, 1, 0], [0, 2, 0], [0, 3, 0]])]
        print(data.node_coordinates)
        data.map_list("set_range", max_distance=1.5, max_neighbours=10, self_loops=False)
        print(data.range_indices, data.range_attributes)

    Functions to modify graph properties are accessed with this class,
    like for example :obj:`sort_edge_indices`. Please find functions in
    :class:`GraphNumpyContainer` and their documentation for further details.
    """

    def __init__(self):
        r"""Initialize an empty :obj:`MemoryGraphList` instance. If you want to expand the list or
        namespace of accepted reserved graph prefix identifier, you can expand :obj:`_reserved_graph_property_prefix`.

        """
        self._list = []
        self._reserved_graph_property_prefix = ["node_", "edge_", "graph_", "range_", "angle_"]
        self.logger = module_logger

    def assign_property(self, key, value):
        if value is None:
            # We could also here remove the key from all graphs.
            return self
        if not isinstance(value, list):
            raise TypeError("Expected type 'list' to assign graph properties.")
        if len(self._list) == 0:
            self.empty(len(value))
        if len(self._list) != len(value):
            raise ValueError("Can only store graph attributes from list with same length.")
        for i, x in enumerate(value):
            self._list[i].assign_property(key, x)
        return self

    def obtain_property(self, key):
        prop_list = [x.obtain_property(key) for x in self._list]
        if all([x is None for x in prop_list]):
            self.logger.warning("Property %s is not set on any graph." % key)
            return None
        return prop_list

    def __setattr__(self, key, value):
        """Setter that intercepts reserved attributes and stores them in the list of graph containers."""
        if not hasattr(self, "_reserved_graph_property_prefix") or not hasattr(self, "_list"):
            return super(MemoryGraphList, self).__setattr__(key, value)
        if any([x == key[:len(x)] for x in self._reserved_graph_property_prefix]):
            self.assign_property(key, value)
        else:
            return super(MemoryGraphList, self).__setattr__(key, value)

    def __getattribute__(self, key):
        """Getter that retrieves a list of properties from graph containers."""
        if key in ["_reserved_graph_property_prefix", "_list"]:
            return super(MemoryGraphList, self).__getattribute__(key)
        if any([x == key[:len(x)] for x in self._reserved_graph_property_prefix]):
            return self.obtain_property(key)
        else:
            return super().__getattribute__(key)

    def __len__(self):
        """Return the current length of this instance."""
        return len(self._list)

    def __getitem__(self, item):
        # Does not make a copy of the data, as a python list does.
        if isinstance(item, int):
            return self._list[item]
        new_list = MemoryGraphList()
        if isinstance(item, slice):
            return new_list._set_internal_list(self._list[item])
        if isinstance(item, list):
            return new_list._set_internal_list([self._list[int(i)] for i in item])
        if isinstance(item, np.ndarray):
            return new_list._set_internal_list([self._list[int(i)] for i in item])
        raise TypeError("Unsupported type for MemoryGraphList items.")

    def _set_internal_list(self, value: list):
        if not isinstance(value, list):
            raise TypeError("Must set list for MemoryGraphList.")
        self._list = value
        return self

    def __setitem__(self, key, value):
        if not isinstance(value, GraphNumpyContainer):
            raise TypeError("Require a GraphNumpyContainer as list item.")
        self._list[key] = value

    def clear(self):
        self._list = []

    def empty(self, length: int):
        if length is None:
            return self
        if length < 0:
            raise ValueError("Length of empty list must be >=0.")
        self._list = [GraphNumpyContainer() for _ in range(length)]
        return self

    @property
    def length(self):
        return len(self._list)

    @length.setter
    def length(self, value: int):
        raise ValueError("Can not set length. Please use 'empty()' to initialize an empty list.")

    def _to_tensor(self, item, make_copy=True):
        if not make_copy:
            self.logger.warning("At the moment always a copy is made for tensor().")
        props = self.obtain_property(item["name"])  # Will be list.
        is_ragged = item["ragged"] if "ragged" in item else False
        if is_ragged:
            return ragged_tensor_from_nested_numpy(props)
        else:
            return tf.constant(np.array(props))

    def tensor(self, items, make_copy=True):
        if isinstance(items, dict):
            return self._to_tensor(items, make_copy=make_copy)
        elif isinstance(items, (tuple, list)):
            return [self._to_tensor(x, make_copy=make_copy) for x in items]
        else:
            raise TypeError("Wrong type, expected e.g. [{'name': 'edge_indices', 'ragged': True}, {...}, ...]")

    def map_list(self, fun, **kwargs):
        for x in self._list:
            getattr(x, fun)(**kwargs)
        return self

    def clean(self, inputs: list):
        invalid_graphs = []
        for item in inputs:
            if isinstance(item, dict):
                item_name = item["name"]
            else:
                item_name = item
            props = self.obtain_property(item_name)
            if props is None:
                self.logger.warning("Can not clean property %s as it was not assigned to any graph." % item)
                continue
            for i, x in enumerate(props):
                if x is None or not hasattr(x, "__getitem__"):
                    self.logger.info("Property %s is not defined for graph %s." % (item_name, i))
                    invalid_graphs.append(i)
                elif len(x) <= 0:
                    self.logger.info("Property %s is with zero length for graph %s." % (item_name, i))
                    invalid_graphs.append(i)
        invalid_graphs = np.unique(np.array(invalid_graphs, dtype="int"))
        invalid_graphs = np.flip(invalid_graphs)  # Need descending order
        self.logger.warning("Found invalid graphs for properties. Removing graphs %s." % invalid_graphs)
        for i in invalid_graphs:
            self._list.pop(int(i))
        return self


class MemoryGraphDataset(MemoryGraphList):
    r"""Dataset class for lists of graph tensor properties that can be cast into the :obj:`tf.RaggedTensor` class.
    The graph list is expected to only store numpy arrays in place of the each node or edge information!

    .. note::
        Each graph attribute is expected to be a python list or iterable object containing numpy arrays.
        For example, the special attribute of :obj:`edge_indices` is expected to be a list of arrays of
        shape `(Num_edges, 2)` with the indices of node connections.
        The node attributes in :obj:`node_attributes` are numpy arrays of shape `(Num_nodes, Num_features)`.

    The Memory Dataset class inherits from :obj:`MemoryGeometricGraphList` and has further information
    about a location on disk, i.e. a file directory and a file name as well as a name of the dataset.

    .. code-block:: python

        from kgcnn.data.base import MemoryGraphDataset
        dataset = MemoryGraphDataset(data_directory="", dataset_name="Example", length=1)
        dataset.edge_indices = [np.array([[1, 0], [0, 1]])]
        dataset.edge_labels = [np.array([[0], [1]])]
        print(dataset.edge_indices, dataset.edge_labels)
        dataset.sort_edge_indices()
        print(dataset.edge_indices, dataset.edge_labels)

    The file directory and file name are not used directly. However, for :obj:`load()` and :obj:`safe()`,
    the default is constructed from the data directory and dataset name. File name and file directory is reserved for
    child classes.
    """

    fits_in_memory = True

    def __init__(self,
                 data_directory: str = None,
                 dataset_name: str = None,
                 file_name: str = None,
                 file_directory: str = None,
                 verbose: int = 10,
                 ):
        r"""Initialize a base class of :obj:`MemoryGraphDataset`.

        Args:
            data_directory (str): Full path to directory of the dataset. Default is None.
            file_name (str): Generic filename for dataset to read into memory like a 'csv' file. Default is None.
            file_directory (str): Name or relative path from :obj:`data_directory` to a directory containing sorted
                files. Default is None.
            dataset_name (str): Name of the dataset. Important for naming and saving files. Default is None.
            verbose (int): Logging level. Default is 10.
        """
        super(MemoryGraphDataset, self).__init__()
        # For logging.
        self.logger = module_logger
        self.logger.setLevel(verbose)
        # Dataset information on file.
        self.data_directory = data_directory
        self.file_name = file_name
        self.file_directory = file_directory
        self.dataset_name = dataset_name
        # Data Frame for information.
        self.data_frame = None
        self.data_keys = None

    @property
    def file_path(self):
        if self.data_directory is None:
            self.warning("Data directory is not set.")
            return None
        if not os.path.exists(self.data_directory):
            self.error("Data directory does not exist.")
        if self.file_name is None:
            self.warning("Can not determine file path.")
            return None
        return os.path.join(self.data_directory, self.file_name)

    @property
    def file_directory_path(self):
        if self.data_directory is None:
            self.warning("Data directory is not set.")
            return None
        if not os.path.exists(self.data_directory):
            self.error("Data directory does not exist.")
        if self.file_directory is None:
            self.warning("Can not determine file directory.")
            return None
        return os.path.join(self.data_directory, self.file_directory)

    def info(self, *args, **kwargs):
        self.logger.info(*args, **kwargs)

    def warning(self, *args, **kwargs):
        self.logger.warning(*args, **kwargs)

    def error(self, *args, **kwargs):
        self.logger.error(*args, **kwargs)

    def save(self, filepath: str = None):
        r"""Save all graph properties to as dictionary as pickled file. By default saves a file named
        :obj:`dataset_name.kgcnn.pickle` in :obj:`data_directory`.

        Args:
            filepath (str): Full path of output file. Default is None.
        """
        if filepath is None:
            filepath = os.path.join(self.data_directory, self.dataset_name + ".kgcnn.pickle")
        self.info("Pickle dataset...")
        save_pickle_file([x._dict for x in self._list], filepath)
        return self

    def load(self, filepath: str = None):
        r"""Load graph properties from a pickled file. By default loads a file named
        :obj:`dataset_name.kgcnn.pickle` in :obj:`data_directory`.

        Args:
            filepath (str): Full path of input file.
        """
        if filepath is None:
            filepath = os.path.join(self.data_directory, self.dataset_name + ".kgcnn.pickle")
        self.info("Load pickled dataset...")
        in_list = load_pickle_file(filepath)
        self._list = [GraphNumpyContainer(graph=x) for x in in_list]
        return self

    def read_in_table_file(self, file_path: str = None, **kwargs):
        r"""Read a data frame in :obj:`data_frame` from file path. By default uses :obj:`file_name` and pandas.
        Checks for a '.csv' file and then for excel file endings. Meaning the file extension of file_path is ignored
        but must be any of the following '.csv', '.xls', '.xlsx', 'odt'.

        Args:
            file_path (str): File path to table file. Default is None.
            kwargs: Kwargs for pandas :obj:`read_csv` function.

        Returns:
            self
        """
        if file_path is None:
            file_path = os.path.join(self.data_directory, self.file_name)
        file_path_base = os.path.splitext(file_path)[0]
        # file_extension_given = os.path.splitext(file_path)[1]

        for file_extension in [".csv"]:
            if os.path.exists(file_path_base + file_extension):
                self.data_frame = pd.read_csv(file_path_base + file_extension, **kwargs)
                return self
        for file_extension in [".xls", ".xlsx", ".xlsm", ".xlsb", ".odf", ".ods", ".odt"]:
            if os.path.exists(file_path_base + file_extension):
                self.data_frame = pd.read_excel(file_path_base + file_extension, **kwargs)
                return self

        self.warning("Unsupported data extension of %s for table file." % file_path)
        return self


MemoryGeometricGraphDataset = MemoryGraphDataset

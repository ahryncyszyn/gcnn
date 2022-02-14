import importlib
import logging

# from typing import Any
from kgcnn.data.moleculenet import MoleculeNetDataset
from kgcnn.data.qm import QMDataset
from kgcnn.data.tudataset import GraphTUDataset

logging.basicConfig()  # Module logger
module_logger = logging.getLogger(__name__)
module_logger.setLevel(logging.INFO)

global_dataset_register = {
    "MoleculeNetDataset": MoleculeNetDataset,
    "QMDataset": QMDataset,
    "GraphTUDataset": GraphTUDataset
}


# Add all modules from datasets dynamically here
def deserialize(dataset: dict):
    r"""Deserialize a dataset class from dictionary including "class_name" and "config" keys.
    Furthermore, "prepare_data", "read_in_memory" and "set_attributes" are possible for deserialization.

    Args:
        dataset (str, dict): Dictionary of the dataset serialization.

    Returns:
        MemoryGraphDataset: Deserialized dataset.
    """
    global global_dataset_register

    # Requires dict. If already deserialized, nothing to do.
    if not isinstance(dataset, (dict, str)):
        module_logger.warning("Can not deserialize dataset %s." % dataset)
        return dataset

    # If only dataset name, make this into a dict with empty config.
    if isinstance(dataset, str):
        dataset = {"class_name": dataset, "config": {}}

    # Find dataset class in register.
    if dataset["class_name"] in global_dataset_register:
        ds_class = global_dataset_register[dataset["class_name"]]
        config = dataset["config"] if "config" in dataset else {}
        ds_instance = ds_class(**config)

    # Or load dynamically from datasets folder.
    else:
        dataset_name = dataset["class_name"]
        try:
            ds_class = getattr(importlib.import_module("kgcnn.data.datasets.%s" % dataset_name), str(dataset_name))
            config = dataset["config"] if "config" in dataset else {}
            ds_instance = ds_class(**config)
        except ModuleNotFoundError:
            raise NotImplementedError(
                "Unknown identifier %s, which is not in the sub-classed modules in kgcnn.data.datasets" % dataset_name)

    # Call class methods to load data.
    # Order is important here.
    method_list = ["prepare_data", "read_in_memory", "set_attributes"]
    for x in method_list:
        if x in dataset and hasattr(ds_instance, x):
            getattr(ds_instance, x)(**dataset[x])

    return ds_instance
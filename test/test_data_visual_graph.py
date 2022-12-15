import os
import unittest

from visual_graph_datasets.testing import TestingConfig

from kgcnn.data.visual_graph import VisualGraphDataset


class TestVisualGraphDataset(unittest.TestCase):

    def test_basically_works(self):
        """
        If the VisualGraphDataset class generally works. Attempts to load the "mock" dataset into memory.
        """
        with TestingConfig() as config:
            # The dataset "mock" is a small dataset which should always be available for testing purposes.
            # the dataset contains exactly 100 randomly generated graphs, which is what we test for later
            # on as well to confirm that it works.
            vgd = VisualGraphDataset('mock', config=config)

            vgd.ensure()
            self.assertTrue(os.path.exists(vgd.data_directory))

            vgd.read_in_memory()
            self.assertNotEqual(0, len(vgd))
            self.assertEqual(100, len(vgd))

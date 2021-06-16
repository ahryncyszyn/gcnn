import tensorflow as tf
import tensorflow.keras as ks
import numpy as np

from kgcnn.ops.models import generate_mol_graph_input,update_model_args
from kgcnn.layers.gather import GatherNodes
from kgcnn.layers.geom import SphericalBasisLayer, NodeDistance, EdgeAngle, BesselBasisLayer
from kgcnn.layers.keras import Dense, Concatenate, Add
from kgcnn.layers.interaction import DimNetInteractionPPBlock
from kgcnn.layers.blocks import DimNetOutputBlock
from kgcnn.layers.pooling import PoolingNodes

# Fast and Uncertainty-Aware Directional Message Passing for Non-Equilibrium Molecules
# Johannes Klicpera, Shankari Giri, Johannes T. Margraf, Stephan Günnemann
# https://arxiv.org/abs/2011.14115

def make_dimnet_pp(
        # Input
        input_node_shape,
        input_embedd: dict = None,
        # Output
        output_embedd: dict = None,
        # Model specific parameter
        emb_size=128,
        out_emb_size=256,
        int_emb_size=64,
        basis_emb_size=8,
        num_blocks=4,
        num_spherical=7,
        num_radial=6,
        cutoff=5.0,
        envelope_exponent=5,
        num_before_skip=1,
        num_after_skip=2,
        num_dense_output=3,
        num_targets=12,
        activation="swish",
        extensive=True,
        output_init='zeros',
        ):
    """Make DimeNet++ network.

    Args:
        input_node_shape (list): Shape of node features. If shape is (None,) embedding layer is used.
        input_embedd (dict): Dictionary of embedding parameters used if input shape is None. Default is
            {'input_embedd': {'input_node_vocab': 95, 'input_node_embedd': 64, 'input_tensor_type': 'ragged'}}
        output_embedd (dict): Dictionary of embedding parameters of the graph network. Not used.
        emb_size (int): Embedding size used for the messages. Default is 128.
        out_emb_size (int): Embedding size used for atoms in the output block. Default is 256.
        int_emb_size (int): Embedding size used for interaction triplets. Default is 64.
        basis_emb_size (int): Embedding size used inside the basis transformation. Default is 8.
        num_blocks (int): Number of building blocks to be stacked. Default is 4.
        num_spherical (int): Number of spherical harmonics. Default is 7.
        num_radial (int): Number of radial basis functions. Default is 6.
        cutoff (float): Cutoff distance for inter-atomic interactions. Default is 5.0.
        envelope_exponent (int): Shape of the smooth cutoff. Default is 5.
        num_before_skip (int): Number of residual layers in interaction block before skip connection. Default is 1.
        num_after_skip (int): Number of residual layers in interaction block after skip connection. Default is 2.
        num_dense_output (int): Number of dense layers for the output blocks. Default is 3.
        num_targets (int): Number of targets to predict. Default is 12.
        activation (int): Activation function. Default is 'swish'.
        extensive (int): Whether the output should be extensive (proportional to the number of atoms). Default is True.
        output_init (int): Initialization method for the output layer (last layer in output block). Default is 'zeros'.

    Returns:
        tf.keras.model: DimeNet++ model.
    """
    model_default = {'input_embedd': {'input_node_vocab': 95, 'input_node_embedd': 64, 'input_tensor_type': 'ragged'}
                     }

    input_embedd = update_model_args(model_default['input_embedd'], input_embedd)
    node_input, n, xyz_input, bond_index_input, angle_index_input, _ = generate_mol_graph_input(input_node_shape,
                                                                                                [None, 3],
                                                                                                [None, 2],
                                                                                                [None, 2],
                                                                                                **input_embedd)
    x = xyz_input
    edi = bond_index_input
    adi = angle_index_input

    # Calculate distances
    d = NodeDistance()([x, edi])
    rbf = BesselBasisLayer(num_radial=num_radial, cutoff=cutoff, envelope_exponent=envelope_exponent)(d)

    # Calculate angles
    a = EdgeAngle()([x, edi, adi])
    sbf = SphericalBasisLayer(num_spherical=num_spherical, num_radial=num_radial, cutoff=cutoff,
                              envelope_exponent=envelope_exponent)([d, a, adi])

    # Embedding block
    rbf_emb = Dense(emb_size, use_bias=True, activation=activation, kernel_initializer="orthogonal")(rbf)
    n_pairs = GatherNodes()([n, edi])
    x = Concatenate(axis=-1)([n_pairs, rbf_emb])
    x = Dense(emb_size, use_bias=True, activation=activation, kernel_initializer="orthogonal")(x)
    ps = DimNetOutputBlock(emb_size, out_emb_size, num_dense_output, num_targets=num_targets,
                           output_kernel_initializer=output_init)([n, x, rbf, edi])

    # Interaction blocks
    add_xp = Add()
    for i in range(num_blocks):
        x = DimNetInteractionPPBlock(emb_size, int_emb_size, basis_emb_size, num_before_skip, num_after_skip)(
            [x, rbf, sbf, adi])
        p_update = DimNetOutputBlock(emb_size, out_emb_size, num_dense_output, num_targets=num_targets,
                                     output_kernel_initializer=output_init)([n, x, rbf, edi])
        ps = add_xp([ps, p_update])

    if extensive:
        main_output = PoolingNodes(pooling_method="sum")(ps)
    else:
        main_output = PoolingNodes(pooling_method="mean")(ps)

    model = tf.keras.models.Model(inputs=[node_input, xyz_input, bond_index_input, angle_index_input],
                                  outputs=main_output)

    return model



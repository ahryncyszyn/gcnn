import tensorflow as tf
import tensorflow.keras as ks

from kgcnn.layers.casting import ChangeTensorType
from kgcnn.layers.conv.attention import AttentionHeadGATV2
from kgcnn.layers.modules import LazyConcatenate, DenseEmbedding, LazyAverage, ActivationEmbedding
from kgcnn.layers.mlp import MLPEmbedding, MLP
from kgcnn.layers.pooling import PoolingNodes
from kgcnn.utils.models import generate_embedding, update_model_kwargs

# Graph Attention Networks by Veličković et al. (2018)
# https://arxiv.org/abs/1710.10903
# Improved by
# How Attentive are Graph Attention Networks?
# by Brody et al. (2021)

model_default = {'name': "GATv2",
                 'inputs': [{'shape': (None,), 'name': "node_attributes", 'dtype': 'float32', 'ragged': True},
                            {'shape': (None,), 'name': "edge_attributes", 'dtype': 'float32', 'ragged': True},
                            {'shape': (None, 2), 'name': "edge_indices", 'dtype': 'int64', 'ragged': True}],
                 'input_embedding': {"node": {"input_dim": 95, "output_dim": 64},
                                     "edge": {"input_dim": 5, "output_dim": 64}},
                 'output_embedding': 'graph',
                 'output_mlp': {"use_bias": [True, True, False], "units": [25, 10, 1],
                                "activation": ['relu', 'relu', 'sigmoid']},
                 'attention_args': {"units": 32, "use_final_activation": False, "use_edge_features": True,
                                    "has_self_loops": True, "activation": "kgcnn>leaky_relu", "use_bias": True},
                 'pooling_nodes_args': {'pooling_method': 'mean'},
                 'depth': 3, 'attention_heads_num': 5,
                 'attention_heads_concat': False, 'verbose': 1
                 }


@update_model_kwargs(model_default)
def make_model(inputs=None,
               input_embedding=None,
               output_embedding=None,
               output_mlp=None,
               attention_args=None,
               pooling_nodes_args=None,
               depth=None,
               attention_heads_num=None,
               attention_heads_concat=None,
               name=None,
               verbose=None):
    """Make GATv2 graph network via functional API. Default parameters can be found in :obj:`model_default`.

    Args:
        inputs (list): List of dictionaries unpacked in :obj:`tf.keras.layers.Input`. Order must match model definition.
        input_embedding (dict): Dictionary of embedding arguments for nodes etc. unpacked in `Embedding` layers.
        output_embedding (str): Main embedding task for graph network. Either "node", ("edge") or "graph".
        output_mlp (dict): Dictionary of layer arguments unpacked in the final classification `MLP` layer block.
            Defines number of model outputs and activation.
        attention_args (dict): Dictionary of layer arguments unpacked in `AttentionHeadGATV2` layer.
        pooling_nodes_args (dict): Dictionary of layer arguments unpacked in `PoolingNodes` layer.
        depth (int): Number of graph embedding units or depth of the network.
        attention_heads_num (int): Number of attention heads to use.
        attention_heads_concat (bool): Whether to concat attention heads. Otherwise average heads.
        name (str): Name of the model.
        verbose (int): Level of print output.

    Returns:
        tf.keras.models.Model
    """

    # Make input
    node_input = ks.layers.Input(**inputs[0])
    edge_input = ks.layers.Input(**inputs[1])
    edge_index_input = ks.layers.Input(**inputs[2])

    # Embedding, if no feature dimension
    n = generate_embedding(node_input, inputs[0]['shape'], input_embedding['node'])
    ed = generate_embedding(edge_input, inputs[1]['shape'], input_embedding['edge'])
    edi = edge_index_input

    # Model
    nk = DenseEmbedding(units=attention_args["units"], activation="linear")(n)
    for i in range(0, depth):
        heads = [AttentionHeadGATV2(**attention_args)([nk, ed, edi]) for _ in range(attention_heads_num)]
        if attention_heads_concat:
            nk = LazyConcatenate(axis=-1)(heads)
        else:
            nk = LazyAverage()(heads)
            nk = ActivationEmbedding(activation=attention_args["activation"])(nk)
    n = nk

    # Output embedding choice
    if output_embedding == 'graph':
        out = PoolingNodes(**pooling_nodes_args)(n)
        out = ks.layers.Flatten()(out)  # will be dense
        main_output = MLP(**output_mlp)(out)
    elif output_embedding == 'node':
        out = MLPEmbedding(**output_mlp)(n)
        main_output = ChangeTensorType(input_tensor_type="ragged", output_tensor_type="tensor")(out)
    else:
        raise ValueError("Unsupported graph embedding for `GATv2`")

    # Define model output
    model = tf.keras.models.Model(inputs=[node_input, edge_input, edge_index_input], outputs=main_output)
    return model

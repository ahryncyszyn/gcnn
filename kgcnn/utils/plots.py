import matplotlib.pyplot as plt
import numpy as np
import os


def plot_train_test_loss(histories: list, loss_name: str = "loss",
                         val_loss_name: str = "val_loss", data_unit: str = "", model_name: str = "",
                         filepath: str = None, file_name: str = "", dataset_name: str = ""
                         ):
    r"""Plot training curves for a list of fit results in form of keras history objects. This means, training-
    and test-loss is plotted vs. epochs for all splits.

    Args:
        histories (list): List of :obj:`tf.keras.callbacks.History()` objects.
        loss_name (str): Which loss or metric to pick from history for plotting. Default is "loss".
        val_loss_name (str): Which validation loss or metric to pick from history for plotting. Default is "val_loss".
        data_unit (str): Unit of the loss. Default is "".
        model_name (str): Name of the model. Default is "".
        filepath (str): Full path where to save plot to, without the name of the file. Default is "".
        file_name (str): File name base. Model name and dataset will be added to the name. Default is "".
        dataset_name (str): Name of the dataset which was fitted to. Default is "".

    Returns:
        matplotlib.pyplot.figure: Figure of the training curves.
    """
    # We assume multiple fits as in KFold.
    train_loss = []
    for hist in histories:
        train_mae = np.array(hist.history[loss_name])
        train_loss.append(train_mae)
    val_loss = []
    for hist in histories:
        val_mae = np.array(hist.history[val_loss_name])
        val_loss.append(val_mae)

    # Determine a mea
    mean_valid = [np.mean(x[-1:]) for x in val_loss]

    # val_step
    val_step = len(train_loss[0]) / len(val_loss[0])

    fig = plt.figure()
    for x in train_loss:
        plt.plot(np.arange(x.shape[0]), x, c='red', alpha=0.85)
    for y in val_loss:
        plt.plot(np.arange(y.shape[0]) * val_step, y, c='blue', alpha=0.85)
    plt.scatter([train_loss[-1].shape[0]], [np.mean(mean_valid)],
                label=r"Test: {0:0.4f} $\pm$ {1:0.4f} ".format(np.mean(mean_valid), np.std(mean_valid)) + data_unit,
                c='blue')
    plt.xlabel('Epochs')
    plt.ylabel('Loss')
    plt.title(dataset_name + " training curve for " + model_name)
    plt.legend(loc='upper right', fontsize='medium')
    if filepath is not None:
        plt.savefig(os.path.join(filepath, model_name + "_" + dataset_name + "_" + file_name))
    plt.show()
    return fig


def plot_predict_true(y_predict, y_true, data_unit: list = None, model_name: str = "",
                      filepath: str = None, file_name: str = "", dataset_name: str = "", target_names: list = None
                      ):
    r"""Make a scatter plot of predicted versus actual targets. Not for k-splits.

    Args:
        y_predict (np.ndarray): Numpy array of shape `(N_samples, n_targets)` or `(N_samples, )`.
        y_true (np.ndarray): Numpy array of shape `(N_samples, n_targets)` or `(N_samples, )`.
        data_unit (list): String or list of string that matches `n_targets`. Name of the data's unit.
        model_name (str): Name of the model. Default is "".
        filepath (str): Full path where to save plot to, without the name of the file. Default is "".
        file_name (str): File name base. Model name and dataset will be added to the name. Default is "".
        dataset_name (str): Name of the dataset which was fitted to. Default is "".
        target_names (list): String or list of string that matches `n_targets`. Name of the targets.

    Returns:
        matplotlib.pyplot.figure: Figure of the scatter plot.
    """
    if len(y_predict.shape) == 1:
        y_predict = np.expand_dims(y_predict, axis=-1)
    if len(y_true.shape) == 1:
        y_true = np.expand_dims(y_true, axis=-1)
    num_targets = y_true.shape[1]

    if data_unit is None:
        data_unit = ""
    if isinstance(data_unit, str):
        data_unit = [data_unit]*num_targets
    if len(data_unit) != num_targets:
        print("WARNING:kgcnn: Targets do not match units for plot.")
    if target_names is None:
        target_names = ""
    if isinstance(target_names, str):
        target_names = [target_names]*num_targets
    if len(target_names) != num_targets:
        print("WARNING:kgcnn: Targets do not match names for plot.")

    fig = plt.figure()
    for i in range(num_targets):
        mae_valid = np.mean(np.abs(y_true[:, i] - y_predict[:, i]))
        plt.scatter(y_predict[:, i], y_true[:, i], alpha=0.3,
                    label=target_names[i] + " MAE: {0:0.4f} ".format(mae_valid) + "[" + data_unit[i] + "]")
    plt.plot(np.arange(np.amin(y_true), np.amax(y_true), 0.05),
             np.arange(np.amin(y_true), np.amax(y_true), 0.05), color='red')
    plt.xlabel('Predicted')
    plt.ylabel('Actual')
    plt.title("Prediction of " + model_name + " for " + dataset_name)
    plt.legend(loc='upper left', fontsize='x-large')
    if filepath is not None:
        plt.savefig(os.path.join(filepath, model_name + "_" + dataset_name + "_" + file_name))
    plt.show()
    return fig
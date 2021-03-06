import globals
from dataset import read_draw, numbers_to_words, derivation_to_equation
from template_parser import debug
import os
import nltk
import numpy as np
import scoring_function as sf
from keras.layers import Bidirectional, LSTM, Flatten, Dense, PReLU, MaxPool1D, Input, Embedding, TimeDistributed, \
    BatchNormalization, concatenate, Conv1D
from keras.models import Model
from keras.preprocessing.sequence import pad_sequences
from sklearn.model_selection import train_test_split
from dsbox_spen.dsbox.spen.core import spen as sp, config, energy
from dsbox_spen.dsbox.spen.utils.metrics import token_level_loss_ar, token_level_loss

GLOVE_DIR = 'glove.6B'
EMBEDDING_DIM = 50  # 50
MAX_SEQUENCE_LENGTH = 105

worddict = {}
text2sols = {}
text2align = {}


def feed_forward_mlp_model(input_shape, b_vocab, emb_layer):
    '''
    Deep neural network model to get F(x) which is to be fed to SPENs
    '''
    a = Input(shape=input_shape)
    b = Input(shape=input_shape)
    emb_a = emb_layer(a)
    emb_b = Embedding(b_vocab + 1, 5, input_length=input_shape)(b)
    tensor_a = Bidirectional(LSTM(32, return_sequences=True))(emb_a)
    tensor_b = Bidirectional(LSTM(32, return_sequences=True))(emb_b)
    l0 = concatenate([tensor_a, tensor_b], axis=2)
    l0 = Bidirectional(LSTM(64, return_sequences=True))(l0)
    l8 = TimeDistributed(Dense(21, activation='softmax'), name='seq')(l0)
    l0 = Conv1D(256, 3)(l0)
    l0 = Conv1D(256, 3)(l0)
    l0 = Flatten()(l0)
    l0 = Dense(256)(l0)
    l0 = BatchNormalization()(l0)
    l0 = PReLU()(l0)
    l1 = Dense(25, activation='softmax', name='t_id')(l0)
    l2 = Dense(globals.PROBLEM_LENGTH, activation='softmax', name='a')(l0)
    l3 = Dense(globals.PROBLEM_LENGTH, activation='softmax', name='b')(l0)
    l4 = Dense(globals.PROBLEM_LENGTH, activation='softmax', name='c')(l0)
    l5 = Dense(globals.PROBLEM_LENGTH, activation='softmax', name='d')(l0)
    l6 = Dense(globals.PROBLEM_LENGTH, activation='softmax', name='e')(l0)
    l7 = Dense(globals.PROBLEM_LENGTH, activation='softmax', name='f')(l0)
    model = Model(inputs=[a, b], outputs=[l1, l2, l3, l4, l5, l6, l7, l8])
    model.compile('adam', {'t_id': 'sparse_categorical_crossentropy', 'a': 'sparse_categorical_crossentropy',
                           'b': 'sparse_categorical_crossentropy', 'c': 'sparse_categorical_crossentropy',
                           'd': 'sparse_categorical_crossentropy', 'e': 'sparse_categorical_crossentropy',
                           'f': 'sparse_categorical_crossentropy', 'seq': 'sparse_categorical_crossentropy'})
    return model


def get_layers():
    layers = [(1000, 'relu')]
    enlayers = [(250, 'softplus')]
    return (layers, enlayers)


def load_glove(vocab):
    # ref: https://blog.keras.io/using-pre-trained-word-embeddings-in-a-keras-model.html
    vocab_size = len(vocab.keys())
    word_index = vocab_size

    embeddings_index = {}
    f = open(os.path.join(GLOVE_DIR, 'glove.6B.%dd.txt' % EMBEDDING_DIM), encoding="utf8")
    for line in f:
        values = line.split()
        word = values[0]
        coefs = np.asarray(values[1:], dtype='float32')
        embeddings_index[word] = coefs
    f.close()
    print('Found %s word vectors.' % len(embeddings_index))

    # embedding_matrix = np.zeros((len(word_index) + 1, EMBEDDING_DIM))
    embedding_matrix = np.zeros((vocab_size + 1, EMBEDDING_DIM))

    # for word, i in word_index.items():
    for word, i in vocab.items():
        embedding_vector = embeddings_index.get(word)
        if embedding_vector is not None:
            # words not found in embedding index will be all-zeros.
            embedding_matrix[i] = embedding_vector

    from keras.layers import Embedding

    # embedding_layer = Embedding(len(word_index) + 1,
    embedding_layer = Embedding(vocab_size + 1,
                                EMBEDDING_DIM,
                                weights=[embedding_matrix],
                                input_length=MAX_SEQUENCE_LENGTH,
                                trainable=True)
    return embedding_layer


def evaluation_function(xinput=None, yinput=None, yt=None):
    xd = xinput
    yd = yinput
    size = np.shape(xd)[0]
    scorer = sf.Scorer()
    penalty = np.zeros(size)
    for i in range(size):
        x = xd[i, :]
        text = ''
        for j in range(x.shape[0]):
            text += ' ' + worddict[x[j]]
        penalty[i] = scorer.score_output(text, yd[i], text2sols[str(x)], text2align[str(x)])
    return penalty


def main():
    derivations, vocab_dataset = debug()
    X, Xtags, YSeq, Y, Z = derivations
    for key in vocab_dataset:
        worddict[vocab_dataset[key]] = key
    X = pad_sequences(X, padding='post', truncating='post', value=0., maxlen=globals.PROBLEM_LENGTH)
    Xtags = pad_sequences(Xtags, padding='post', truncating='post', value=0., maxlen=globals.PROBLEM_LENGTH)
    YSeq = pad_sequences(YSeq, padding='post', truncating='post', value=0., maxlen=globals.PROBLEM_LENGTH)
    YSeq = np.reshape(YSeq, (YSeq.shape[0], YSeq.shape[1], 1))
    for i in range(X.shape[0]):
        text2sols[str(X[i])] = Z[i]
        text2align[str(X[i])] = Y[i]
    emb_layer = load_glove(vocab_dataset)
    F = feed_forward_mlp_model(X.shape[1:], 36, emb_layer)
    X_train, X_test, Y_train, Y_test, Xtags_train, Xtags_test, YSeq_train, YSeq_test = train_test_split(X, Y, Xtags,
                                                                                                        YSeq,
                                                                                                        test_size=0.2,
                                                                                                        random_state=23)
    ntrain = X_train.shape[0]
    print(X_train.shape)
    print(YSeq.shape)
    # F.fit([X_train, Xtags_train],
    #       [Y_train[:, 0], Y_train[:, 1], Y_train[:, 2], Y_train[:, 3], Y_train[:, 4], Y_train[:, 5], Y_train[:, 6],
    #        YSeq_train],
    #       batch_size=128, epochs=20, validation_data=(
    #         [X_test, Xtags_test],
    #         [Y_test[:, 0], Y_test[:, 1], Y_test[:, 2], Y_test[:, 3], Y_test[:, 4], Y_test[:, 5], Y_test[:, 6],
    #          YSeq_test]))

    y_pred = np.argmax(F.predict([X_test, Xtags_test])[7], axis=2)
    global_acc = 0.0
    for i in range(y_pred.shape[0]):
        acc = 0.0
        for j in range(y_pred.shape[1]):
            if y_pred[i][j] == YSeq_test[i][j] and j < 20:
                acc += 1
        global_acc += (acc / y_pred.shape[1])
    print(global_acc)

    ###Configurable parameters START
    ln = 1e10
    l2 = 0.0
    lr = 0.001
    inf_iter = 20
    inf_rate = 0.1
    mw = 1000
    dp = 0.0
    bs = 100
    ip = 0.0
    output_num = Y.shape[1]
    input_num = X.shape[1]
    f_layers, en_layers = get_layers()

    config.l2_penalty = l2
    config.inf_iter = inf_iter
    config.inf_rate = inf_rate
    config.learning_rate = lr
    config.dropout = dp
    config.dimension = globals.PROBLEM_LENGTH + 1
    config.output_num = output_num
    config.input_num = input_num
    config.en_layer_info = en_layers
    config.layer_info = f_layers
    config.margin_weight = mw
    config.lstm_hidden_size = 16
    config.sequence_length = 105
    config.inf_penalty = ip
    ###Configurable parameters END
    s = sp.SPEN(config)
    e = energy.EnergyModel(config)
    s.get_energy = e.get_energy_rnn_mlp_emb
    s.evaluate = evaluation_function
    s.train_batch = s.train_unsupervised_batch

    s.createOptimizer()
    s.construct_embedding(EMBEDDING_DIM, len(vocab_dataset.keys()) + 1)
    s.construct(training_type=sp.TrainingType.Rank_Based)
    s.print_vars()

    s.init()
    s.init_embedding(F.get_layer('embedding_1').get_weights()[0])
    labeled_num = min((ln, ntrain))
    indices = np.arange(labeled_num)
    xlabeled = X_train[indices][:]
    ylabeled = Y_train[indices][:]
    xtags_labeled = Xtags_train[indices][:]
    print(xlabeled.shape)
    print(ylabeled.shape)

    total_num = xlabeled.shape[0]
    for i in range(1, 100):
        bs = min((bs, labeled_num))
        perm = np.random.permutation(total_num)

        for b in range(int(ntrain / bs)):
            indices = perm[b * bs:(b + 1) * bs]

            xbatch = xlabeled[indices][:]
            xbatch = np.reshape(xbatch, (xbatch.shape[0], -1))
            ybatch = ylabeled[indices][:]
            ybatch = np.reshape(ybatch, (ybatch.shape[0], -1))
            xtags_batch = xtags_labeled[indices][:]
            xtags_batch = np.reshape(xtags_batch, (xtags_batch.shape[0], -1))
            s.set_train_iter(i)
            s.train_batch(xbatch, verbose=4)

        if i % 2 == 0:
            yval_out = s.map_predict(xinput=np.reshape(Xtags_test, (Xtags_test.shape[0], -1)))
            print(yval_out)
            print(Y_test)
            hm_ts, ex_ts = token_level_loss(yval_out, Y_test)
            print(hm_ts)
            print(ex_ts)


globals.init()  # Fetch global variables such as PROBLEM_LENGTH
config = config.Config()
main()

from typing import List, Tuple, Optional
import shutil
import os
import pickle
import time

import numpy as np
import torch
import torch.nn as nn
from torch.autograd import Variable
from torch.nn import functional as F

from qanta import logging
from qanta.guesser.abstract import AbstractGuesser
from qanta.datasets.abstract import TrainingData, Answer, QuestionText
from qanta.preprocess import preprocess_dataset, tokenize_question
from qanta.guesser.nn import create_load_embeddings_function, convert_text_to_embeddings_indices, compute_n_classes
from qanta.manager import BaseLogger, TerminateOnNaN, EarlyStopping, ModelCheckpoint, MaxEpochStopping, TrainingManager


log = logging.get(__name__)


PTDAN_WE_TMP = '/tmp/qanta/deep/pt_dan_we.pickle'
PTDAN_WE = 'pt_dan_we.pickle'
load_embeddings = create_load_embeddings_function(PTDAN_WE_TMP, PTDAN_WE, log)


def flatten_and_offset(x_batch):
    flat_x_batch = []
    for r in x_batch:
        flat_x_batch.extend(r)
    flat_x_batch = np.array(flat_x_batch)
    x_lengths = [len(r) for r in x_batch]
    offsets = np.cumsum([0] + x_lengths[:-1])
    return flat_x_batch, offsets


def batchify(batch_size, x_array, y_array, truncate=True, shuffle=True):
    n_examples = x_array.shape[0]
    n_batches = n_examples // batch_size
    if shuffle:
        random_order = np.random.permutation(n_examples)
        x_array = x_array[random_order]
        y_array = y_array[random_order]

    t_x_batches = []
    t_offset_batches = []
    t_y_batches = []

    for b in range(n_batches):
        x_batch = x_array[b * batch_size:(b + 1) * batch_size]
        y_batch = y_array[b * batch_size:(b + 1) * batch_size]
        flat_x_batch, offsets = flatten_and_offset(x_batch)

        t_x_batches.append(torch.from_numpy(flat_x_batch).long().cuda())
        t_offset_batches.append(torch.from_numpy(offsets).long().cuda())
        t_y_batches.append(torch.from_numpy(y_batch).long().cuda())

    if (not truncate) and (batch_size * n_batches < n_examples):
        x_batch = x_array[n_batches * batch_size:]
        y_batch = y_array[n_batches * batch_size:]
        flat_x_batch, offsets = flatten_and_offset(x_batch)

        t_x_batches.append(torch.from_numpy(flat_x_batch).long().cuda())
        t_offset_batches.append(torch.from_numpy(offsets).long().cuda())
        t_y_batches.append(torch.from_numpy(y_batch).long().cuda())

    t_x_batches = np.array(t_x_batches)
    t_offset_batches = np.array(t_offset_batches)
    t_y_batches = np.array(t_y_batches)

    return n_batches, t_x_batches, t_offset_batches, t_y_batches


def create_save_model(model):
    def save_model(path):
        torch.save(model, path)
    return save_model


class DanGuesser(AbstractGuesser):
    def __init__(self, max_epochs=100, batch_size=128):
        super(DanGuesser, self).__init__()
        self.max_epochs = max_epochs
        self.batch_size = batch_size
        self.class_to_i = None
        self.i_to_class = None
        self.vocab = None
        self.embeddings = None
        self.embedding_lookup = None
        self.n_classes = None
        self.model = None
        self.criterion = None
        self.optimizer = None

    def guess(self, questions: List[QuestionText], max_n_guesses: Optional[int]) -> List[List[Tuple[Answer, float]]]:
        x_test = [convert_text_to_embeddings_indices(
            tokenize_question(q), self.embedding_lookup)
            for q in questions
        ]
        x_test = np.array(x_test)
        y_test = np.zeros(len(x_test))

        n_batches, t_x_batches, t_offset_batches, t_y_batches = batchify(
            self.batch_size, x_test, y_test, truncate=False, shuffle=False
        )

        self.model.eval()
        self.model.cuda()
        guesses = []
        for b in range(n_batches):
            t_x = Variable(t_x_batches[b], volatile=True)
            t_offset = Variable(t_offset_batches[b], volatile=True)
            out = self.model(t_x, t_offset)
            probs = F.softmax(out)
            scores, preds = torch.max(probs, 1)
            scores = scores.data.cpu().numpy()
            preds = preds.data.cpu().numpy()
            for p, s in zip(preds, scores):
                guesses.append([(p, s)])

        return guesses


    def train(self, training_data: TrainingData) -> None:
        x_train_text, y_train, x_test_text, y_test, vocab, class_to_i, i_to_class = preprocess_dataset(
            training_data
        )

        self.class_to_i = class_to_i
        self.i_to_class = i_to_class
        self.vocab = vocab

        embeddings, embedding_lookup = load_embeddings(vocab=vocab, expand_glove=True)
        self.embeddings = embeddings
        self.embedding_lookup = embedding_lookup

        x_train = np.array([convert_text_to_embeddings_indices(q, embedding_lookup) for q in x_train_text])
        y_train = np.array(y_train)

        x_test = np.array([convert_text_to_embeddings_indices(q, embedding_lookup) for q in x_test_text])
        y_test = np.array(y_test)

        self.n_classes = compute_n_classes(training_data[1])

        n_batches_train, t_x_train, t_offset_train, t_y_train = batchify(
            self.batch_size, x_train, y_train, truncate=True)
        n_batches_test, t_x_test, t_offset_test, t_y_test = batchify(
            self.batch_size, x_test, y_test, truncate=False)

        self.model = DanModel(embeddings.shape[0], self.n_classes)
        self.model.init_weights(initial_embeddings=embeddings)
        self.model.cuda()
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=.001)
        self.criterion = nn.CrossEntropyLoss()

        manager = TrainingManager([
            BaseLogger(), TerminateOnNaN(),
            EarlyStopping(patience=5), MaxEpochStopping(100),
            ModelCheckpoint(create_save_model(self.model), '/tmp/dan.pt')
        ])

        log.info('Starting training...')
        while True:
            self.model.train()
            train_acc, train_loss, train_time = self.run_epoch(
                n_batches_train,
                t_x_train, t_offset_train, t_y_train, evaluate=False
            )

            self.model.eval()
            test_acc, test_loss, test_time = self.run_epoch(
                n_batches_test,
                t_x_test, t_offset_test, t_y_test, evaluate=True
            )

            stop_training, reasons = manager.instruct(
                train_time, train_loss, train_acc,
                test_time, test_loss, test_acc
            )

            if stop_training:
                log.info(' '.join(reasons))
                break

    def run_epoch(self, n_batches, t_x_array, t_offset_array, t_y_array, evaluate=False):
        if not evaluate:
            random_batch_order = np.random.permutation(n_batches)
            t_x_array = t_x_array[random_batch_order]
            t_offset_array = t_offset_array[random_batch_order]
            t_y_array = t_y_array[random_batch_order]

        batch_accuracies = []
        batch_losses = []
        epoch_start = time.time()
        for batch in range(n_batches):
            t_x_batch = Variable(t_x_array[batch], volatile=evaluate)
            t_offset_batch = Variable(t_offset_array[batch], volatile=evaluate)
            t_y_batch = Variable(t_y_array[batch], volatile=evaluate)

            self.model.zero_grad()
            out = self.model(t_x_batch, t_offset_batch)
            _, preds = torch.max(out, 1)
            accuracy = torch.mean(torch.eq(preds, t_y_batch).float()).data[0]
            batch_loss = self.criterion(out, t_y_batch)
            if not evaluate:
                batch_loss.backward()
                self.optimizer.step()

            batch_accuracies.append(accuracy)
            batch_losses.append(batch_loss.data[0])

        epoch_end = time.time()

        return np.mean(batch_accuracies), np.mean(batch_losses), epoch_end - epoch_start


    def save(self, directory: str) -> None:
        shutil.copyfile('/tmp/dan.pt', os.path.join(directory, 'dan.pt'))
        with open(os.path.join(directory, 'dan.pickle'), 'wb') as f:
            pickle.dump({
                'vocab': self.vocab,
                'class_to_i': self.class_to_i,
                'i_to_class': self.i_to_class,
                'embeddings': self.embeddings,
                'embeddings_lookup': self.embedding_lookup,
                'n_classes': self.n_classes,
                'max_epochs': self.max_epochs,
                'batch_size': self.batch_size
            }, f)

    @classmethod
    def load(cls, directory: str):
        with open(os.path.join(directory, 'dan.pickle'), 'rb') as f:
            params = pickle.load(f)

        guesser = DanGuesser()
        guesser.vocab = params['vocab']
        guesser.class_to_i = params['class_to_i']
        guesser.i_to_class = params['i_to_class']
        guesser.embeddings = params['embeddings']
        guesser.embedding_lookup = params['embedding_lookup']
        guesser.n_classes = params['n_classes']
        guesser.max_epochs = params['max_epochs']
        guesser.batch_size = params['batch_size']
        guesser.model = torch.load(os.path.join(directory, 'dan.pt'))
        return guesser

    @classmethod
    def targets(cls) -> List[str]:
        return ['dan.pickle', 'dan.pt']


class DanModel(nn.Module):
    def __init__(self, vocab_size, n_classes,
                 embedding_dim=300,
                 dropout_prob=.5, word_dropout_prob=.5,
                 n_hidden_layers=1, n_hidden_units=1000, non_linearity='relu',
                 init_scale=.1):
        super(DanModel, self).__init__()
        self.n_hidden_layers = 1
        self.non_linearity = non_linearity
        self.n_hidden_units = n_hidden_units
        self.dropout_prob = dropout_prob
        self.word_dropout_prob = word_dropout_prob
        self.vocab_size = vocab_size
        self.n_classes = n_classes
        self.embedding_dim = embedding_dim
        self.init_scale = init_scale

        self.dropout = nn.Dropout(dropout_prob)
        self.word_dropout = nn.Dropout2d(word_dropout_prob)
        self.embeddings = nn.EmbeddingBag(vocab_size, embedding_dim)

        layers = []
        for i in range(n_hidden_layers):
            if i == 0:
                input_dim = embedding_dim
            else:
                input_dim = n_hidden_units

            layers.extend([
                nn.Linear(input_dim, n_hidden_units),
                nn.Dropout(dropout_prob),
                nn.ReLU()
            ])

        layers.extend([
            nn.Linear(n_hidden_units, n_classes),
            nn.Dropout(dropout_prob)
        ])
        self.layers = nn.Sequential(*layers)

        self.init_weights()

    def init_weights(self, initial_embeddings=None):
        if initial_embeddings is not None:
            self.embeddings.weight = nn.Parameter(torch.from_numpy(initial_embeddings).float())

    def forward(self, input_: Variable, offsets: Variable):
        avg_embeddings = self.dropout(self.embeddings(input_.view(-1), offsets))
        return self.layers(avg_embeddings)

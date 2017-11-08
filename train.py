import argparse
import random

import dynet

from stack_lstm import (
    StackLSTMBuilder, START_SYMBOL, SEPARATOR_SYMBOL, END_SYMBOL,
    input_symbol_to_index, output_symbol_to_index, output_index_to_symbol)
from util import transpose, argmax


def random_sequence(length, alphabet_size):
    return Sequence([3 + random.randrange(alphabet_size) for i in range(length)])


class Sequence:
    def __init__(self, source_sequence):
        self.source_sequence = source_sequence

    def input_sequence(self):
        yield START_SYMBOL
        for symbol in self.source_sequence:
            yield symbol
        yield SEPARATOR_SYMBOL

    def output_sequence(self):
        for symbol in reversed(self.source_sequence):
            yield symbol
        yield END_SYMBOL

    def output_sequence_length(self):
        return len(self.source_sequence) + 1


def parse_range(arg):
    lo, hi = arg.split(',')
    return int(lo), int(hi)


def train(args, builder, params):
    trainer = dynet.RMSPropTrainer(params, args.learning_rate)
    trainer.set_clip_threshold(args.clip_threshold)
    for group_no in range(args.iterations):
        print('batch group #%d...' % (group_no + 1))
        batch_group_loss = 0.0
        for batch_no in range(args.batch_group_size):
            # Sample a new batch of training data
            length = random.randint(*args.training_length_range)
            batch = [
                random_sequence(length, args.source_alphabet_size)
                for i in range(args.batch_size)]
            # Arrange the input and output halves of the sequences into batches
            # of individual symbols
            input_sequence_batch = transpose(s.input_sequence() for s in batch)
            output_sequence_batch = transpose(s.output_sequence() for s in batch)
            # Start building the computation graph for this batch
            dynet.renew_cg()
            state = builder.initial_state(args.batch_size)
            # Feed everything up to the separator symbol into the model; ignore
            # outputs
            for symbol_batch in input_sequence_batch:
                index_batch = [input_symbol_to_index(s) for s in symbol_batch]
                state = state.next(index_batch, StackLSTMBuilder.INPUT_MODE)
            # Feed the rest of the sequence into the model and sum up the loss
            # over the predicted symbols
            symbol_losses = []
            for symbol_batch in output_sequence_batch:
                index_batch = [output_symbol_to_index(s) for s in symbol_batch]
                symbol_loss = dynet.pickneglogsoftmax_batch(state.output(), index_batch)
                symbol_losses.append(symbol_loss)
                state = state.next(index_batch, StackLSTMBuilder.OUTPUT_MODE)
            loss = dynet.sum_batches(dynet.esum(symbol_losses))
            # Forward pass
            loss_value = loss.value()
            batch_group_loss += loss_value
            # Backprop
            loss.backward()
            # Update parameters
            trainer.update()
        avg_loss = batch_group_loss / (args.batch_size * args.batch_group_size)
        print('  average loss: %0.2f' % avg_loss)


def test(args, builder):
    print('testing...')
    total_fine_correct = 0.0
    total_coarse_correct = 0
    for test_no in range(args.test_data_size):
        fine_correct = 0
        # Generate a new test example
        length = random.randint(*args.test_length_range)
        sequence = random_sequence(length, args.source_alphabet_size)
        # Start building the computation graph for this sequence
        dynet.renew_cg()
        state = builder.initial_state(1)
        # Feed everything up to and including the separator symbol into the
        # model
        for symbol in sequence.input_sequence():
            index = input_symbol_to_index(symbol)
            state = state.next([index], StackLSTMBuilder.INPUT_MODE)
        # Feed the rest of the sequence into the model and stop at the first
        # error
        for correct_symbol in sequence.output_sequence():
            predicted_index = argmax(state.output().value())
            predicted_symbol = output_index_to_symbol(predicted_index)
            if predicted_symbol == correct_symbol:
                fine_correct += 1
                state = state.next([predicted_index], StackLSTMBuilder.OUTPUT_MODE)
            else:
                break
        fine_total = sequence.output_sequence_length()
        total_fine_correct += (fine_correct / fine_total)
        total_coarse_correct += (fine_correct == fine_total)
    fine_accuracy = total_fine_correct / args.test_data_size
    coarse_accuracy = total_coarse_correct / args.test_data_size
    print('fine accuracy:   %0.2f' % fine_accuracy)
    print('coarse accuracy: %0.2f' % coarse_accuracy)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hidden-units', type=int, default=256,
                        help='Number of hidden units to use in the LSTM controller.')
    parser.add_argument('--learning-rate', type=float, default=0.001,
                        help='Initial learning rate for RMSProp.')
    parser.add_argument('--iterations', type=int, default=20,
                        help='Number of iterations of training to run. By default, each iteration is equivalent to 1000 training examples.')
    parser.add_argument('--source-alphabet-size', type=int, default=128,
                        help='Number of symbols to use in the source sequence.')
    parser.add_argument('--embedding-size', type=int, default=64,
                        help='Input embedding size.')
    parser.add_argument('--stack-embedding-size', type=int, default=256,
                        help='Size of vector values stored on the neural stack.')
    parser.add_argument('--clip-threshold', type=float, default=1.0,
                        help='Gradient clipping threshold.')
    parser.add_argument('--batch-size', type=int, default=10,
                        help='Batch size.')
    parser.add_argument('--batch-group-size', type=int, default=100,
                        help='Number of batches per iteration.')
    parser.add_argument('--training-length-range', type=parse_range, default=(8, 64),
                        help='Range of lengths of source sequences during training.',
                        metavar='MIN,MAX')
    parser.add_argument('--test-length-range', type=parse_range, default=(65, 128),
                        help='Range of lengths of source sequences during testing.',
                        metavar='MIN,MAX')
    parser.add_argument('--test-data-size', type=int, default=1000,
                        help='Number of samples used in the test data.')
    parser.add_argument('--output', type=str, default=None,
                        help='Optional output file where parameters will be saved after training.')
    args = parser.parse_args()

    params = dynet.ParameterCollection()
    builder = StackLSTMBuilder(
        params,
        source_alphabet_size=args.source_alphabet_size,
        embedding_size=args.embedding_size,
        stack_embedding_size=args.stack_embedding_size,
        hidden_units=args.hidden_units)
    train(args, builder, params)
    if args.output is not None:
        params.save(args.output)
        print('parameters saved to %s' % args.output)
    test(args, builder)


if __name__ == '__main__':
    main()

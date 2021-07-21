# Imports
import argformat
import argparse
import torch

# DeepCASE imports
from deepcase.preprocessing   import Preprocessor
from deepcase.context_builder import ContextBuilder
from deepcase.interpreter     import Interpreter
from deepcase.utils           import show_sequences

if __name__ == "__main__":

    ########################################################################
    #                           Parse arguments                            #
    ########################################################################

    # Parse arguments
    parser = argparse.ArgumentParser(
        prog            = "deepcase.py",
        description     = "DeepCASE: Semi-Supervised Contextual Analysis of Security Events",
        formatter_class = argformat.StructuredFormatter,
    )

    # Add DeepCASE mode arguments, run in different modes
    parser.add_argument('mode', help="mode in which to run DeepCASE", choices=(
        'sequence',
        'train',
        'manual',
        'automatic',
    ))

    # Add I/O arguments
    group_io = parser.add_argument_group("Input/Output")
    group_io.add_argument('--csv'   , help="CSV events file to process")
    group_io.add_argument('--txt'   , help="TXT events file to process")
    group_io.add_argument('--events', default='auto', help="number of distinct events to handle")
    # group_io.add_argument('--save-sequences', help="JSON file to store      sequences")

    # Add Sequence arguments
    group_sequences = parser.add_argument_group("Sequencing")
    group_sequences.add_argument('--length'  , type=int  , default=10   , help="sequence LENGTH           ")
    group_sequences.add_argument('--timeout' , type=float, default=86400, help="sequence TIMEOUT (seconds)")
    group_sequences.add_argument('--save-sequences', help="path to save sequences")
    group_sequences.add_argument('--load-sequences', help="path to load sequences")

    # Add ContextBuilder arguments
    group_builder = parser.add_argument_group("ContextBuilder")
    group_builder.add_argument('--hidden', type=int  , default=128, help="HIDDEN layers dimension")
    group_builder.add_argument('--delta' , type=float, default=0.1, help="label smoothing DELTA")
    group_builder.add_argument('--save-builder', help="path to save ContextBuilder")
    group_builder.add_argument('--load-builder', help="path to load ContextBuilder")

    # Add Interpreter arguments
    group_interpreter = parser.add_argument_group("Interpreter")
    group_interpreter.add_argument('--confidence' , type=float, default=0.2, help="minimum required CONFIDENCE")
    group_interpreter.add_argument('--epsilon'    , type=float, default=0.1, help="DBSCAN clustering EPSILON")
    group_interpreter.add_argument('--min_samples', type=int  , default=5  , help="DBSCAN clustering MIN_SAMPLES")
    group_interpreter.add_argument('--save-interpreter', help="path to save Interpreter")
    group_interpreter.add_argument('--load-interpreter', help="path to load Interpreter")

    # Add Training arguments
    group_train = parser.add_argument_group("Train")
    group_train.add_argument('--epochs', type=int, default=10 , help="number of epochs to train with")
    group_train.add_argument('--batch' , type=int, default=128, help="batch size       to train with")

    # Add other arguments
    group_other = parser.add_argument_group("Other")
    group_other.add_argument('--device', default='auto', help="DEVICE used for computation (cpu|cuda|auto)")

    # Parse arguments
    args = parser.parse_args()

    ########################################################################
    #                     A. Security event sequences                      #
    ########################################################################

    # Create preprocessor
    preprocessor = Preprocessor(
        length  = args.length,
        timeout = args.timeout,
    )

    # Load files
    if args.csv is not None and args.txt is not None:
        # Raise an error if both csv and txt are specified
        raise ValueError("Please specify EITHER --csv OR --txt.")
    if args.csv:
        # Load csv file
        events, context, label, mapping = preprocessor.csv(args.csv)
    elif args.txt:
        # Load txt file
        events, context, label, mapping = preprocessor.txt(args.txt)

    # Save sequences if necessary
    if args.save_sequences:
        with open(args.save_sequences, 'wb') as outfile:
            torch.save({
                "events" : events,
                "context": context,
                "label"  : label,
                "mapping": mapping,
            }, outfile)

    # Load sequences if necessary
    if args.load_sequences:
        with open(args.load_sequences, 'rb') as infile:
            # Load data
            data = torch.load(infile)
            # Extract data
            events  = data["events"]
            context = data["context"]
            label   = data["label"]
            mapping = data["mapping"]

    # If sequence mode, output result and exit
    if args.mode == "sequence":
        # Show sequences
        show_sequences(context, events, label, mapping, NO_EVENT=preprocessor.NO_EVENT)
        exit()

    ########################################################################
    #                         Set "auto" arguments                         #
    ########################################################################

    # Automatically set device argument
    if args.device == "auto":
        args.device = "cuda" if torch.cuda.is_available() else "cpu"

    # Automatically set the number of events to expect
    if args.events == "auto":
        args.events = len(mapping)
    else:
        args.events = int(args.events)

    # Cast tensors to device
    events  = events .to(args.device)
    context = context.to(args.device)

    ########################################################################
    #                          B. Context Builder                          #
    ########################################################################

    # Create ContextBuilder
    context_builder = ContextBuilder(
        input_size    = args.events,
        output_size   = args.events,
        hidden_size   = args.hidden,
        num_layers    = 1,
        max_length    = args.length,
        bidirectional = False,
        LSTM          = False,
    ).to(args.device)

    # Training mode
    if args.mode == "train":

        # Train the ContextBuilder
        context_builder.fit(
            X             = context,
            y             = events.reshape(-1, 1),
            epochs        = args.epochs,
            batch_size    = args.batch,
            learning_rate = 0.01,
            teach_ratio   = 0.5,
            verbose       = True,
        )

    # Save the builder, if necessary
    if args.save_builder:
        context_builder.save(args.save_builder)

    # Load the builder, if necessary
    if args.load_builder:
        context_builder = ContextBuilder.load(args.load_builder, args.device)

    ########################################################################
    #                            C. Interpreter                            #
    ########################################################################

    # Create Interpreter
    interpreter = Interpreter(
        context_builder = context_builder,
        features        = args.events,
        eps             = args.epsilon,
        min_samples     = args.min_samples,
        threshold       = args.confidence,
    )

    # Fit the interpreter using given data
    if args.mode == "train":

        # Fit the interpreter
        interpreter.fit(
            X          = context,
            y          = events.reshape(-1, 1),
            score      = torch.zeros((events.shape[0], 1), device=args.device) - 4,
            iterations = 100,
            batch_size = 1024,
            verbose    = True,
        )

    # Save the interpreter, if necessary
    if args.save_interpreter:
        interpreter.save(args.save_interpreter)

    # Load the interpreter, if necessary
    if args.load_interpreter:
        interpreter = Interpreter.load(
            args.load_interpreter,
            context_builder = context_builder
        )

    ########################################################################
    #                          D. Manual analysis                          #
    ########################################################################

    if args.mode == "manual":

        # Predict clusters using the interpreter
        pass

    ########################################################################
    #                      E. Semi-automatic analysis                      #
    ########################################################################

    if args.mode == "automatic":
        print("SEMI-AUTOMATIC mode")
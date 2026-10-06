# Number generator for practicing addition/subtraction with an abacus

The program will generate a series of positive or negative numbers while keeping the total always positive, and report the total of those numbers at the end of each loop.

## Setup

Create a python environment and install the requirements
```
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Applications use

### Options

General
- `--num-digits`/`-d` - number of digits each number generated should have
- `--variable-length` - if set, considered `num-digits` a maximum and will generate numbers with variable length
- `--num-numbers`/`-n` - number of numbers in each set to generate
- `--num-loop`/`-l` - number of number sets to generate
- `--pause-sec`/`-p` - seconds to pause between each number generated (can be a decimal)
- `--use-negatives` - if set, will generate also negative numbers (while always keeping intermediate totals positive)
- `--flash` - if set, shows each number full-screen in the largest digits that fit the terminal `pause-sec` seconds before it is replaced by the next one.

Voice control
- `--speed` - how fast the voice should speak ("slow", "medium", "fast", "chipmunk")
- `--simple` - if set, the voice will say each individual digit instead of the number as a whole (e.g. "one two" instead of "twelve")
- `--silent` - if set, no voice is used
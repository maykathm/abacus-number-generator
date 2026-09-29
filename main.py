#!/usr/bin/env python3

import argparse
import pyttsx3
import random
import sys
import time


def get_rate(speed):
    if speed == "chipmunk":
        return 220
    if speed == "fast":
        return 190
    if speed == "medium":
        return 150
    if speed == "slow":
        return 100


# Old engines must stay alive: espeak can still call back into them after runAndWait().
_engines = []


def speak(words, rate):
    engine = pyttsx3.Engine()
    _engines.append(engine)
    engine.setProperty('rate', rate)
    engine.say(words)
    engine.runAndWait()


def get_next_num(current_total, num_digits, use_negatives, variable_length):
    lower = 0
    upper = int("9" * num_digits)
    if not variable_length:
        lower = int("1" + "0" * (num_digits - 1))
    if use_negatives:
        lower_neg = int("-" + "9" * num_digits)
        if not variable_length:
            upper_neg = int("-1" + "0" * (num_digits - 1))
    while True:
        if use_negatives and random.randint(0, 1) == 0:
            num = random.randint(lower_neg, upper_neg)
        else:
            num = random.randint(lower, upper)
        if current_total + num >= 0:
            return num


def print_group(next_num, do_speak, num_numbers, pause_sec):
    total = 0
    for _ in range(num_numbers):
        num = next_num(total)
        print(num)
        do_speak("" if num >= 0 else "negative", num)
        time.sleep(pause_sec)
        total += num
    print("-----")
    print(total)
    do_speak("Total", total)


def main():
    parser = argparse.ArgumentParser("Number Generator", description="""
    Generates numbers for practicing addition and subtraction on an abacus. Unless --silent is specified, it will speak each number aloud.
    """)
    parser.add_argument("-d", "--num-digits", type=int, default=4, required=False, help="Number of digits each number should have")
    parser.add_argument("-n", "--num-numbers", type=int, default=5, required=False, help="How many numbers to generate for each set")
    parser.add_argument("-p", "--pause-sec", type=float, default=4, required=False, help="How many seconds to pause between numbers")
    parser.add_argument("-l", "--num-loop", type=int, default=10, required=False, help="How many sets of numbers to generate")
    parser.add_argument("--use-negatives", action="store_true", required=False, help="Whether or not to use negative numbers (the total will never become negative)")
    parser.add_argument("--speed", choices=["slow", "medium", "fast", "chipmunk"], required=False, help="How fast the voice should say the numbers")
    parser.add_argument("--simple", action="store_true", required=False, help='When this flag is present, the voice will say each digit individually as its own number (ex: "one one two" instead of "one hundred twelve")')
    parser.add_argument("--variable-length", action="store_true", required=False, help="When this flag is present, the number of digits will be variable up to num-digits")
    parser.add_argument("--silent", action="store_true", required=False, help="Turns off text to speech")
    args = parser.parse_args()

    if args.silent and (args.simple or args.speed):
        print("Cannot use --silent in combination with speech flags (--simple, --speed) as --silent turns off speech.", file=sys.stderr)
        sys.exit(1)

    if not args.speed:
        args.speed = "medium"

    print("------------------------------")
    def next_num(current_total):
        return get_next_num(current_total, args.num_digits, args.use_negatives, args.variable_length)
    
    rate = get_rate(args.speed)
    def do_speak(prefix, num):
        say = str(abs(num))
        if args.simple:
            say = " ".join(say)
        speak(prefix + " " + say, rate)

    speech_func = do_speak
    if args.silent:
        speech_func = lambda x, y: None
    
    for i in range(args.num_loop):
        print_group(next_num, speech_func, args.num_numbers, args.pause_sec)
        if i < args.num_loop - 1:
            print("Press enter to continue...")
            input()


if __name__ == '__main__':
    main()

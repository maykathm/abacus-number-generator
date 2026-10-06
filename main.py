#!/usr/bin/env python3

import argparse
import fcntl
import os
import pyttsx3
import random
import re
import select
import shutil
import struct
import subprocess
import sys
import termios
import tty
import time

from PIL import Image, ImageDraw, ImageFont

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame


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


FLASH_GAP_SEC = 0.15  # Brief blank between numbers so repeated values are still visible as new numbers.
FLASH_FG = (255, 255, 255)
FLASH_BG = (0, 0, 0)
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
]
SIXEL_SHADES = 8  # Grey levels used to anti-alias glyph edges when drawing with sixel graphics.
_font_path = None
# Set by detect_sixel() when the terminal can draw real pixel images; otherwise numbers are drawn with half blocks.
_sixel_cell_size = None


def find_font_path():
    global _font_path
    if _font_path is None:
        _font_path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), "")
        if not _font_path and shutil.which("fc-match"):
            result = subprocess.run(["fc-match", "-f", "%{file}", "sans:bold"], capture_output=True, text=True)
            _font_path = result.stdout.strip()
    return _font_path


def load_font(size):
    path = find_font_path()
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def fit_font(text, width, height):
    # Binary search for the largest font size whose rendered text fits in width x height pixels.
    lo, hi = 1, height * 2
    while lo < hi:
        mid = (lo + hi + 1) // 2
        left, top, right, bottom = load_font(mid).getbbox(text)
        if right - left <= width and bottom - top <= height:
            lo = mid
        else:
            hi = mid - 1
    return load_font(lo)


def shade(value):
    # Blend between background and foreground so glyph edges are anti-aliased.
    return tuple(b + (f - b) * value // 255 for f, b in zip(FLASH_FG, FLASH_BG))


def clear_screen():
    # Bright white on black using basic colour codes, which every terminal supports (unlike 24-bit colour).
    sys.stdout.write("\x1b[97;40m\x1b[2J\x1b[H")
    sys.stdout.flush()


def sextant_char(bits):
    """Returns the character whose 2x3 cell pattern matches bits (bit r * 2 + c is row r, column c)."""
    # The Unicode sextant block leaves out the patterns that already exist elsewhere.
    special = {0: " ", 21: "▌", 42: "▐", 63: "█"}
    if bits in special:
        return special[bits]
    return chr(0x1FB00 + bits - 1 - (bits > 21) - (bits > 42))


SEXTANTS = [sextant_char(bits) for bits in range(64)]
# Quadrant characters for each 2x2 cell pattern (bit r * 2 + c is row r, column c). These are standard
# block elements found in practically every monospace font, unlike sextants.
QUADRANTS = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"


def terminal_draws_sextants():
    """Whether the terminal is known to draw sextants itself rather than relying on the font, which often lacks them."""
    env = os.environ
    return bool(
        env.get("VTE_VERSION")  # GNOME Terminal, Ptyxis, Tilix and other VTE-based terminals
        or env.get("KITTY_WINDOW_ID")
        or env.get("WEZTERM_PANE")
        or env.get("KONSOLE_VERSION")
        or env.get("TERM_PROGRAM") == "ghostty"
        or env.get("TERM", "").startswith("foot")
    )


def detect_sixel():
    """Asks the terminal whether it supports sixel graphics and how big a character cell is in pixels."""
    global _sixel_cell_size
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return
    if os.environ.get("TMUX"):
        # tmux incorrectly reports sixel support
        result = subprocess.run(["tmux", "display-message", "-p", "#{client_termfeatures}"], capture_output=True, text=True)
        if "sixel" not in result.stdout.strip().split(","):
            return
    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    response = b""
    try:
        tty.setcbreak(fd)
        # Request the cell size in pixels and primary device attributes. Every terminal answers
        # the latter (ending in "c").
        sys.stdout.write("\x1b[16t\x1b[c")
        sys.stdout.flush()
        while not response.endswith(b"c"):
            ready, _, _ = select.select([fd], [], [], 1.0)
            if not ready:
                break
            response += os.read(fd, 1024)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)

    attributes = re.search(rb"\x1b\[\?([\d;]*)c", response)
    if not attributes or b"4" not in attributes.group(1).split(b";"):
        return
    cell = re.search(rb"\x1b\[6;(\d+);(\d+)t", response)
    if cell:
        cell_h, cell_w = map(int, cell.groups())
    else:
        # Fall back to the window's pixel size as reported by the kernel (zero if the terminal doesn't set it).
        rows, cols, xpix, ypix = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
        cell_w, cell_h = xpix // max(1, cols), ypix // max(1, rows)
    if cell_w > 0 and cell_h > 0:
        _sixel_cell_size = (cell_w, cell_h)


def render_text(text, width, height):
    font = fit_font(text, int(width * 0.95), int(height * 0.9))
    left, top, right, bottom = font.getbbox(text)
    image = Image.new("L", (width, height), 0)
    x = (width - (right - left)) // 2 - left
    y = (height - (bottom - top)) // 2 - top
    ImageDraw.Draw(image).text((x, y), text, fill=255, font=font)
    return image


def sixel_encode(image):
    width, height = image.size
    out = [f'\x1bP0;1;0q"1;1;{width};{height}']
    for k in range(1, SIXEL_SHADES + 1):
        r, g, b = (c * 100 // 255 for c in shade(255 * k // SIXEL_SHADES))
        out.append(f"#{k};2;{r};{g};{b}")
    # One 0/1 mask per grey level; level 0 is left transparent so the black background shows through.
    masks = [
        image.point(lambda v, k=k: 1 if (v * SIXEL_SHADES + 127) // 255 == k else 0).tobytes()
        for k in range(1, SIXEL_SHADES + 1)
    ]
    offset = int.from_bytes(b"?" * width, "big")
    for band_top in range(0, height, 6):
        band = []
        for k, mask in enumerate(masks, 1):
            # Each sixel character encodes a column of 6 pixels as bits. Treating a row of 0/1 bytes as one
            # big integer lets us build every column's value at once: shifting by i sets bit i in each byte,
            # and no byte ever exceeds 63, so there are no carries between columns.
            value = 0
            for i in range(min(6, height - band_top)):
                start = (band_top + i) * width
                value += int.from_bytes(mask[start:start + width], "big") << i
            if value == 0:
                continue
            chars = (value + offset).to_bytes(width, "big").rstrip(b"?")
            chars = re.sub(rb"(.)\1{3,}", lambda m: b"!%d%c" % (len(m.group(0)), m.group(1)[0]), chars)
            band.append(f"#{k}" + chars.decode() + "$")
        out.append("".join(band) + ("-" if band_top + 6 < height else ""))
    out.append("\x1b\\")
    return "".join(out)


def show_big(text, header="", footer=""):
    cols, rows = shutil.get_terminal_size()
    avail_rows = rows - 2  # Leave a line for the header and one for the footer.
    if cols < 4 or avail_rows < 2:
        # Terminal too small to draw anything useful; fall back to plain text.
        clear_screen()
        sys.stdout.write("\n".join([header, text, footer]))
        sys.stdout.flush()
        return

    if _sixel_cell_size:
        # Draw a real image at the terminal's pixel resolution, keeping one spare row so it never scrolls.
        cell_w, cell_h = _sixel_cell_size
        image = render_text(text, cols * cell_w, (avail_rows - 1) * cell_h)
        clear_screen()
        sys.stdout.write(header[:cols] + "\x1b[2;1H" + sixel_encode(image) + f"\x1b[{rows};1H" + footer[:cols])
        sys.stdout.flush()
        return

    # Without image support, draw with block characters that split each cell into a grid of on/off pixels:
    # 2x3 sextants where the terminal draws them properly, otherwise 2x2 quadrants. Those pixels aren't square
    # (cells are about twice as tall as wide), so render at a square-pixel resolution first and then squash
    # it down to the character grid.
    if terminal_draws_sextants():
        sub_rows, chars = 3, SEXTANTS
    else:
        sub_rows, chars = 2, QUADRANTS
    image = render_text(text, cols * 6, avail_rows * 12).resize((cols * 2, avail_rows * sub_rows), Image.BOX)
    pixels = image.load()

    out = [header[:cols]]
    for row in range(avail_rows):
        line = []
        for col in range(cols):
            bits = 0
            for r in range(sub_rows):
                for c in range(2):
                    if pixels[col * 2 + c, row * sub_rows + r] >= 128:
                        bits |= 1 << (r * 2 + c)
            line.append(chars[bits])
        out.append("".join(line))
    out.append(footer[:cols])
    clear_screen()
    sys.stdout.write("\n".join(out))
    sys.stdout.flush()


def show_centered(message):
    cols, rows = shutil.get_terminal_size()
    clear_screen()
    # Cursor positions are 1-based; place the message on the middle row, horizontally centred.
    row = rows // 2 + 1
    col = max(1, (cols - len(message)) // 2 + 1)
    sys.stdout.write(f"\x1b[{row};{col}H{message[:cols]}")
    sys.stdout.flush()


class WindowClosed(Exception):
    pass


class WindowDisplay:
    """Shows numbers in a full-screen window, where the font is drawn smoothly at the screen's real resolution."""

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.display.set_caption("Number Generator")
        pygame.mouse.set_visible(False)
        width, height = self.screen.get_size()
        self.small_font = self.load_font(max(16, height // 30))

    def close(self):
        pygame.quit()

    def load_font(self, size):
        return pygame.font.Font(find_font_path() or None, size)

    def check_events(self, keys=()):
        """Returns True if one of keys was pressed; raises WindowClosed if the window is closed or Esc pressed."""
        pressed = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                raise WindowClosed()
            if event.type == pygame.KEYDOWN and event.key in keys:
                pressed = True
        return pressed

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check_events()
            time.sleep(0.01)

    def wait_for_enter(self):
        while not self.check_events(keys=(pygame.K_RETURN, pygame.K_KP_ENTER)):
            time.sleep(0.01)

    def blit_small(self, text, centered_x, y):
        surface = self.small_font.render(text, True, FLASH_FG)
        width = self.screen.get_width()
        x = (width - surface.get_width()) // 2 if centered_x else self.small_font.get_height() // 2
        self.screen.blit(surface, (x, y))

    def show(self, text="", header="", footer="", big=True):
        width, height = self.screen.get_size()
        self.screen.fill(FLASH_BG)
        margin = self.small_font.get_height() // 2
        if header:
            self.blit_small(header, False, margin)
        if footer:
            self.blit_small(footer, True, height - self.small_font.get_height() - margin)
        if text and not big:
            self.blit_small(text, True, (height - self.small_font.get_height()) // 2)
        elif text:
            # Text scales linearly with font size, so measure the drawn digits at a reference size and
            # scale up to fill the screen, leaving room for the header and footer.
            reference = 100
            bounds = self.load_font(reference).render(text, True, FLASH_FG).get_bounding_rect()
            size = int(reference * min(width * 0.95 / bounds.width, (height - 6 * margin) * 0.9 / bounds.height))
            surface = self.load_font(size).render(text, True, FLASH_FG)
            # Centre the digits themselves rather than the font's line box, which includes space for descenders.
            bounds = surface.get_bounding_rect()
            self.screen.blit(surface, ((width - bounds.width) // 2 - bounds.x, (height - bounds.height) // 2 - bounds.y))
        pygame.display.flip()
        self.check_events()

    def show_number(self, text, header="", footer=""):
        self.show(text, header, footer)

    def show_message(self, message):
        self.show(message, big=False)

    def blank(self):
        self.show()


class TerminalDisplay:
    """Draws numbers in the terminal, for when a window can't be opened (for example over SSH)."""

    def __init__(self):
        detect_sixel()
        # Use the terminal's alternate screen with a hidden cursor, restoring both on close.
        sys.stdout.write("\x1b[?1049h\x1b[?25l")

    def close(self):
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()

    def show_number(self, text, header="", footer=""):
        show_big(text, header, footer)

    def show_message(self, message):
        show_centered(message)

    def blank(self):
        clear_screen()

    def wait(self, seconds):
        time.sleep(seconds)

    def wait_for_enter(self):
        input()


def flash_group(display, next_num, do_speak, num_numbers, flash_sec, footer):
    total = 0
    for i in range(num_numbers):
        num = next_num(total)
        display.show_number(str(num), header=f"{i + 1}/{num_numbers}")
        do_speak("" if num >= 0 else "negative", num)
        display.wait(flash_sec)
        display.blank()
        display.wait(FLASH_GAP_SEC)
        total += num
    display.show_message("Press enter to show total")
    display.wait_for_enter()
    display.show_number(str(total), header="Total", footer=footer)
    do_speak("Total", total)


def run_flash(next_num, speech_func, args):
    try:
        display = WindowDisplay()
    except pygame.error as e:
        print(f"Could not open a window ({e}), showing numbers in the terminal instead.", file=sys.stderr)
        pygame.quit()
        display = TerminalDisplay()
    try:
        for i in range(args.num_loop):
            last = i == args.num_loop - 1
            footer = "Press enter to exit..." if last else "Press enter to continue..."
            flash_group(display, next_num, speech_func, args.num_numbers, args.pause_sec, footer)
            display.wait_for_enter()
    except (KeyboardInterrupt, EOFError, WindowClosed):
        pass
    finally:
        display.close()


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
    parser.add_argument("--flash", action="store_true", required=False, help="Show each number in large digits in a full-screen window for --pause-sec seconds (Enter continues, Esc quits)")
    parser.add_argument("--speak", action="store_true", required=False, help="Turns on text to speech")
    args = parser.parse_args()

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
    if not args.speak:
        speech_func = lambda x, y: None
    
    if args.flash:
        run_flash(next_num, speech_func, args)
        return

    for i in range(args.num_loop):
        print_group(next_num, speech_func, args.num_numbers, args.pause_sec)
        if i < args.num_loop - 1:
            print("Press enter to continue...")
            input()


if __name__ == '__main__':
    main()

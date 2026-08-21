"""Single-keystroke input for the menu, including the arrow keys and the mouse.

Reading one key at a time means leaving the terminal's cooked mode, and a
program that does that owes the user one guarantee above all: the terminal is
handed back exactly as it was found, whatever happens in between. Every path
out of `raw_mode` — normal return, exception, Ctrl-C, a `sys.exit` from deeper
in the menu — restores the saved attributes in a `finally`. Mouse tracking is
switched off in that same `finally`, for the same reason and with more at
stake: a terminal left in tracking mode spits escape sequences into the shell
on every pointer movement, and the user has no obvious way to stop it.

Arrow keys arrive as escape sequences (`ESC [ A`), which is the same byte that
starts a bare Escape press. They are told apart by waiting a few milliseconds
for a follow-up byte: a real arrow key sends its whole sequence at once, a
human pressing Escape does not.

Mouse reports arrive in the same shape and are decoded into a `Mouse` object
rather than a key name, so callers can tell a click from a keypress without
parsing anything themselves.

Nothing here requires a terminal to be *tested*: `read_key` takes any object
with `read(n)` and a `fileno`, and `FakeKeys` supplies a scripted sequence, so
the menu's navigation can be exercised in a self-check with no TTY at all.
"""

import os
import re
import select
import sys
from contextlib import contextmanager

try:                                        # absent on Windows; the menu then
    import termios                          # falls back to line input
    import tty
    HAVE_TERMIOS = True
except ImportError:                         # pragma: no cover - not our target
    HAVE_TERMIOS = False

# How long to wait for the rest of an escape sequence. Long enough for a slow
# terminal to deliver `[A`, short enough that a real Escape press is not felt
# as a delay.
ESC_TIMEOUT = 0.05

ARROWS = {'A': 'up', 'B': 'down', 'C': 'right', 'D': 'left',
          'H': 'home', 'F': 'end'}

# A held modifier turns `ESC [ C` into `ESC [ 1 ; 5 C`, where the number is a
# bitmask over shift, alt and control offset by one. Reported as a prefix on
# the key name — `ctrl-right` — because a screen that wants a bigger step from
# a held key needs to know that it was held, and one that does not can go on
# matching the bare name.
MODIFIERS = {2: 'shift-', 3: 'alt-', 4: 'shift-alt-', 5: 'ctrl-',
             6: 'shift-ctrl-', 7: 'alt-ctrl-', 8: 'shift-alt-ctrl-'}

MODIFIED_ARROW = re.compile(r'^1;(\d+)([A-DHF])$')

# `?1000` reports button presses and releases only — no motion, which is all a
# menu needs and the quietest thing to ask a terminal for. `?1006` switches the
# reports to SGR encoding; without it columns past 223 are unreportable,
# because the legacy format packs each coordinate into a single byte.
MOUSE_ON = '\x1b[?1000h\x1b[?1006h'
MOUSE_OFF = '\x1b[?1006l\x1b[?1000l'

# ESC [ < button ; column ; row (M press | m release)
SGR_REPORT = re.compile(r'^<(\d+);(\d+);(\d+)([Mm])$')


class Mouse:
    """A decoded mouse report.

    `row` and `col` are **zero-based**, converted from the one-based numbers
    the terminal sends, because every consumer here indexes a list of rendered
    lines and an off-by-one there is invisible until someone clicks the wrong
    row.
    """

    __slots__ = ('button', 'col', 'row', 'pressed')

    def __init__(self, button: int, col: int, row: int, pressed: bool):
        self.button = button
        self.col = col
        self.row = row
        self.pressed = pressed

    # Bits 2-4 of the button code carry shift, meta and ctrl; bit 6 marks a
    # wheel event. The plain button number is therefore the low two bits.
    @property
    def is_wheel(self) -> bool:
        return bool(self.button & 64)

    @property
    def wheel_up(self) -> bool:
        return self.is_wheel and (self.button & 3) == 0

    @property
    def wheel_down(self) -> bool:
        return self.is_wheel and (self.button & 3) == 1

    @property
    def is_left(self) -> bool:
        return not self.is_wheel and (self.button & 3) == 0

    def __repr__(self) -> str:               # pragma: no cover - diagnostics
        return (f'Mouse(button={self.button}, col={self.col}, '
                f'row={self.row}, pressed={self.pressed})')

    def __eq__(self, other) -> bool:
        return (isinstance(other, Mouse)
                and (self.button, self.col, self.row, self.pressed)
                == (other.button, other.col, other.row, other.pressed))


def sgr(button: int, col: int, row: int, press: bool = False) -> str:
    """The bytes a terminal would send for one report — for tests.

    Takes zero-based coordinates and emits the one-based wire form, so a test
    can be written in the same numbers the menu thinks in.
    """
    return f'\x1b[<{button};{col + 1};{row + 1}{"M" if press else "m"}'


@contextmanager
def raw_mode(stream=None, mouse: bool = False):
    """Put the terminal in cbreak mode, optionally reporting mouse clicks.

    Tracking is enabled and disabled inside the same try/finally as the
    terminal attributes, so there is exactly one place where the terminal is
    handed back and no way to leave tracking on by taking an unexpected exit.
    The attribute restore runs last and unconditionally: even if writing the
    disable sequence fails, the shell gets its echo back.
    """
    stream = stream or sys.stdin
    if not HAVE_TERMIOS or not stream.isatty():
        yield False
        return
    fd = stream.fileno()
    saved = termios.tcgetattr(fd)
    # Only ask for reports when they can actually be written somewhere the
    # terminal will read them; with stdout redirected the codes would land in
    # the pipe instead.
    # Tracking is off unless KIMICODEMODS_MOUSE=1 asks for it. With tracking on
    # the terminal hands clicks to the menu, which costs the thing a terminal
    # is for: a drag selects nothing and no text can be copied out of the
    # screen. Reading what a patch run said is worth more than clicking a row
    # that the arrow keys already reach, so the pointer belongs to the
    # terminal by default and the menu stays keyboard-driven.
    tracking = (bool(mouse) and sys.stdout.isatty()
                and os.environ.get('KIMICODEMODS_MOUSE', '0') in ('1', 'on'))
    try:
        # TCSANOW, not the TCSAFLUSH that `tty.setcbreak` uses by default.
        # Flushing discards whatever is already in the input queue, and this
        # mode is entered once per keystroke — so anything typed while the
        # previous key was being handled is thrown away. Two arrows pressed
        # quickly become one, which is exactly how a menu is used.
        tty.setcbreak(fd, termios.TCSANOW)
        if tracking:
            sys.stdout.write(MOUSE_ON)
            sys.stdout.flush()
        yield True
    finally:
        if tracking:
            try:
                sys.stdout.write(MOUSE_OFF)
                sys.stdout.flush()
            except Exception:               # pragma: no cover - closed stdout
                pass
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def drain_input(stream=None) -> None:
    """Throw away whatever was typed while something else held the terminal.

    A long-running command runs in cooked mode with echo on, so keys pressed
    while it works are echoed into its output and then left in the input queue.
    Coming back to the menu, those bytes read as navigation: three impatient
    arrows move the cursor three rows and a stray Return opens whatever they
    landed on. Nothing typed at a command that was not listening is worth
    keeping, so the queue is emptied before the menu reads again.

    This is the opposite call from `raw_mode`'s deliberate `TCSANOW`, and for
    the opposite reason: there, the keys were meant for the menu.
    """
    stream = stream or sys.stdin
    if not HAVE_TERMIOS or not stream.isatty():
        return
    try:
        termios.tcflush(stream.fileno(), termios.TCIFLUSH)
    except (termios.error, ValueError):     # pragma: no cover - closed stdin
        pass


class _FdStream:
    """Reads straight from a descriptor, with nothing buffered in between.

    This exists because of one bug, and it is worth stating plainly since the
    symptom pointed nowhere near the cause: every arrow key closed the menu.

    A terminal sends `ESC [ A` in a single write. `sys.stdin` is a buffered
    `TextIOWrapper`, so `read(1)` pulls all three bytes into Python's buffer
    and hands back the `ESC`. The escape decoder then asks whether more is on
    the way — by calling `select` on the **file descriptor**, which is empty,
    because the rest is sitting in Python's buffer where `select` cannot see
    it. So a bare Escape is reported, and `esc` means "leave this screen".

    Reading through `os.read` puts the bytes back where `select` is looking.
    The two have to agree about where the data is; buffering on one side and
    polling on the other is the whole defect.

    UTF-8 is decoded here rather than by a text wrapper, because a wrapper is
    exactly what must not sit in front of this.
    """

    __slots__ = ('fd',)

    def __init__(self, fd: int):
        self.fd = fd

    def fileno(self) -> int:
        return self.fd

    def read(self, _n: int = 1) -> str:
        try:
            first = os.read(self.fd, 1)
        except OSError:
            return ''
        if not first:
            return ''
        byte = first[0]
        if byte < 0x80:
            return chr(byte)
        # A leading byte says how many continuation bytes follow. Reading them
        # now keeps a typed umlaut from arriving as two unusable halves.
        length = 2 if byte >> 5 == 0b110 else 3 if byte >> 4 == 0b1110 else \
            4 if byte >> 3 == 0b11110 else 1
        buf = bytearray(first)
        for _ in range(length - 1):
            try:
                more = os.read(self.fd, 1)
            except OSError:
                break
            if not more:
                break
            buf += more
        return buf.decode('utf-8', 'replace')


def _unbuffered(stream):
    """The same stream, read without a buffer in front of it.

    A test source answers `has_pending` for itself and is handed back
    untouched; anything with a real descriptor is wrapped. Wrapping is what
    makes `select` the authority on whether more bytes are coming.
    """
    if stream is None:
        stream = sys.stdin
    if isinstance(stream, _FdStream) or getattr(stream, 'has_pending', None) is not None:
        return stream
    try:
        return _FdStream(stream.fileno())
    except (AttributeError, ValueError, OSError):
        return stream


def _waiting(stream, timeout=ESC_TIMEOUT) -> bool:
    """Is another byte already on its way?

    A stream may answer for itself via `has_pending()`; that is how the test
    source works, and it keeps `select` — which needs a real file descriptor —
    out of the picture there. Anything else is asked the usual way.
    """
    pending = getattr(stream, 'has_pending', None)
    if pending is not None:
        return pending()
    try:
        r, _, _ = select.select([stream], [], [], timeout)
        return bool(r)
    except (OSError, ValueError):
        return False


def _read_sequence(stream) -> str:
    """The body of an escape sequence, after the introducing `[` or `O`."""
    seq = ''
    while True:
        c = stream.read(1)
        if c == '':
            break
        seq += c
        if seq[0] == '<':
            # A mouse report ends in M or m and carries three numbers, so it
            # is both longer than the ordinary sequences and differently
            # terminated. `<64;1024;768M` is 13 characters.
            if c in ('M', 'm') or len(seq) > 24:
                break
        elif c.isalpha() or c == '~' or len(seq) > 8:
            break
    return seq


def _parse_sgr(seq: str):
    m = SGR_REPORT.match(seq)
    if not m:
        return None
    button, col, row, final = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    return Mouse(button, col - 1, row - 1, final == 'M')


def key_ready(stream=None, timeout: float = 0.0) -> bool:
    """Is there a keypress waiting, within `timeout` seconds?

    Lets a caller wait for input *and* get on with something else — the menu
    turns the moon in its header on the timeouts. `read_key` still does the
    reading; this only answers whether calling it would block.
    """
    return _waiting(_unbuffered(stream), timeout)


def read_key(stream=None):
    """One keypress or mouse click.

    Returns `up`, `down`, `left`, `right`, `home`, `end`, `enter`, `esc`,
    `backspace`, `tab`, `ctrl-c`, `eof`, the literal character — or a `Mouse`
    for a click or a wheel step.

    Clicks are reported on **release**. The press is swallowed, which keeps the
    two halves of one click from arriving as two events, and a release on a
    different row than the press is dropped as a drag rather than acted on.
    """
    stream = _unbuffered(stream)
    press_row = None
    while True:
        ch = stream.read(1)
        if ch == '':
            return 'eof'
        if ch == '\x03':
            return 'ctrl-c'
        if ch in ('\r', '\n'):
            return 'enter'
        if ch == '\t':
            return 'tab'
        if ch in ('\x7f', '\b'):
            return 'backspace'
        if ch != '\x1b':
            return ch

        # An escape byte: arrow key, mouse report, or the Escape key on its own.
        if not _waiting(stream):
            return 'esc'
        nxt = stream.read(1)
        if nxt not in ('[', 'O'):
            return 'esc'
        seq = _read_sequence(stream)

        if seq[:1] == '<':
            ev = _parse_sgr(seq)
            if ev is None:
                continue                    # malformed; ignore rather than act
            if ev.is_wheel:
                return ev                   # the wheel sends no release
            if ev.pressed:
                press_row = ev.row
                continue
            if press_row is not None and press_row != ev.row:
                press_row = None            # dragged across rows: not a click
                continue
            press_row = None
            return ev

        mod = MODIFIED_ARROW.match(seq)
        if mod is not None:
            return MODIFIERS.get(int(mod.group(1)), '') + ARROWS[mod.group(2)]
        if seq and seq[-1] in ARROWS:
            return ARROWS[seq[-1]]
        if seq == '5~':
            return 'pageup'
        if seq == '6~':
            return 'pagedown'
        return 'esc'


class FakeKeys:
    """A scripted key source, so navigation can be tested without a terminal.

    Accepts key *names* (`'down'`) as well as raw characters, and turns them
    back into the bytes a terminal would send, so `read_key` itself is what is
    being exercised rather than a stand-in for it. Mouse reports go in as raw
    strings, most readably via `sgr()`.
    """

    ENCODE = {'up': '\x1b[A', 'down': '\x1b[B', 'right': '\x1b[C',
              'left': '\x1b[D', 'home': '\x1b[H', 'end': '\x1b[F',
              'enter': '\r', 'esc': '\x1b', 'tab': '\t',
              'backspace': '\x7f', 'ctrl-c': '\x03',
              'shift-right': '\x1b[1;2C', 'shift-left': '\x1b[1;2D',
              'ctrl-right': '\x1b[1;5C', 'ctrl-left': '\x1b[1;5D'}

    def __init__(self, keys):
        self.buf = ''.join(self.ENCODE.get(k, k) for k in keys)
        self.pos = 0

    def read(self, n=1) -> str:
        out = self.buf[self.pos:self.pos + n]
        self.pos += len(out)
        return out

    def isatty(self) -> bool:
        return False

    def has_pending(self) -> bool:
        """Whatever is left in the script counts as already delivered."""
        return self.pos < len(self.buf)

    def fileno(self) -> int:                # pragma: no cover - never selected
        raise OSError('fake stream has no fd')

    @property
    def exhausted(self) -> bool:
        return self.pos >= len(self.buf)


def _selfcheck() -> int:
    cases = [
        (['up'], 'up'), (['down'], 'down'), (['left'], 'left'),
        (['right'], 'right'), (['enter'], 'enter'), (['tab'], 'tab'),
        # A held modifier is reported as a prefix, so a screen that wants a
        # bigger step from a held key can tell, and one that does not goes on
        # matching the bare name.
        (['shift-right'], 'shift-right'), (['shift-left'], 'shift-left'),
        (['ctrl-right'], 'ctrl-right'), (['\x1b[1;3D'], 'alt-left'),
        (['\x1b[1;6C'], 'shift-ctrl-right'),
        # An unknown modifier number keeps the key and drops the prefix,
        # rather than reporting a key nobody handles.
        (['\x1b[1;99C'], 'right'),
        (['q'], 'q'), (['ctrl-c'], 'ctrl-c'), (['backspace'], 'backspace'),
        (['esc'], 'esc'),
    ]
    for keys, want in cases:
        got = read_key(FakeKeys(keys))
        assert got == want, f'{keys} -> {got!r}, wanted {want!r}'

    # A sequence is consumed one key at a time, in order.
    src = FakeKeys(['down', 'down', 'enter', 'q'])
    assert [read_key(src) for _ in range(4)] == ['down', 'down', 'enter', 'q']

    # An exhausted stream reports EOF rather than blocking or looping.
    assert read_key(FakeKeys([])) == 'eof'

    # raw_mode is a no-op on a non-tty and must not raise.
    with raw_mode(FakeKeys([])) as active:
        assert active is False
    with raw_mode(FakeKeys([]), mouse=True) as active:
        assert active is False

    # -- mouse decoding ----------------------------------------------------

    ev = read_key(FakeKeys([sgr(0, 9, 4)]))
    assert isinstance(ev, Mouse), ev
    assert (ev.col, ev.row, ev.pressed) == (9, 4, False), ev
    assert ev.is_left and not ev.is_wheel

    # Multi-digit coordinates survive the length guard that trims ordinary
    # sequences at eight characters.
    ev = read_key(FakeKeys([sgr(0, 119, 44)]))
    assert (ev.col, ev.row) == (119, 44), ev

    # Both terminators decode; the press half of a click is swallowed so one
    # click is one event.
    src = FakeKeys([sgr(0, 3, 7, press=True), sgr(0, 3, 7), 'q'])
    ev = read_key(src)
    assert isinstance(ev, Mouse) and ev.row == 7 and not ev.pressed, ev
    assert read_key(src) == 'q'

    # Pressing on one row and releasing on another is a drag, not a click.
    src = FakeKeys([sgr(0, 3, 7, press=True), sgr(0, 3, 12), 'x'])
    assert read_key(src) == 'x'

    # The wheel has no release event, so it is reported as it arrives.
    up = read_key(FakeKeys([sgr(64, 5, 5, press=True)]))
    assert isinstance(up, Mouse) and up.wheel_up and not up.wheel_down, up
    down = read_key(FakeKeys([sgr(65, 5, 5, press=True)]))
    assert down.wheel_down and not down.wheel_up, down

    # A modifier set alongside the button must not hide which button it was:
    # 4 is shift, so 4 = shift+left.
    shift_left = read_key(FakeKeys([sgr(4, 2, 2)]))
    assert shift_left.is_left, shift_left

    # Right and middle are distinguishable from left.
    assert not read_key(FakeKeys([sgr(2, 2, 2)])).is_left

    # A malformed report is skipped rather than mistaken for a key.
    assert read_key(FakeKeys(['\x1b[<0;bogus;1m', 'k'])) == 'k'

    # Keys and clicks interleave in one stream.
    src = FakeKeys(['down', sgr(0, 1, 3), 'enter'])
    got = [read_key(src) for _ in range(3)]
    assert got[0] == 'down' and isinstance(got[1], Mouse) and got[2] == 'enter', got

    # -- over a real descriptor, which is the only way this bug shows ------
    #
    # `FakeKeys` answers `has_pending` for itself, so every case above skips
    # `select` entirely. That is exactly the path a terminal does *not* take,
    # and it hid a defect that made every arrow key close the menu: a terminal
    # writes `ESC [ A` at once, a buffered reader swallows all three bytes and
    # returns the ESC, and `select` on the descriptor then reports nothing
    # pending — because the rest is in Python's buffer, not in the kernel's.
    #
    # The cases below are written the way a terminal sends them: whole
    # sequences, in one write, read through an ordinary buffered stream. They
    # fail on the buffered reader and pass on the unbuffered one.
    import io

    def over_a_pipe(raw: bytes):
        r, w = os.pipe()
        os.write(w, raw)
        stream = io.TextIOWrapper(io.open(r, 'rb'))
        try:
            return read_key(stream)
        finally:
            # Held until here on purpose: a temporary is collected mid-call
            # and closes the descriptor under the reader, which reports EOF
            # and looks exactly like the bug this is testing for.
            os.close(w)
            stream.close()

    for raw, want in ((b'\x1b[A', 'up'), (b'\x1b[B', 'down'),
                      (b'\x1b[C', 'right'), (b'\x1b[D', 'left'),
                      (b'\x1b[H', 'home'), (b'\x1b[F', 'end'),
                      (b'\r', 'enter'), (b'q', 'q')):
        got = over_a_pipe(raw)
        assert got == want, f'{raw!r} over a descriptor -> {got!r}, wanted {want!r}'

    # A lone Escape still has to read as Escape, or leaving a screen breaks.
    assert over_a_pipe(b'\x1b') == 'esc', over_a_pipe(b'\x1b')

    # A click arrives as press and release in one write, like a terminal sends
    # it, and still resolves to one event.
    click = over_a_pipe(b'\x1b[<0;6;9M\x1b[<0;6;9m')
    assert isinstance(click, Mouse) and (click.col, click.row) == (5, 8), click

    # A multi-byte character survives being read one byte at a time.
    assert over_a_pipe('ü'.encode()) == 'ü', repr(over_a_pipe('ü'.encode()))

    # Dropping the input queue is a no-op on anything that is not a terminal,
    # which is how it behaves in a pipeline and in this selfcheck.
    with open(os.devnull) as devnull:
        drain_input(devnull)

    print('keyreader selfcheck: ok')
    return 0


if __name__ == '__main__':
    sys.exit(_selfcheck())

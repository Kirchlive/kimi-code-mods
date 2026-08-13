"""Single-keystroke input for the menu, including the arrow keys.

Reading one key at a time means leaving the terminal's cooked mode, and a
program that does that owes the user one guarantee above all: the terminal is
handed back exactly as it was found, whatever happens in between. Every path
out of `raw_mode` — normal return, exception, Ctrl-C, a `sys.exit` from deeper
in the menu — restores the saved attributes in a `finally`.

Arrow keys arrive as escape sequences (`ESC [ A`), which is the same byte that
starts a bare Escape press. They are told apart by waiting a few milliseconds
for a follow-up byte: a real arrow key sends its whole sequence at once, a
human pressing Escape does not.

Nothing here requires a terminal to be *tested*: `read_key` takes any object
with `read(n)` and a `fileno`, and `FakeKeys` supplies a scripted sequence, so
the menu's navigation can be exercised in a self-check with no TTY at all.
"""

import os
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


@contextmanager
def raw_mode(stream=None):
    """Put the terminal in cbreak mode for the duration of the block."""
    stream = stream or sys.stdin
    if not HAVE_TERMIOS or not stream.isatty():
        yield False
        return
    fd = stream.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield True
    finally:
        # Unconditional: an exception, Ctrl-C or SystemExit must not leave the
        # shell without echo.
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


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


def read_key(stream=None) -> str:
    """One keypress, as a name.

    Returns `up`, `down`, `left`, `right`, `home`, `end`, `enter`, `esc`,
    `backspace`, `tab`, `ctrl-c`, `eof`, or the literal character.
    """
    stream = stream or sys.stdin
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

    # An escape byte: arrow key, or the Escape key on its own.
    if not _waiting(stream):
        return 'esc'
    nxt = stream.read(1)
    if nxt not in ('[', 'O'):
        return 'esc'
    seq = ''
    while True:
        c = stream.read(1)
        if c == '':
            break
        seq += c
        if c.isalpha() or c == '~':
            break
        if len(seq) > 8:                    # malformed; give up rather than spin
            break
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
    being exercised rather than a stand-in for it.
    """

    ENCODE = {'up': '\x1b[A', 'down': '\x1b[B', 'right': '\x1b[C',
              'left': '\x1b[D', 'home': '\x1b[H', 'end': '\x1b[F',
              'enter': '\r', 'esc': '\x1b', 'tab': '\t',
              'backspace': '\x7f', 'ctrl-c': '\x03'}

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

    print('keyreader selfcheck: ok')
    return 0


if __name__ == '__main__':
    sys.exit(_selfcheck())

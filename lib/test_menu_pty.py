#!/usr/bin/env python3
"""Drive a menu through a real pseudo-terminal.

    python3 lib/test_menu_pty.py

Every other test here scripts the keyboard with `FakeKeys`, which answers
`has_pending` for itself and therefore never touches `select`. That is the one
path a terminal does not take, and it hid a defect that made the menu unusable
while every check stayed green: a terminal writes `ESC [ A` in a single write,
a buffered reader swallows all three bytes and returns the `ESC`, `select` on
the descriptor then sees nothing left — so an arrow key was read as Escape,
and Escape leaves the screen. Every arrow press closed the menu.

The only way to catch that is a real descriptor with a real terminal on the
other end, so this forks a pty, runs a small menu inside it, and types.

It runs against `menu.py` rather than the real one on purpose: the tweakkimi
menu shells out to `kimi-patch.sh --status`, which hashes 180 MB before it
draws anything. What is under test is the keyboard reaching the loop, and that
is the same code either way.
"""

import os
import pty
import re
import select
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import menu                                                  # noqa: E402

# The menu run inside the pty. Kept as source rather than a fixture file so
# the whole test is one thing to read.
CHILD = '''
import sys
sys.path.insert(0, {here!r})
import menu as m
from menu import Item, Screen

state = {{'colour': 'red', 'typed': '(nothing)'}}
CHOICES = ['red', 'green', 'blue']

def build(st):
    return [
        Item('action', 'Alpha', lambda s: 'first', key='a'),
        Item('action', 'Beta', lambda s: 'second', key='b'),
        Item('sep'),
        Item('cycle', 'Colour', lambda s: s['colour'], key='colour', choices=CHOICES),
        Item('action', 'Name', lambda s: s['typed'], key='name'),
        Item('action', 'Omega', lambda s: 'last', key='z'),
    ]

def cycle(st, item, forward):
    i = CHOICES.index(st['colour'])
    st['colour'] = CHOICES[(i + (1 if forward else -1)) % len(CHOICES)]

def activate(st, item):
    if item.key == 'name':
        got = m.field('Name', hint='type something')
        st['typed'] = '(escaped)' if got is None else repr(got)
    return True

m.loop(Screen(build, cycle=cycle, activate=activate, title='pty screen',
              help_line=m.HELP_ROOT), state)
'''

ANSI = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')


class Session:
    """A menu running under a pty, and the last screen it drew."""

    def __init__(self, source: str):
        self.buf = ''
        self.pid, self.fd = pty.fork()
        if self.pid == 0:                                   # pragma: no cover
            os.environ['TERM'] = 'xterm-256color'
            os.execv(sys.executable, [sys.executable, '-c', source])

    def settle(self, timeout: float = 5.0) -> None:
        """Read until the output stops arriving.

        Quiet is the signal rather than a fixed sleep: a redraw is one burst,
        and waiting for three empty polls after it is both faster and less
        flaky than guessing how long a draw takes.
        """
        end = time.time() + timeout
        quiet = 0
        while time.time() < end:
            ready, _, _ = select.select([self.fd], [], [], 0.15)
            if ready:
                try:
                    self.buf += os.read(self.fd, 65536).decode('utf-8', 'replace')
                except OSError:
                    return
                quiet = 0
            else:
                quiet += 1
                if quiet >= 3 and self.buf:
                    return

    def type(self, keys: bytes) -> None:
        os.write(self.fd, keys)
        self.settle()

    def cursor(self) -> str:
        """The row the cursor is on, in the screen drawn last."""
        last = ANSI.sub('', self.buf.split('\x1b[2J')[-1])
        for line in last.splitlines():
            if '❯' in line:
                return ' '.join(line.split())
        return '(no cursor drawn)'

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass


def main() -> int:
    passed = 0
    failed = []

    def check(name, cond, detail=''):
        nonlocal passed
        if cond:
            passed += 1
            print(f'  ok   {name}')
        else:
            failed.append(name)
            print(f'  FAIL {name}{"  — " + str(detail) if detail else ""}')

    print('menu through a pseudo-terminal:')
    s = Session(CHILD.format(here=str(HERE)))
    try:
        s.settle(10)
        check('the menu draws', '❯' in s.cursor(), s.cursor())
        check('it starts on the first row', 'Alpha' in s.cursor(), s.cursor())

        s.type(b'\x1b[B')
        check('down moves', 'Beta' in s.cursor(), s.cursor())

        # The row after Beta is a separator; navigation has to step over it.
        s.type(b'\x1b[B')
        check('down skips the separator', 'Colour' in s.cursor(), s.cursor())

        s.type(b'\x1b[A')
        check('up moves back', 'Beta' in s.cursor(), s.cursor())

        s.type(b'\x1b[F')
        check('end jumps to the last row', 'Omega' in s.cursor(), s.cursor())

        s.type(b'\x1b[H')
        check('home returns to the first', 'Alpha' in s.cursor(), s.cursor())

        # ‹› on a cycle row writes through and the redraw shows it.
        s.type(b'\x1b[B\x1b[B')
        check('the cycle row is reachable', 'Colour' in s.cursor(), s.cursor())
        s.type(b'\x1b[C')
        check('right advances the value', 'green' in s.cursor(), s.cursor())
        s.type(b'\x1b[D')
        check('left steps back', 'red' in s.cursor(), s.cursor())

        # A digit is still a shortcut.
        s.type(b'2')
        check('a digit selects a row', 'Beta' in s.cursor(), s.cursor())

        # And the one that matters most: an arrow must not be read as Escape.
        # If it were, the loop would have exited long before here and the
        # screen would have stopped redrawing.
        s.type(b'\x1b[B')
        check('the menu is still running after nine arrow keys',
              '❯' in s.cursor(), s.cursor())

        # The terminal's own cursor is hidden while a screen is up: with the
        # selected row already marked, a second block blinking under the last
        # line is only a distraction. Checked on the raw bytes, because this
        # is one of the few things a rendered screen cannot show.
        check('the terminal cursor is hidden while drawing',
              '\x1b[?25l' in s.buf)

        # Colour is decided by the caller, and only `draw` turns it on. This
        # is the one place that proves the real path does: a self-check that
        # renders without a terminal can only prove the opposite.
        check('the selected row is drawn in colour', '\x1b[1;36m' in s.buf)

        # The field, which is the whole reason `input()` is gone. Typing an
        # arrow key into it must leave no trace in the value: as a line reader
        # it arrived as \x1b[C inside the string, and that string was written
        # to config.toml, where the next parse threw on the escape byte.
        s.type(b'\x1b[B')                             # down to the Name row
        check('the field row is reachable', 'Name' in s.cursor(), s.cursor())
        s.type(b'\r')
        check('enter opens a bordered field', '╭' in s.buf.split('\x1b[2J')[-1])
        s.type(b'ab')
        s.type(b'\x1b[C\x1b[D\x1b[A')                 # arrows: navigation, not text
        s.type(b'c')
        s.type(b'\x7f')                               # backspace deletes one
        s.type(b'\r')
        check('the field returns what was typed', "'ab'" in s.cursor(), s.cursor())
        check('and no escape byte reached the value',
              '\\x1b' not in s.cursor() and '^[' not in s.cursor(), s.cursor())

        # The frame is drawn by columns, not by characters. An emoji is one
        # character and two columns, so a marker with one in it would push the
        # right edge out by one for every emoji typed.
        s.type(b'\r')
        s.type('✨🌕'.encode())
        drawn = ANSI.sub('', s.buf.split('\x1b[2J')[-1]).splitlines()
        frame = [l for l in drawn if l.startswith('  ╭') or l.startswith('  │')
                 or l.startswith('  ╰')]
        widths = {menu.visible(l) for l in frame}
        check('the field frame is square around a wide character',
              len(frame) == 3 and len(widths) == 1, (frame, widths))

        s.type(b'\x1b')                               # escape cancels outright
        check('escape leaves the value alone',
              '(escaped)' in s.cursor(), s.cursor())

        # Leaving has to give it back, or the shell you return to has no
        # cursor. Typing q ends the loop, whose `finally` shows it again.
        s.type(b'q')
        check('and shown again on the way out',
              s.buf.rstrip().endswith('\x1b[?25h'), repr(s.buf[-20:]))
    finally:
        s.close()

    print()
    if failed:
        print(f'{passed} passed, {len(failed)} FAILED.')
        return 1
    print(f'{passed} passed, 0 failed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

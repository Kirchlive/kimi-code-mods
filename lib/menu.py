"""One navigable screen, and the loop that drives it.

Every screen in tweakkimi is the same thing: a header, a list of rows, and a
help line. What differs is which rows and what they do. That is the whole
reason this module exists — the navigation was written once for the main menu
and every submenu underneath it then fell back to `input()` and digits, so the
arrow keys stopped working exactly where the user had just learned to use them.

A `Screen` supplies the parts that differ as callables; `loop` supplies the
parts that do not: arrow keys, wheel and click, home and end, digit shortcuts,
separators that navigation skips, and the guarantee that raw mode and mouse
tracking are switched off around anything a row runs.

`render` records which terminal line each row landed on while it is drawing.
That mapping is what makes a click land on the right row, and building it here
rather than reconstructing it afterwards is deliberate: here the answer is
`len(lines)` and cannot drift; afterwards it would mean counting header and
separator lines a second time, in a second place.

Nothing here needs a terminal to be tested. `handle` takes a decoded key or a
`Mouse`, and `keyreader.FakeKeys` scripts a sequence, so a screen's navigation
can be exercised without a TTY.
"""

import colorsys
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from keyreader import Mouse, raw_mode, read_key             # noqa: E402

CURSOR = '❯'                    # the tweakcc marker
RULE_WIDTH = 64
# Wide enough for the longest row label in the tree ('AGENTS.md alternative
# names'), so the value column never moves between screens.
LABEL_WIDTH = 30

# The terminal's own cursor has nothing to point at here — the selected row is
# marked by `CURSOR`, so a second block blinking under the last line is just a
# distraction. It is hidden as part of the drawing and shown again before
# anything that reads a line, which is the only rule that keeps the two in
# step: a screen is always drawn after an action, so hiding belongs there
# rather than at the top of the loop.
HIDE_CURSOR = '\x1b[?25l'
SHOW_CURSOR = '\x1b[?25h'

# tweakcc draws the row you are on in bold cyan and everything it says *about*
# that row dimmed. Worth copying exactly: the mark alone is one character wide
# and easy to lose on a full screen, and dimming the explanation stops it
# competing with the rows for attention.
SELECTED = '\x1b[1;36m'
DIM = '\x1b[2m'
RESET = '\x1b[0m'


def paint(text: str, style: str, on: bool) -> str:
    """`text` in `style`, or unchanged when colour is off.

    Whether it is on is decided by the caller rather than read from the
    terminal here, and `render` defaults it to off. Every self-check compares
    rendered lines against what it expects to read, and a check that passes
    or fails depending on whether the suite was run through a pipe is worse
    than no check at all.
    """
    return f'{style}{text}{RESET}' if text and on else text


# The one line at the bottom of every screen. A submenu adds "esc back",
# because that is the only key whose meaning differs between the two.
HELP_ROOT = '  ↑↓/wheel move · enter open · ‹› change · q quit'
HELP_SUB = '  ↑↓/wheel move · enter open · ‹› change · esc back'
HELP_DEL = '  ↑↓/wheel move · enter open · ‹› change · ⌫ remove · esc back'


class Item:
    """One row.

    `kind` decides what the arrow keys do:
      submenu  enter opens it
      cycle    left/right/enter step through `choices`, writing as they go
      action   enter runs it
      info     shown, never selected — a fact the screen wants to state
      sep      a rule, skipped by navigation
    """

    def __init__(self, kind, label='', value=lambda st: '', note=lambda st: '',
                 key='', choices=None, on_cycle=None, on_enter=None,
                 on_delete=None, help=''):
        self.kind = kind
        self.label = label
        self.value = value
        self.note = note
        self.key = key
        self.choices = choices or []
        self.on_cycle = on_cycle
        self.on_enter = on_enter
        # Backspace removes what the row stands for — a saved set, a hook, a
        # value handed back to Kimi. It used to be ‹›, which is the key that
        # *changes* a value everywhere else in this menu; a user stepping
        # through a list to look at it deleted an entry instead. One key, one
        # meaning, and the destructive one is the key that already means
        # "remove" on every keyboard.
        self.on_delete = on_delete
        self.help = help

    @property
    def selectable(self) -> bool:
        return self.kind not in ('sep', 'info')


class Screen:
    """What one screen contributes; `loop` contributes everything else.

    `build(st)` returns the rows. It is called again after every action, so a
    row's value is read from the file that owns it rather than remembered here
    — the same rule the rest of tweakkimi follows, and the reason a change made
    by an external editor shows up the moment you come back.

    `activate(st, item)` runs a row and returns False to close the screen.
    `cycle(st, item, forward)` advances a value and persists it.
    `reload(st)` returns the state to use after an action; the default keeps
    the one it was given, which is right for every screen whose rows read
    files directly.
    """

    def __init__(self, build, header=None, activate=None, cycle=None,
                 reload=None, delete=None, aside=None, help_line=HELP_SUB,
                 title=''):
        self.build = build
        self._header = header
        self._activate = activate
        self._cycle = cycle
        self._reload = reload
        self._delete = delete
        self._aside = aside
        self.help_line = help_line
        self.title = title

    def header(self, st) -> list[str]:
        # The title is indented by one to sit over the row labels, which start
        # at column two behind the cursor mark. Done here rather than in each
        # screen's title string, so no screen can be the one that forgets.
        if self._header is not None:
            return list(self._header(st))
        return ['', ' ' + self.title] if self.title else ['']

    def activate(self, st, item) -> bool:
        if item.on_enter is not None:
            return item.on_enter(st, item) is not False
        if self._activate is not None:
            return self._activate(st, item)
        return True

    def cycle(self, st, item, forward: bool) -> None:
        if item.on_cycle is not None:
            item.on_cycle(st, item, forward)
        elif self._cycle is not None:
            self._cycle(st, item, forward)

    def reload(self, st):
        return self._reload(st) if self._reload is not None else st

    def aside(self, st, selected=None) -> list[str]:
        """A preview drawn beside the rows, tweakcc's second column.

        A colour, a spinner and a message frame are things you judge by
        looking at them, and a list of names is not a substitute for that.
        Rows and preview are rendered together so the two cannot disagree
        about the state they are both describing.

        The selected row is handed over too, because a preview of nineteen
        palette tokens has to be able to say which one the cursor is on —
        otherwise it shows everything and answers nothing.
        """
        return list(self._aside(st, selected)) if self._aside is not None else []

    def delete(self, st, item) -> bool:
        """Remove what a row stands for. False when the row has nothing to remove."""
        if item.on_delete is not None:
            item.on_delete(st, item)
            return True
        if self._delete is not None:
            return self._delete(st, item) is not False
        return False


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def render(screen: Screen, st, items: list[Item], cursor: int,
           row_map: dict | None = None, color: bool = False,
           width: int | None = None) -> list[str]:
    """The screen as lines, recording which line each row landed on.

    A preview, when the screen has one, is appended to the same lines rather
    than printed separately: a click's row is an index into what was printed,
    so anything that adds lines has to go through here to be counted.
    """
    lines = list(screen.header(st))
    lines.append('')

    sel_row = items[cursor] if 0 <= cursor < len(items) else None
    for i, it in enumerate(items):
        if it.kind == 'sep':
            lines.append('  ' + '─' * RULE_WIDTH)
            continue
        if it.kind == 'info':
            lines.append(f'  {it.label}')
            continue
        mark = CURSOR if i == cursor else ' '
        value = it.value(st)
        note = it.note(st)
        if note:
            value = f'{value}   [{note}]' if value else f'[{note}]'
        arrows = ' ‹›' if (it.kind == 'cycle' or it.on_cycle) else '   '
        if row_map is not None:
            row_map[len(lines)] = i
        row = f'{mark} {it.label:<{LABEL_WIDTH}}{arrows} {value}'.rstrip()
        lines.append(paint(row, SELECTED, color) if i == cursor else row)

    # The preview goes beside the rows, and only the rows. The two lines that
    # follow — what the selected row is for, and the keys — are sentences, and
    # a sentence is what decides how wide the left column is if it is allowed
    # to. Left in, one long explanation would push a preview that fits
    # comfortably onto the line below the whole menu.
    lines = beside(lines, screen.aside(st, sel_row), width)

    lines.append('')
    sel = items[cursor] if 0 <= cursor < len(items) else None
    if sel is not None and sel.help:
        lines.append(paint(f'  {sel.help}', DIM, color))
        lines.append('')
    lines.append(paint(screen.help_line, DIM, color))
    return lines


ANSI = re.compile(r'\x1b\[[0-9;]*m')
ASIDE_GAP = 3


def visible(text: str) -> int:
    """How wide a line actually prints.

    Two things make this more than `len`. Colour codes take no columns at
    all, and a wide character — an emoji, a CJK glyph — takes two. Getting
    either wrong shifts the right-hand edge of a framed preview by exactly
    the number of them in the line, which is how a box ends up ragged.
    """
    plain = ANSI.sub('', text)
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
               for c in plain)


def terminal_width(fallback: int = 100) -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return fallback


def beside(lines: list[str], aside: list[str], width: int | None = None) -> list[str]:
    """Put `aside` to the right of `lines`, or under them when it will not fit.

    Two rules decide it, and both are about not making the screen worse than
    it was. The preview only goes beside the rows when the window is wide
    enough for both without wrapping — a wrapped line would occupy two
    terminal rows, and the mouse mapping counts one. And it never lengthens
    the block it is added to beyond what the rows already need, except where
    the preview itself is the taller of the two.
    """
    if not aside:
        return lines
    left = max((visible(l) for l in lines), default=0)
    right = max((visible(a) for a in aside), default=0)
    if width is None:
        width = terminal_width()
    if left + ASIDE_GAP + right > width:
        # Too narrow to sit beside: below, separated by a blank line, where it
        # costs height rather than correctness.
        return lines + [''] + aside

    out = []
    for i in range(max(len(lines), len(aside))):
        row = lines[i] if i < len(lines) else ''
        pad = ' ' * (left - visible(row) + ASIDE_GAP)
        extra = aside[i] if i < len(aside) else ''
        out.append((row + pad + extra).rstrip() if extra else row)
    return out


def draw(screen: Screen, st, items: list[Item], cursor: int) -> dict:
    """Paint the screen and return the line-to-row mapping for the mouse.

    Clear-and-home puts the first line at screen row 0, which is what makes the
    mapping usable directly: a click's zero-based row *is* an index into the
    list that was just printed. That holds as long as the screen fits the
    window; on a very short terminal the top scrolls away and clicks land off.
    """
    # `2J` clears the window, `3J` clears the scrollback behind it. Without
    # the second one a menu taller than the window leaves its previous drawing
    # above the current one: scroll up and there are two headers, which is
    # what it looks like when the same screen has been drawn twice. It has
    # not — the old one simply never went anywhere.
    sys.stdout.write('\x1b[3J\x1b[2J\x1b[H')
    if sys.stdout.isatty():
        sys.stdout.write(HIDE_CURSOR)
    row_map: dict[int, int] = {}
    print('\n'.join(render(screen, st, items, cursor, row_map,
                           color=sys.stdout.isatty(), width=terminal_width())))
    sys.stdout.flush()
    return row_map


def show_cursor() -> None:
    """Give the terminal cursor back before anything reads a line."""
    if sys.stdout.isatty():
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()


# --------------------------------------------------------------------------
# typed values
# --------------------------------------------------------------------------

FIELD_WIDTH = 46


def field(title: str, value: str = '', hint: str = '', width: int = FIELD_WIDTH):
    """Read one line in a bordered field, and return it — or None on escape.

    This exists because `input()` cannot be used here, and the reason is not
    stylistic. `input()` reads a line in cooked mode, so an arrow key pressed
    out of habit arrives as the three bytes of its escape sequence *inside the
    returned string*. That string was then written to `config.toml`, where
    `\\x1b` is not a legal character, and the next parse of the file threw —
    out of a menu that had already redrawn, with a traceback in place of the
    screen. Not hypothetical: that is how it crashed.

    Here every key arrives decoded. An arrow key is a key rather than text and
    is simply ignored, so it cannot reach the value; backspace deletes; enter
    accepts; escape returns None, which every caller reads as "nothing was
    entered" and leaves the setting alone.

    Without a terminal it returns None immediately rather than blocking, the
    same rule `loop` follows.
    """
    if not sys.stdin.isatty():
        return None
    text = value
    color = sys.stdout.isatty()
    inner = width - 2
    try:
        while True:
            sys.stdout.write('\x1b[3J\x1b[2J\x1b[H')
            if color:
                sys.stdout.write(HIDE_CURSOR)
            shown = text[-inner:] if len(text) > inner else text
            lines = ['', ' ' + title, '']
            if hint:
                lines += [paint('  ' + hint, DIM, color), '']
            lines += ['  ╭' + '─' * width + '╮',
                      '  │ ' + (shown + '▋').ljust(inner)[:inner] + ' │',
                      '  ╰' + '─' * width + '╯', '',
                      paint('  enter saves · backspace deletes · esc cancels',
                            DIM, color)]
            print('\n'.join(lines))
            sys.stdout.flush()

            with raw_mode():
                key = read_key()
            if key == 'enter':
                return text
            if key in ('esc', 'ctrl-c', 'eof'):
                return None
            if key == 'backspace':
                text = text[:-1]
                continue
            # Anything that is a key rather than a character is navigation,
            # and navigation has no meaning in a one-line field.
            if isinstance(key, Mouse) or len(key) != 1 or not key.isprintable():
                continue
            text += key
    finally:
        show_cursor()


# --------------------------------------------------------------------------
# colours
# --------------------------------------------------------------------------

BAR_WIDTH = 44


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """`#RRGGBB` as three numbers. Anything unreadable comes back mid-grey."""
    text = value.strip().lstrip('#')
    if len(text) == 3:                      # #abc is a convenience here only;
        text = ''.join(c * 2 for c in text)  # what gets written is always six
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (128, 128, 128)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return '#{:02x}{:02x}{:02x}'.format(max(0, min(255, int(round(r)))),
                                        max(0, min(255, int(round(g)))),
                                        max(0, min(255, int(round(b)))))


def rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Degrees and two percentages. `colorsys` speaks HLS, hence the swap."""
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return (h * 360, s * 100, l * 100)


def hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, l / 100, s / 100)
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def bg(r: int, g: int, b: int) -> str:
    return f'\x1b[48;2;{r};{g};{b}m'


def fg(r: int, g: int, b: int) -> str:
    return f'\x1b[38;2;{r};{g};{b}m'


def gradient(at_fraction, position: float, width: int = BAR_WIDTH) -> str:
    """A bar of colours with a marker on it.

    `at_fraction(f)` gives the colour at 0…1 along the bar, so one function
    draws hue, saturation, lightness and the three RGB channels without any of
    them knowing how a bar is drawn. The marker is a bar character in black or
    white, whichever the colour under it is further from, so it stays visible
    at both ends of a lightness ramp — the place a fixed marker colour
    disappears.
    """
    mark = max(0, min(width - 1, int(round(position * (width - 1)))))
    out = []
    for x in range(width):
        r, g, b = at_fraction(x / max(1, width - 1))
        if x == mark:
            light = (r * 299 + g * 587 + b * 114) / 1000
            ink = (0, 0, 0) if light > 140 else (255, 255, 255)
            out.append(f'{bg(r, g, b)}{fg(*ink)}│')
        else:
            out.append(f'{bg(r, g, b)} ')
    return ''.join(out) + RESET


CHANNELS = {
    'hsl': [('Hue', 360, '°'), ('Saturation', 100, '%'), ('Lightness', 100, '%')],
    'rgb': [('Red', 255, ''), ('Green', 255, ''), ('Blue', 255, '')],
}


def clipboard() -> str:
    """Whatever the system clipboard holds, or '' where there is no way to ask."""
    for cmd in (['pbpaste'], ['wl-paste', '-n'], ['xclip', '-selection', 'clipboard', '-o']):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0:
            return out.stdout.strip()
    return ''


# A hex colour lifted out of whatever the clipboard held — CSS, a JSON line, a
# chat message. Bounded on both sides by "not a hex digit" rather than by a
# word boundary: `deadbeef99` ends on one, and taking six digits out of the
# middle of a longer run would be a colour nobody copied.
HEX_ANYWHERE = re.compile(
    r'(?<![0-9a-fA-F])#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])')


def color(title: str, value: str = '#808080', hint: str = '', preview=None):
    """Pick a colour on three bars. Returns `#rrggbb`, or None if cancelled.

    A colour is the one setting that cannot be chosen from a list and should
    not be typed: six hex digits are a description of a colour, not the colour
    itself, and getting from the one you can see in your head to those digits
    is the whole difficulty. Three bars drawn *in* the colours they select
    turn it back into looking at something.

    HSL is the default because its three axes are the ones people actually
    reach for — a bit more blue, a bit less washed out, a bit darker. RGB is
    one keystroke away for when a value has to match something exact.

    `preview(hex)` supplies lines drawn beside the picker, so a palette token
    can show what it does to a mock transcript while it is being dragged.
    """
    if not sys.stdin.isatty():
        return None

    r, g, b = hex_to_rgb(value)
    h, s, l = rgb_to_hsl(r, g, b)
    mode, row = 'hsl', 0
    color_on = sys.stdout.isatty()

    def current() -> tuple[int, int, int]:
        return (int(round(r)), int(round(g)), int(round(b))) if mode == 'rgb' \
            else hsl_to_rgb(h, s, l)

    def channel_values() -> list[float]:
        return [r, g, b] if mode == 'rgb' else [h, s, l]

    def set_channel(i: int, v: float) -> None:
        nonlocal r, g, b, h, s, l
        limit = CHANNELS[mode][i][1]
        v = max(0.0, min(float(limit), v))
        if mode == 'rgb':
            r, g, b = [v if j == i else x for j, x in enumerate((r, g, b))]
            h, s, l = rgb_to_hsl(r, g, b)
        else:
            h, s, l = [v if j == i else x for j, x in enumerate((h, s, l))]
            r, g, b = hsl_to_rgb(h, s, l)

    def bar_for(i: int):
        """The colour at each point of one bar, with the others held still."""
        if mode == 'rgb':
            return lambda f: tuple(int(round(f * 255)) if j == i else int(round(x))
                                   for j, x in enumerate((r, g, b)))
        if i == 0:
            return lambda f: hsl_to_rgb(f * 360, s, l)
        if i == 1:
            return lambda f: hsl_to_rgb(h, f * 100, l)
        return lambda f: hsl_to_rgb(h, s, f * 100)

    try:
        while True:
            rr, gg, bb = current()
            hex_now = rgb_to_hex(rr, gg, bb)
            hh, ss, ll = rgb_to_hsl(rr, gg, bb)

            lines = ['', ' ' + title, '']
            if hint:
                lines += [paint('  ' + hint, DIM, color_on)]
            lines += [
                paint('  ←→ adjust · shift+←→ by ten · ↑↓ change bar', DIM, color_on),
                paint('  a switches rgb/hsl · p pastes · h types a hex value',
                      DIM, color_on),
                paint('  enter keeps it · esc leaves it as it was', DIM, color_on),
                '',
            ]
            for i, (name, limit, unit) in enumerate(CHANNELS[mode]):
                v = channel_values()[i]
                label = f'{name} ({int(round(v))}{unit})'
                mark = CURSOR if i == row else ' '
                bar = gradient(bar_for(i), v / limit, BAR_WIDTH) if color_on else ''
                lines.append(f'{mark} {label:<20} {bar}')
                lines.append('')

            swatch = f'{bg(rr, gg, bb)}      {RESET}' if color_on else '      '
            lines += [
                f'  Current: {swatch}',
                '',
                paint('  Hex        RGB                     HSL', DIM, color_on),
                f'  {hex_now}    rgb({rr}, {gg}, {bb})'.ljust(37)
                + f'hsl({int(round(hh))}, {int(round(ss))}%, {int(round(ll))}%)',
            ]

            body = beside(lines, list(preview(hex_now)) if preview else [],
                          terminal_width())
            sys.stdout.write('\x1b[3J\x1b[2J\x1b[H')
            sys.stdout.write(HIDE_CURSOR if color_on else '')
            print('\n'.join(body))
            sys.stdout.flush()

            with raw_mode():
                key = read_key()

            if key == 'enter':
                return hex_now
            if key in ('esc', 'ctrl-c', 'eof'):
                return None
            if key == 'up':
                row = (row - 1) % 3
            elif key == 'down':
                row = (row + 1) % 3
            elif key in ('left', 'right'):
                set_channel(row, channel_values()[row] + (1 if key == 'right' else -1))
            elif key.endswith('-left') or key.endswith('-right'):
                step = 10 if key.endswith('-right') else -10
                set_channel(row, channel_values()[row] + step)
            elif key == 'home':
                set_channel(row, 0)
            elif key == 'end':
                set_channel(row, CHANNELS[mode][row][1])
            elif key == 'a':
                mode = 'rgb' if mode == 'hsl' else 'hsl'
            elif key in ('p', 'h'):
                got = clipboard() if key == 'p' else field(
                    'Hex value', hex_now, hint='Six hex digits, with or without #.')
                found = HEX_ANYWHERE.search(got or '')
                if found:
                    r, g, b = hex_to_rgb(found.group(1))
                    h, s, l = rgb_to_hsl(r, g, b)
    finally:
        show_cursor()


def pick(title: str, options: list[str], hint: str = '', note=None):
    """Choose one of `options` on a screen of its own. `None` if cancelled.

    A list the program already holds has no business being typed. Every place
    that used to print a numbered list and read the number back — the twenty
    hook events, the models in a pool — is one of these instead, so the answer
    cannot be misspelled and there is nothing to validate afterwards.

    `note(option)` supplies the second column, where an option has more to say
    about itself than its name.
    """
    chosen = None

    def build(_st) -> list[Item]:
        rows: list[Item] = []
        if hint:
            rows += [Item('info', hint), Item('sep')]
        for opt in options:
            rows.append(Item('action', opt,
                             (lambda o: lambda _s: note(o) if note else '')(opt),
                             key=f'pick:{opt}'))
        if not options:
            rows.append(Item('info', 'nothing to choose from'))
        rows += [Item('sep'), Item('action', 'Cancel', key='cancel')]
        return rows

    def act(_st, item: Item) -> bool:
        nonlocal chosen
        if item.key.startswith('pick:'):
            chosen = item.key[5:]
        return False

    loop(Screen(build, activate=act, title=title), None)
    return chosen


def press_any(message: str = '') -> None:
    """Say something the next repaint would wipe out, and wait for a key.

    A key rather than a line: there is nothing to type, and asking for enter
    through `input()` is the same cooked-mode reader this module exists to
    keep away from the terminal.
    """
    color = sys.stdout.isatty()
    if message:
        print(message)
    if not sys.stdin.isatty():
        return
    print(paint('\n  press any key ', DIM, color))
    sys.stdout.flush()
    with raw_mode():
        read_key()


# --------------------------------------------------------------------------
# navigation
# --------------------------------------------------------------------------


def first_selectable(items: list[Item], start: int = 0, step: int = 1) -> int:
    i = start
    for _ in range(len(items)):
        if 0 <= i < len(items) and items[i].selectable:
            return i
        i = (i + step) % len(items)
    return 0


def move(items: list[Item], cursor: int, step: int) -> int:
    """Next selectable row, wrapping, skipping separators and facts."""
    i = cursor
    for _ in range(len(items)):
        i = (i + step) % len(items)
        if items[i].selectable:
            return i
    return cursor


def handle_mouse(screen: Screen, st, items: list[Item], cursor: int,
                 ev: Mouse, row_map: dict) -> tuple[int, bool, bool]:
    """One click or wheel step. Same return shape as `handle`.

    A click both selects and acts, because a row is a button: making it select
    first and act on a second click would be a keyboard habit imposed on a
    pointer. Anything that is not a row — header, separator, the help line — is
    inert rather than treated as the nearest row; guessing what a stray click
    meant is worse than doing nothing.
    """
    if ev.wheel_up:
        return move(items, cursor, -1), True, False
    if ev.wheel_down:
        return move(items, cursor, 1), True, False
    if not ev.is_left:                      # middle and right have no meaning
        return cursor, True, False

    idx = row_map.get(ev.row)
    if idx is None or not (0 <= idx < len(items)) or not items[idx].selectable:
        return cursor, True, False

    item = items[idx]
    if item.kind == 'cycle':
        screen.cycle(st, item, True)
        return idx, True, True
    return idx, screen.activate(st, item), True


def handle(screen: Screen, st, items: list[Item], cursor: int, key,
           row_map: dict | None = None) -> tuple[int, bool, bool]:
    """One keystroke or click. Returns (cursor, keep_running, needs_reload)."""
    if isinstance(key, Mouse):
        return handle_mouse(screen, st, items, cursor, key, row_map or {})
    if key in ('q', 'esc', 'ctrl-c', 'eof'):
        return cursor, False, False
    if key == 'up':
        return move(items, cursor, -1), True, False
    if key == 'down':
        return move(items, cursor, 1), True, False
    if key == 'home':
        return first_selectable(items), True, False
    if key == 'end':
        return first_selectable(items, len(items) - 1, -1), True, False

    item = items[cursor] if 0 <= cursor < len(items) else None

    if key == 'backspace' and item is not None:
        return cursor, True, screen.delete(st, item)

    # ‹› adjusts, enter opens. A `cycle` row adjusts by definition; any other
    # row may opt in by carrying an `on_cycle`, which is how a row that asks
    # for a typed value on enter can still be adjusted with an arrow key.
    if key in ('left', 'right') and item is not None \
            and (item.kind == 'cycle' or item.on_cycle is not None):
        screen.cycle(st, item, key == 'right')
        return cursor, True, True
    if key == 'enter' and item is not None:
        if item.kind == 'cycle':
            screen.cycle(st, item, True)
            return cursor, True, True
        return cursor, screen.activate(st, item), True

    if key.isdigit():
        want = int(key)
        n = 0
        for i, it in enumerate(items):
            if not it.selectable:
                continue
            n += 1
            if n == want:
                return i, True, False
    return cursor, True, False


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------


def loop(screen: Screen, st) -> int:
    """Drive one screen until it is left. Returns 0.

    Without a terminal the screen is printed once and the loop is not entered,
    rather than spinning on EOF. That keeps `| less`, CI and `--dry-run`
    honest, and it is the reason every screen here can be smoke-tested by
    running it with stdin closed.
    """
    items = screen.build(st)
    cursor = first_selectable(items)

    if not sys.stdin.isatty():
        print('\n'.join(render(screen, st, items, cursor)))
        return 0

    try:
        while True:
            row_map = draw(screen, st, items, cursor)
            # Raw mode and mouse tracking wrap the keystroke only. Everything a
            # row may run — the TOML editor, kimi-patch.sh, an editor — reads
            # lines from this same terminal: cbreak mode would break their
            # prompts, and tracking left on would feed them escape sequences
            # every time the pointer moved. Switching both off between
            # keystrokes costs a few bytes and removes a whole class of
            # interference. The cursor is shown again for the same reason:
            # a row may ask a question, and a prompt with no cursor is worse
            # than one with a stray cursor under the menu.
            with raw_mode(mouse=True):
                key = read_key()
            show_cursor()
            cursor, keep, reload_ = handle(screen, st, items, cursor, key, row_map)
            if not keep:
                break
            if reload_:
                st = screen.reload(st)
                items = screen.build(st)
                cursor = min(cursor, len(items) - 1)
                if not items[cursor].selectable:
                    cursor = first_selectable(items)
    finally:
        show_cursor()
    return 0


# --------------------------------------------------------------------------
# selfcheck
# --------------------------------------------------------------------------


def row_map_line(items, idx, lines) -> int:
    """Which rendered line a row landed on — for the self-check only."""
    return next(n for n, l in enumerate(lines) if items[idx].label in l)


def _selfcheck() -> int:
    from keyreader import FakeKeys, sgr

    ok = 0

    def check(name, cond, detail=''):
        nonlocal ok
        if cond:
            ok += 1
        else:
            raise AssertionError(f'{name}: {detail}')

    store = {'colour': 'red', 'ran': []}
    CHOICES = ['red', 'green', 'blue']

    def build(st):
        return [
            Item('action', 'First', lambda s: 'do a thing', key='first',
                 help='the first row'),
            Item('info', 'a fact nobody selects'),
            Item('sep'),
            Item('cycle', 'Colour', lambda s: s['colour'], key='colour',
                 choices=CHOICES, help='cycles'),
            Item('submenu', 'Deeper', lambda s: '', key='deeper'),
            Item('action', 'Back', lambda s: '', key='back'),
        ]

    def activate(st, item):
        st['ran'].append(item.key)
        return item.key != 'back'

    def cycle(st, item, forward):
        i = CHOICES.index(st['colour'])
        st['colour'] = CHOICES[(i + (1 if forward else -1)) % len(CHOICES)]

    screen = Screen(build, activate=activate, cycle=cycle, title='test screen')
    items = build(store)

    # -- navigation --------------------------------------------------------
    start = first_selectable(items)
    check('starts on a real row', items[start].selectable and start == 0)

    seps = [i for i, it in enumerate(items) if not it.selectable]
    check('info and sep are both unselectable', len(seps) == 2, seps)

    pos = start
    for _ in range(len(items) * 2):
        pos, _, _ = handle(screen, store, items, pos, 'down')
        check('never lands on an unselectable row', pos not in seps, pos)

    pos_end, _, _ = handle(screen, store, items, start, 'end')
    check('end jumps to the last row', pos_end == len(items) - 1, pos_end)
    pos_home, _, _ = handle(screen, store, items, pos_end, 'home')
    check('home returns to the first', pos_home == start)

    up, _, _ = handle(screen, store, items, start, 'up')
    check('up from the first wraps to the last', up == len(items) - 1, up)

    # digits skip the unselectable rows, so the numbers match what is drawn
    pos3, _, _ = handle(screen, store, items, start, '2')
    check('digit 2 selects the second *selectable* row',
          items[pos3].key == 'colour', items[pos3].key)

    # -- leaving -----------------------------------------------------------
    for key in ('q', 'esc', 'ctrl-c', 'eof'):
        _, keep, _ = handle(screen, store, items, start, key)
        check(f'{key} leaves', keep is False)

    # -- acting ------------------------------------------------------------
    store['ran'] = []
    _, keep, reload_ = handle(screen, store, items, start, 'enter')
    check('enter runs the row', store['ran'] == ['first'], store['ran'])
    check('acting asks for a reload', reload_ and keep)

    idx_back = next(i for i, it in enumerate(items) if it.key == 'back')
    _, keep, _ = handle(screen, store, items, idx_back, 'enter')
    check('a row may close the screen', keep is False)

    # -- cycling -----------------------------------------------------------
    idx = next(i for i, it in enumerate(items) if it.key == 'colour')
    handle(screen, store, items, idx, 'right')
    check('right advances', store['colour'] == 'green', store['colour'])
    handle(screen, store, items, idx, 'left')
    check('left steps back', store['colour'] == 'red', store['colour'])
    handle(screen, store, items, idx, 'enter')
    check('enter cycles too', store['colour'] == 'green', store['colour'])
    handle(screen, store, items, idx, 'left')

    # An action row that carries an `on_cycle` adjusts with the arrows and
    # still runs on enter. That is what lets a row ask for a typed value and
    # be cleared without typing anything.
    cleared = []
    dual = Item('action', 'Dual', key='dual',
                on_cycle=lambda st, it, fwd: cleared.append(fwd))
    rows2 = [dual]
    screen2 = Screen(lambda st: rows2, activate=lambda st, it: True)
    handle(screen2, store, rows2, 0, 'right')
    check('an action row with on_cycle adjusts', cleared == [True], cleared)
    _, keep2, _ = handle(screen2, store, rows2, 0, 'enter')
    check('and still runs on enter', keep2 is True and cleared == [True], cleared)

    plain = Item('action', 'Plain', key='plain')
    rows3 = [plain]
    screen3 = Screen(lambda st: rows3, cycle=lambda st, it, fwd: cleared.append('no'))
    handle(screen3, store, rows3, 0, 'right')
    check('an action row without on_cycle ignores the arrows', cleared == [True], cleared)

    # -- rendering ---------------------------------------------------------
    row_map: dict[int, int] = {}
    lines = render(screen, store, items, start, row_map)
    check('title drawn', any('test screen' in l for l in lines))
    check('cursor drawn', any(CURSOR in l for l in lines))
    check('separator drawn', any(l.startswith('  ─') for l in lines))
    check('info row drawn', any('a fact nobody selects' in l for l in lines))
    check('cycle row shows arrows', any('‹›' in l for l in lines))
    check('help of the selected row drawn', any('the first row' in l for l in lines))
    check('help line drawn', lines[-1] == HELP_SUB, lines[-1])
    check('nothing is coloured unless asked',
          not any('\x1b[' in l for l in lines), lines)

    # Colour is a caller's decision, and the row it marks is the selected one.
    tinted = render(screen, store, items, start, color=True)
    check('the selected row is bold cyan', tinted[row_map_line(items, start, tinted)]
          .startswith(SELECTED), tinted[:6])
    check('an unselected row is left plain',
          not any(l.startswith(SELECTED) for n, l in enumerate(tinted)
                  if n != row_map_line(items, start, tinted)), tinted)
    check('the help line is dimmed', tinted[-1].startswith(DIM), tinted[-1])

    # -- the mouse mapping is the drawing ----------------------------------
    check('every selectable row is mapped',
          len(row_map) == len([i for i in items if i.selectable]), len(row_map))
    for line_no, item_idx in row_map.items():
        check('mapped line holds its row',
              items[item_idx].label in lines[line_no],
              f'line {line_no}: {lines[line_no]!r}')
    dead = [n for n, l in enumerate(lines)
            if n not in row_map]
    check('unmapped lines exist', len(dead) > 0)

    line_no = next(n for n, i in row_map.items() if i == idx)
    store['colour'] = 'red'
    pos, keep, reload_ = handle(screen, store, items, 0, Mouse(0, 5, line_no, False), row_map)
    check('click selects the clicked row', pos == idx, pos)
    check('click on a cycle row advances it', store['colour'] == 'green', store['colour'])
    check('click asks for a reload', reload_ and keep)

    before = store['colour']
    for d in dead:
        pos2, keep2, reload2 = handle(screen, store, items, idx,
                                      Mouse(0, 3, d, False), row_map)
        check(f'click on line {d} does nothing',
              (pos2, keep2, reload2) == (idx, True, False), (pos2, keep2, reload2))
    check('inert clicks changed nothing', store['colour'] == before)

    pos3, _, _ = handle(screen, store, items, idx, Mouse(0, 0, 999, False), row_map)
    check('click past the end is inert', pos3 == idx)
    pos4, _, reload4 = handle(screen, store, items, idx, Mouse(2, 5, line_no, False), row_map)
    check('right button ignored', pos4 == idx and not reload4)

    w = first_selectable(items)
    posw, _, reloadw = handle(screen, store, items, w, Mouse(65, 0, 0, True), row_map)
    check('wheel down moves without acting', posw != w and not reloadw, posw)
    posu, _, _ = handle(screen, store, items, posw, Mouse(64, 0, 0, True), row_map)
    check('wheel up moves back', posu == w, posu)

    # -- end to end: the bytes a terminal sends reach the row --------------
    store['colour'] = 'red'
    ev = read_key(FakeKeys([sgr(0, 5, line_no, press=True), sgr(0, 5, line_no)]))
    check('click bytes decode to a Mouse', isinstance(ev, Mouse), ev)
    pos5, _, _ = handle(screen, store, items, 0, ev, row_map)
    check('decoded click reaches the row', pos5 == idx, pos5)

    # -- the second column -------------------------------------------------
    # A preview is part of the same lines as the rows, so a click still lands
    # where it looks like it should. Both halves of that matter: the columns
    # have to line up, and the mapping has to survive the padding.
    wide = Screen(build, activate=activate, cycle=cycle, title='with a preview',
                  aside=lambda st, sel: ['┌────┐', '│ ab │', '└────┘'])
    rows_w = wide.build(store)
    map_w: dict[int, int] = {}
    out_w = render(wide, store, rows_w, 0, map_w, width=200)
    starts = {visible(l[:l.index('│')]) for l in out_w if '│' in l}
    check('the preview starts in one column', len(starts) == 1, starts)
    check('the rows are still mapped',
          len(map_w) == len([i for i in rows_w if i.selectable]), len(map_w))
    for line_no, item_idx in map_w.items():
        check('a mapped line still holds its row',
              rows_w[item_idx].label in out_w[line_no], out_w[line_no])

    # Too narrow to sit beside, so it goes underneath rather than wrapping —
    # a wrapped line would take two terminal rows and the mapping counts one.
    narrow = render(wide, store, rows_w, 0, None, width=20)
    check('a narrow window puts the preview below',
          '└────┘' in narrow, narrow[-6:])
    check('and above the help lines',
          narrow.index('└────┘') < len(narrow) - 1, narrow[-4:])
    check('and nothing is beside the rows there',
          not any('│' in l and 'Colour' in l for l in narrow))

    # The preview is told which row the cursor is on. Without it a palette
    # preview can only show everything, which answers nothing.
    seen = []
    told = Screen(build, activate=activate, cycle=cycle, title='told',
                  aside=lambda st, sel: seen.append(sel) or ['x'])
    told_rows = told.build(store)
    render(told, store, told_rows, 0)
    check('the preview is told the selected row',
          seen and seen[-1] is told_rows[0], seen)
    render(told, store, told_rows, 3)
    check('and follows the cursor', seen[-1] is told_rows[3], seen[-1])

    check('a wide character counts as two columns', visible('🌕') == 2)
    check('colour codes count as none', visible(f'{DIM}ab{RESET}') == 2)
    check('an empty aside changes nothing',
          beside(['a', 'b'], []) == ['a', 'b'])

    # -- colours -------------------------------------------------------------
    # The picker is the one screen whose whole job is arithmetic, and the
    # arithmetic is the part that can be wrong without looking wrong: a hue
    # that drifts by a degree each time it is converted ends up somewhere else
    # after a few nudges.
    check('hex parses', hex_to_rgb('#4FA8FF') == (79, 168, 255), hex_to_rgb('#4FA8FF'))
    check('the short form is accepted on the way in',
          hex_to_rgb('#abc') == hex_to_rgb('#aabbcc'))
    check('something unreadable is grey, not an exception',
          hex_to_rgb('not a colour') == (128, 128, 128))
    check('hex is written back lower case and six digits',
          rgb_to_hex(79, 168, 255) == '#4fa8ff', rgb_to_hex(79, 168, 255))
    check('a channel out of range is clamped rather than wrapped',
          rgb_to_hex(-20, 300, 128) == '#00ff80', rgb_to_hex(-20, 300, 128))

    for probe in ('#4fa8ff', '#000000', '#ffffff', '#e47b58', '#7f7f7f'):
        r0, g0, b0 = hex_to_rgb(probe)
        h0, s0, l0 = rgb_to_hsl(r0, g0, b0)
        check(f'{probe} survives a round trip through HSL',
              rgb_to_hex(*hsl_to_rgb(h0, s0, l0)) == probe,
              rgb_to_hex(*hsl_to_rgb(h0, s0, l0)))

    check('hue wraps rather than clamping',
          hsl_to_rgb(370, 100, 50) == hsl_to_rgb(10, 100, 50))

    bar = gradient(lambda f: (int(f * 255), 0, 0), 0.5, width=10)
    check('a bar carries one cell per column', bar.count('\x1b[48;2;') == 10)
    check('and exactly one marker on it', bar.count('│') == 1, bar.count('│'))
    left = gradient(lambda f: (0, 0, 0), 0.0, width=10)
    right = gradient(lambda f: (0, 0, 0), 1.0, width=10)
    check('the marker reaches both ends',
          visible(left).index if False else
          ANSI.sub('', left).index('│') == 0
          and ANSI.sub('', right).index('│') == 9,
          (ANSI.sub('', left), ANSI.sub('', right)))
    check('a dark cell takes a light marker', '255;255;255' in left)
    check('a light cell takes a dark marker',
          '38;2;0;0;0' in gradient(lambda f: (255, 255, 255), 0.0, width=4))

    check('a hex value is found inside other text',
          HEX_ANYWHERE.search('rgb #E47B58 there').group(1) == 'E47B58')
    check('and not in a longer run of hex digits',
          HEX_ANYWHERE.search('deadbeef99') is None,
          HEX_ANYWHERE.search('deadbeef99'))

    # Without a terminal the picker returns None rather than blocking, the
    # same rule `field` and `loop` follow.
    check('the picker needs a terminal', color('t', '#ffffff') is None)

    # -- backspace removes ---------------------------------------------------
    removed = []
    del_row = Item('action', 'Removable', key='rm',
                   on_delete=lambda st, it: removed.append(it.key))
    rows_d = [del_row]
    screen_d = Screen(lambda st: rows_d)
    _, keep_d, reload_d = handle(screen_d, store, rows_d, 0, 'backspace')
    check('backspace runs the row\'s delete', removed == ['rm'], removed)
    check('and asks for a reload', reload_d and keep_d)

    plain_row = [Item('action', 'Nothing to remove', key='x')]
    screen_p = Screen(lambda st: plain_row)
    _, _, reload_p = handle(screen_p, store, plain_row, 0, 'backspace')
    check('backspace on a row with nothing to remove is inert', not reload_p)

    # -- a screen with no header still renders -----------------------------
    bare = Screen(lambda st: [Item('action', 'Only', key='only')])
    out = render(bare, store, bare.build(store), 0)
    check('bare screen renders', any('Only' in l for l in out), out)

    print(f'menu selfcheck: ok ({ok} checks)')
    return 0


if __name__ == '__main__':
    sys.exit(_selfcheck())

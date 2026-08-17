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

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from keyreader import Mouse, raw_mode, read_key             # noqa: E402

CURSOR = '❯'                    # the tweakcc marker
RULE_WIDTH = 66
LABEL_WIDTH = 26

# The one line at the bottom of every screen. A submenu adds "esc back",
# because that is the only key whose meaning differs between the two.
HELP_ROOT = '   ↑↓ or wheel move · enter or click open · ‹› change · q quit'
HELP_SUB = '   ↑↓ or wheel move · enter or click open · ‹› change · esc back'


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
                 key='', choices=None, on_cycle=None, on_enter=None, help=''):
        self.kind = kind
        self.label = label
        self.value = value
        self.note = note
        self.key = key
        self.choices = choices or []
        self.on_cycle = on_cycle
        self.on_enter = on_enter
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
                 reload=None, help_line=HELP_SUB, title=''):
        self.build = build
        self._header = header
        self._activate = activate
        self._cycle = cycle
        self._reload = reload
        self.help_line = help_line
        self.title = title

    def header(self, st) -> list[str]:
        if self._header is not None:
            return list(self._header(st))
        return ['', self.title] if self.title else ['']

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


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def render(screen: Screen, st, items: list[Item], cursor: int,
           row_map: dict | None = None) -> list[str]:
    """The screen as lines, recording which line each row landed on."""
    lines = list(screen.header(st))
    lines.append('')

    n = 0
    for i, it in enumerate(items):
        if it.kind == 'sep':
            lines.append('   ' + '─' * RULE_WIDTH)
            continue
        if it.kind == 'info':
            lines.append(f'      {it.label}')
            continue
        n += 1
        mark = CURSOR if i == cursor else ' '
        value = it.value(st)
        note = it.note(st)
        if note:
            value = f'{value}   [{note}]' if value else f'[{note}]'
        arrows = ' ‹›' if (it.kind == 'cycle' or it.on_cycle) else '   '
        if row_map is not None:
            row_map[len(lines)] = i
        lines.append(f' {mark} {n:>2}  {it.label:<{LABEL_WIDTH}}{arrows} {value}')

    lines.append('')
    sel = items[cursor] if 0 <= cursor < len(items) else None
    if sel is not None and sel.help:
        lines.append(f'   {sel.help}')
        lines.append('')
    lines.append(screen.help_line)
    return lines


def draw(screen: Screen, st, items: list[Item], cursor: int) -> dict:
    """Paint the screen and return the line-to-row mapping for the mouse.

    Clear-and-home puts the first line at screen row 0, which is what makes the
    mapping usable directly: a click's zero-based row *is* an index into the
    list that was just printed. That holds as long as the screen fits the
    window; on a very short terminal the top scrolls away and clicks land off.
    """
    sys.stdout.write('\x1b[2J\x1b[H')
    row_map: dict[int, int] = {}
    print('\n'.join(render(screen, st, items, cursor, row_map)))
    sys.stdout.flush()
    return row_map


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

    # ‹› adjusts, enter opens. A `cycle` row adjusts by definition; any other
    # row may opt in by carrying an `on_cycle`, which is how a row that asks
    # for a typed value on enter can still be cleared with an arrow key.
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

    while True:
        row_map = draw(screen, st, items, cursor)
        # Raw mode and mouse tracking wrap the keystroke only. Everything a row
        # may run — the TOML editor, kimi-patch.sh, an editor — reads lines
        # from this same terminal: cbreak mode would break their prompts, and
        # tracking left on would feed them escape sequences every time the
        # pointer moved. Switching both off between keystrokes costs a few
        # bytes and removes a whole class of interference.
        with raw_mode(mouse=True):
            key = read_key()
        cursor, keep, reload_ = handle(screen, st, items, cursor, key, row_map)
        if not keep:
            break
        if reload_:
            st = screen.reload(st)
            items = screen.build(st)
            cursor = min(cursor, len(items) - 1)
            if not items[cursor].selectable:
                cursor = first_selectable(items)
    return 0


# --------------------------------------------------------------------------
# selfcheck
# --------------------------------------------------------------------------


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
    check('separator drawn', any(l.startswith('   ─') for l in lines))
    check('info row drawn', any('a fact nobody selects' in l for l in lines))
    check('cycle row shows arrows', any('‹›' in l for l in lines))
    check('help of the selected row drawn', any('the first row' in l for l in lines))
    check('help line drawn', lines[-1] == HELP_SUB, lines[-1])

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

    # -- a screen with no header still renders -----------------------------
    bare = Screen(lambda st: [Item('action', 'Only', key='only')])
    out = render(bare, store, bare.build(store), 0)
    check('bare screen renders', any('Only' in l for l in out), out)

    print(f'menu selfcheck: ok ({ok} checks)')
    return 0


if __name__ == '__main__':
    sys.exit(_selfcheck())

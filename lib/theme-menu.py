#!/usr/bin/env python3
"""Kimi's colour palette, edited as a file rather than patched into the binary.

Kimi already loads custom themes. `src/tui/theme/custom-theme-loader.ts` reads
`~/.kimi-code/themes/<name>.json`, merges it over a built-in base and offers it
in `/theme`, so nothing here touches the binary — this is the editor Kimi does
not ship, not a patch.

Three properties of that loader decide everything below, and all three are
silent failures if you get them wrong by hand:

  colors = Object.fromEntries(Object.entries(parsed.colors ?? {})
             .filter(([, v]) => HEX_COLOR_REGEX.test(v)));
  HEX_COLOR_REGEX = /^#[0-9a-fA-F]{6}$/;
  RESERVED_THEME_NAMES = new Set(["dark", "light", "auto"]);

A value that is not six-digit hex is dropped without a word — `#fff`, `red` and
`rgb(1,2,3)` all vanish. A token name Kimi does not know is kept in the file
and ignored. And a theme called `dark`, `light` or `auto` never appears in the
picker at all. This editor refuses all three at the point where you can still
see why, which is the only reason it exists.

    python3 lib/theme-menu.py              interactive
    python3 lib/theme-menu.py --selfcheck  prove the reading and writing
"""

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import menu as m                                             # noqa: E402
from menu import Item                                        # noqa: E402

HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
RESERVED = {'dark', 'light', 'auto'}

# The palette, in the order Kimi declares it. Order matters here for one
# reason only: it is the order someone reads when they are looking for the
# token that controls the thing they just saw on screen.
TOKENS = [
    ('primary', 'accents, the spinner while composing'),
    ('accent', 'secondary highlights'),
    ('text', 'ordinary text'),
    ('textStrong', 'emphasised text'),
    ('textDim', 'thinking blocks, tips, the quiet half'),
    ('textMuted', 'the quietest text Kimi draws'),
    ('border', 'the composer frame and rules'),
    ('borderFocus', 'the frame while the composer has focus'),
    ('success', 'confirmations'),
    ('warning', 'warnings'),
    ('error', 'errors'),
    ('diffAdded', 'added lines in a diff'),
    ('diffRemoved', 'removed lines in a diff'),
    ('diffAddedStrong', 'the changed part of an added line'),
    ('diffRemovedStrong', 'the changed part of a removed line'),
    ('diffGutter', 'the line numbers beside a diff'),
    ('diffMeta', 'the file header above a diff'),
    ('roleUser', 'your own messages'),
    ('shellMode', 'the ! shell-mode marker'),
]

# Kimi's own two palettes, so the editor can show what a token looks like
# before it is overridden. Read out of the bundle, not invented.
BUILT_IN = {
    'dark': {
        'primary': '#4FA8FF', 'accent': '#5BC0BE', 'text': '#E0E0E0',
        'textStrong': '#F5F5F5', 'textDim': '#888888', 'textMuted': '#6B6B6B',
        'border': '#5A5A5A', 'borderFocus': '#E8A838', 'success': '#4EC87E',
        'warning': '#E8A838', 'error': '#E85454', 'diffAdded': '#4EC87E',
        'diffRemoved': '#E85454', 'diffAddedStrong': '#7AD99B',
        'diffRemovedStrong': '#F08585', 'diffGutter': '#6B6B6B',
        'diffMeta': '#888888', 'roleUser': '#FFCB6B', 'shellMode': '#BD93F9',
    },
    'light': {
        'primary': '#1565C0', 'accent': '#00838F', 'text': '#1A1A1A',
        'textStrong': '#1A1A1A', 'textDim': '#454545', 'textMuted': '#5F5F5F',
        'border': '#737373', 'borderFocus': '#92660A', 'success': '#0E7A38',
        'warning': '#92660A', 'error': '#B91C1C', 'diffAdded': '#0E7A38',
        'diffRemoved': '#B91C1C', 'diffAddedStrong': '#0E7A38',
        'diffRemovedStrong': '#B91C1C', 'diffGutter': '#737373',
        'diffMeta': '#5F5F5F', 'roleUser': '#9A4A00', 'shellMode': '#7C3AED',
    },
}


def themes_dir() -> Path:
    """Where Kimi looks. `KIMI_CODE_HOME` moves it, and the tests rely on that."""
    home = os.environ.get('KIMI_CODE_HOME')
    return (Path(home) if home else Path.home() / '.kimi-code') / 'themes'


def list_themes(directory: Path | None = None) -> list[str]:
    directory = directory or themes_dir()
    try:
        names = sorted(p.stem for p in directory.glob('*.json'))
    except OSError:
        return []
    # Kimi filters the reserved names out of its own picker, so a file called
    # `dark.json` is invisible there. Showing it here would be a lie.
    return [n for n in names if n not in RESERVED]


def read_theme(name: str, directory: Path | None = None) -> dict:
    directory = directory or themes_dir()
    try:
        data = json.loads((directory / f'{name}.json').read_text())
    except (OSError, ValueError):
        return {'name': name, 'base': 'dark', 'colors': {}}
    if not isinstance(data, dict):
        return {'name': name, 'base': 'dark', 'colors': {}}
    colors = data.get('colors')
    return {
        'name': data.get('name') or name,
        'displayName': data.get('displayName'),
        'base': data.get('base') if data.get('base') in ('dark', 'light') else 'dark',
        'colors': colors if isinstance(colors, dict) else {},
    }


def write_theme(theme: dict, directory: Path | None = None) -> Path:
    """Write one theme, dropping nothing and inventing nothing.

    Only the keys Kimi's schema names are written. A colour that is not
    six-digit hex is refused by `set_color` before it gets here, so anything
    in `colors` at this point is something Kimi will actually load.
    """
    directory = directory or themes_dir()
    directory.mkdir(parents=True, exist_ok=True)
    out = {'name': theme['name'], 'base': theme.get('base', 'dark'),
           'colors': theme.get('colors', {})}
    if theme.get('displayName'):
        out['displayName'] = theme['displayName']
    path = directory / f"{theme['name']}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')
    return path


def valid_name(name: str) -> str:
    """The reason a name is refused, or '' when it is fine."""
    if not name:
        return 'a theme needs a name'
    if name in RESERVED:
        return f'"{name}" is reserved — Kimi hides a theme with that name'
    if not re.fullmatch(r'[A-Za-z0-9._-]+', name):
        return 'use letters, digits, dot, dash or underscore — the name is a filename'
    return ''


def valid_color(value: str) -> str:
    """The reason a colour is refused, or '' when it is fine."""
    if HEX.fullmatch(value):
        return ''
    if re.fullmatch(r'#[0-9a-fA-F]{3}', value):
        return 'Kimi accepts six digits only — write #RRGGBB, not the short form'
    return 'Kimi accepts #RRGGBB only; anything else is dropped without a word'


def effective(theme: dict) -> dict:
    """What Kimi will actually use: the base palette with the overrides on top."""
    palette = dict(BUILT_IN.get(theme.get('base', 'dark'), BUILT_IN['dark']))
    palette.update({k: v for k, v in theme.get('colors', {}).items()
                    if HEX.fullmatch(str(v))})
    return palette


def swatch(hex_value: str) -> str:
    """A block in the colour itself, for terminals that can show it."""
    try:
        r, g, b = (int(hex_value[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return '  '
    return f'\x1b[38;2;{r};{g};{b}m██\x1b[0m'


# --------------------------------------------------------------------------
# screens
# --------------------------------------------------------------------------


class ThemeState:
    """One theme being edited, plus where it lives."""

    def __init__(self, directory: Path | None = None, name: str = ''):
        self.dir = directory or themes_dir()
        self.name = name
        self.theme = read_theme(name, self.dir) if name else {}
        self.message = ''

    def reload(self):
        if self.name:
            self.theme = read_theme(self.name, self.dir)
        return self


def screen_tokens(st: ThemeState) -> m.Screen:
    """One row per palette token; enter asks for a colour."""

    def clear_token(s: ThemeState, item: Item, forward: bool) -> None:
        s.theme.get('colors', {}).pop(item.key[4:], None)
        write_theme(s.theme, s.dir)
        s.message = f'{item.key[4:]} back to the base palette'

    def build(s: ThemeState) -> list[Item]:
        palette = effective(s.theme)
        overrides = s.theme.get('colors', {})
        rows = [Item('info', f'{s.dir / (s.name + ".json")}'),
                Item('info', f'base: {s.theme.get("base", "dark")}   '
                             f'{len(overrides)} of {len(TOKENS)} tokens overridden')]
        if s.message:
            rows.append(Item('info', s.message))
        rows.append(Item('sep'))
        rows.append(Item('cycle', 'Base palette',
                         lambda x: x.theme.get('base', 'dark'), key='__base',
                         choices=['dark', 'light'],
                         help='Tokens you do not set fall back to this palette.'))
        rows.append(Item('sep'))
        for token, what in TOKENS:
            value = palette.get(token, '')
            own = token in overrides
            rows.append(Item(
                'action', token,
                (lambda v, o: lambda x: f'{swatch(v)} {v}{"" if o else "   (base)"}')(value, own),
                key=f'tok:{token}', on_cycle=clear_token,
                help=what + '   (enter sets it, ‹› clears it)'))
        rows += [Item('sep'), Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def act(s: ThemeState, item: Item) -> bool:
        s.message = ''
        if item.key == 'back':
            return False
        if item.key.startswith('tok:'):
            token = item.key[4:]
            current = effective(s.theme).get(token, '')
            raw = _ask(f'{token} [{current}] : ').strip()
            if not raw:
                return True
            why = valid_color(raw)
            if why:
                s.message = f'not written — {why}'
                return True
            s.theme.setdefault('colors', {})[token] = raw
            write_theme(s.theme, s.dir)
            s.message = f'{token} = {raw}'
        return True

    def cyc(s: ThemeState, item: Item, forward: bool) -> None:
        if item.key == '__base':
            s.theme['base'] = 'light' if s.theme.get('base', 'dark') == 'dark' else 'dark'
            write_theme(s.theme, s.dir)

    return m.Screen(build, activate=act, cycle=cyc, reload=lambda s: s.reload(),
                    title='Theme')


def screen_themes(st: ThemeState) -> m.Screen:
    """The list of custom themes, and the way to make another."""

    def build(s: ThemeState) -> list[Item]:
        names = list_themes(s.dir)
        rows = [Item('info', f'{s.dir}'),
                Item('info', 'Kimi ships dark, light and auto; these are yours. '
                             'Switch with /theme.')]
        if s.message:
            rows.append(Item('info', s.message))
        rows.append(Item('sep'))
        for n in names:
            t = read_theme(n, s.dir)
            rows.append(Item('action', n,
                             (lambda th: lambda x: f'{len(th.get("colors", {}))} '
                                                   f'token(s) over {th.get("base", "dark")}')(t),
                             key=f'edit:{n}'))
        if not names:
            rows.append(Item('info', 'none yet'))
        rows += [Item('sep'),
                 Item('action', 'New theme', lambda x: '', key='new',
                      help='Starts from a built-in palette; you override what you want.'),
                 Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def act(s: ThemeState, item: Item) -> bool:
        s.message = ''
        if item.key == 'back':
            return False
        if item.key == 'new':
            name = _ask('name (letters, digits, dash): ').strip()
            why = valid_name(name)
            if why:
                s.message = f'not created — {why}'
                return True
            if (s.dir / f'{name}.json').exists():
                s.message = f'"{name}" already exists — pick it to edit'
                return True
            write_theme({'name': name, 'base': 'dark', 'colors': {}}, s.dir)
            s.message = f'created {name}.json'
            return True
        if item.key.startswith('edit:'):
            inner = ThemeState(s.dir, item.key[5:])
            m.loop(screen_tokens(inner), inner)
        return True

    return m.Screen(build, activate=act, reload=lambda s: s,
                    title='Themes')


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return ''


# --------------------------------------------------------------------------
# selfcheck
# --------------------------------------------------------------------------


def _selfcheck() -> int:
    import tempfile
    ok = 0

    def check(name, cond, detail=''):
        nonlocal ok
        if cond:
            ok += 1
        else:
            raise AssertionError(f'{name}: {detail}')

    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / 'themes'

        check('no themes in an empty directory', list_themes(d) == [])

        # -- what Kimi accepts, and what it silently drops ------------------
        check('six-digit hex is accepted', valid_color('#A1b2C3') == '')
        check('the short form is refused', 'six digits' in valid_color('#fff'))
        check('a colour name is refused', valid_color('red') != '')
        check('rgb() is refused', valid_color('rgb(1,2,3)') != '')

        check('a reserved name is refused', 'reserved' in valid_name('dark'))
        check('an empty name is refused', valid_name('') != '')
        check('a path separator is refused', valid_name('a/b') != '')
        check('an ordinary name is fine', valid_name('midnight') == '')

        # -- round trip ------------------------------------------------------
        write_theme({'name': 'midnight', 'base': 'light',
                     'colors': {'roleUser': '#FFCB6B'}}, d)
        check('the theme is listed', list_themes(d) == ['midnight'], list_themes(d))
        back = read_theme('midnight', d)
        check('name survives', back['name'] == 'midnight')
        check('base survives', back['base'] == 'light')
        check('colours survive', back['colors'] == {'roleUser': '#FFCB6B'})

        # A reserved name on disk is hidden, because Kimi hides it too.
        write_theme({'name': 'dark', 'base': 'dark', 'colors': {}}, d)
        check('a reserved name stays out of the list',
              list_themes(d) == ['midnight'], list_themes(d))

        # -- merging is what Kimi will actually use --------------------------
        eff = effective(back)
        check('an override wins', eff['roleUser'] == '#FFCB6B')
        check('the rest comes from the base', eff['text'] == BUILT_IN['light']['text'])
        check('every token has a value', set(eff) == {t for t, _ in TOKENS},
              set(eff) ^ {t for t, _ in TOKENS})

        # A junk value in the file must not reach the palette, because Kimi
        # would drop it and the editor would otherwise show a colour that is
        # not in use.
        (d / 'broken.json').write_text(json.dumps(
            {'name': 'broken', 'base': 'dark', 'colors': {'text': 'red'}}))
        eff = effective(read_theme('broken', d))
        check('a junk colour does not reach the palette',
              eff['text'] == BUILT_IN['dark']['text'], eff['text'])

        # Unreadable JSON yields an empty theme rather than an exception.
        (d / 'bad.json').write_text('{not json')
        check('unparsable JSON degrades to an empty theme',
              read_theme('bad', d)['colors'] == {})

        # -- the screens are navigable --------------------------------------
        st = ThemeState(d)
        for label, screen, state in (('themes', screen_themes(st), st),
                                     ('tokens', screen_tokens(ThemeState(d, 'midnight')),
                                      ThemeState(d, 'midnight'))):
            rows = screen.build(state)
            check(f'{label}: builds rows', len(rows) > 0)
            dead = [i for i, r in enumerate(rows) if not r.selectable]
            pos = m.first_selectable(rows)
            for _ in range(len(rows) * 2):
                pos, _, _ = m.handle(screen, state, rows, pos, 'down')
                check(f'{label}: never lands on an unselectable row', pos not in dead, pos)
            idx = next(i for i, r in enumerate(rows) if r.key == 'back')
            check(f'{label}: back closes',
                  m.handle(screen, state, rows, idx, 'enter')[1] is False)
            rmap: dict[int, int] = {}
            lines = m.render(screen, state, rows, m.first_selectable(rows), rmap)
            check(f'{label}: every selectable row is mapped',
                  len(rmap) == len([r for r in rows if r.selectable]))
            for line_no, ri in rmap.items():
                check(f'{label}: mapped line holds its row',
                      rows[ri].label in lines[line_no], lines[line_no])

        # ‹› on a token row clears the override and writes the file.
        inner = ThemeState(d, 'midnight')
        screen = screen_tokens(inner)
        rows = screen.build(inner)
        idx = next(i for i, r in enumerate(rows) if r.key == 'tok:roleUser')
        m.handle(screen, inner, rows, idx, 'right')
        check('clearing a token writes through',
              read_theme('midnight', d)['colors'] == {},
              read_theme('midnight', d)['colors'])

        # and the base can be cycled the same way
        idx = next(i for i, r in enumerate(rows) if r.key == '__base')
        m.handle(screen, inner, rows, idx, 'right')
        check('the base cycles and is written',
              read_theme('midnight', d)['base'] == 'dark',
              read_theme('midnight', d)['base'])

    print(f'theme-menu selfcheck: ok ({ok} checks)')
    return 0


def main() -> int:
    if '--selfcheck' in sys.argv:
        return _selfcheck()
    st = ThemeState()
    return m.loop(screen_themes(st), st)


if __name__ == '__main__':
    sys.exit(main())

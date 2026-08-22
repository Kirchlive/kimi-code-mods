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
import subprocess
import sys
from functools import lru_cache
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

# The project's own, which is Kimi's dark palette with one token moved: the
# blue `primary` becomes the red of the banner in README and repo. Everything
# else is deliberately untouched — a theme that changed twelve tokens would be
# a different palette rather than this one wearing its own colour.
BUILT_IN['kimi-code-mods'] = dict(BUILT_IN['dark'], primary='#EA4242')

# Two themes this project ships rather than the user writing them. They are
# ordinary theme files — Kimi only offers what is on disk, so a preset that
# existed only in this menu could not be selected with `/theme` — but the menu
# refuses to delete them and writes them back if they go missing. Names are
# filenames, hence the dash in `Default-Kimi`; `displayName` carries the space.
# `kimi-code-mods` is also the name a colour change from elsewhere in the menu
# writes to (see `OURS` below), and on a case-insensitive filesystem a second
# file spelled with capitals would *be* that file. One theme, then: this preset
# seeds it, and a colour changed later lands in the same place.
# The one a fresh install is pointed at, once, by `ensure_default_theme`.
DEFAULT_PRESET = 'kimi-code-mods'

PRESETS = {
    'kimi-code-mods': {
        'name': 'kimi-code-mods',
        'displayName': 'Kimi-Code-Mods',
        'base': 'dark',
        'colors': {'primary': '#EA4242'},
    },
    'Default-Kimi': {
        'name': 'Default-Kimi',
        'displayName': 'Default Kimi',
        'base': 'dark',
        # Deliberately empty: this *is* Kimi's own palette, offered as a row so
        # there is a way back that reads like the way out.
        'colors': {},
    },
}


def ensure_presets(directory: Path | None = None) -> None:
    """Write any preset whose file is missing, and leave the rest alone.

    Missing rather than different: a preset that has been edited stays edited.
    The menu will not delete these two, but nothing stops an editor or a stray
    `rm`, and a row pointing at a file Kimi cannot load would be worse than a
    file quietly restored.
    """
    directory = directory or themes_dir()
    for name, theme in PRESETS.items():
        if not (directory / f'{name}.json').exists():
            try:
                write_theme(theme, directory)
            except OSError:
                pass


def ensure_default_theme() -> str:
    """Point `tui.toml` at this project's theme, but only the first time.

    The test is whether a `theme =` line exists at all, not what it says: a
    file that names `auto` has been answered, and answering it again would be
    this menu overriding a choice rather than making one. Only a file that has
    never been asked gets `kimi-code-mods` written into it.
    """
    try:
        text = tui_config().read_text()
    except OSError:
        text = ''
    if re.search(r'^\s*theme\s*=', text, re.M):
        return ''
    return set_active_theme(DEFAULT_PRESET)


def kimi_home() -> Path:
    home = os.environ.get('KIMI_CODE_HOME')
    return Path(home) if home else Path.home() / '.kimi-code'


def themes_dir() -> Path:
    """Where Kimi looks. `KIMI_CODE_HOME` moves it, and the tests rely on that."""
    return kimi_home() / 'themes'


@lru_cache(maxsize=1)
def kimi_version() -> str:
    """The version of the installed binary, or '' when it cannot be asked.

    The preview draws Kimi's own header, and a header naming a version that is
    not the one installed is the preview quietly lying about the thing it
    exists to show. Asked once per run and cached: this is drawn on every
    keystroke, and starting a 170 MB binary that often would be felt.

    An empty answer is a fine answer — the caller drops the number rather than
    printing a stale one.
    """
    binary = kimi_home() / 'bin' / 'kimi'
    try:
        out = subprocess.run([str(binary), '--version'], capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ''
    first = (out.stdout or out.stderr).strip().splitlines()
    if not first:
        return ''
    # Kimi answers with the bare number; anything else is taken as no answer
    # rather than pasted into the header.
    hit = re.search(r'\d+\.\d+\.\d+', first[0])
    return hit.group(0) if hit else ''


def tui_config() -> Path:
    """`tui.toml`, which is where the *chosen* theme lives.

    Not `config.toml`: Kimi splits its settings in two, and the file says so
    itself — "Terminal UI preferences for kimi-code. Agent/runtime settings
    stay in ~/.kimi-code/config.toml". The theme is a UI preference, so a
    menu that only ever looked at `config.toml` could edit every palette and
    never tell you which one was in use.
    """
    return kimi_home() / 'tui.toml'


def active_theme() -> str:
    """The theme Kimi is set to use: a name, or `auto` / `dark` / `light`."""
    try:
        text = tui_config().read_text()
    except OSError:
        return 'auto'
    hit = re.search(r'^\s*theme\s*=\s*"([^"]*)"', text, re.M)
    return hit.group(1) if hit else 'auto'


def set_active_theme(name: str) -> str:
    """Point `tui.toml` at a theme. Returns '' or the reason it was not done.

    The line is replaced where it stands and the rest of the file is left
    alone, for the same reason the config editor does it that way: this is a
    file the user owns, with their comments in it.
    """
    path = tui_config()
    try:
        text = path.read_text()
    except OSError:
        text = ''
    line = f'theme = "{name}"'
    quoted = re.compile(r'^(\s*theme\s*=\s*)"[^"]*"', re.M)
    if quoted.search(text):
        # Only the value inside the quotes. Kimi's own file ends that line
        # with `# "auto" | "dark" | "light" | custom theme name`, and
        # replacing the whole line would take the note with it.
        text = quoted.sub(lambda hit: f'{hit.group(1)}"{name}"', text, count=1)
    elif re.search(r'^\s*theme\s*=', text, re.M):
        text = re.sub(r'^\s*theme\s*=.*$', line, text, count=1, flags=re.M)
    else:
        header = ('# ~/.kimi-code/tui.toml\n'
                  '# Terminal UI preferences for kimi-code.\n\n') if not text else ''
        text = header + text + ('\n' if text and not text.endswith('\n') else '') + line + '\n'
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    except OSError as e:
        return str(e)
    return ''


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


def rgb(hex_value: str) -> str:
    """The escape sequence for a hex colour, or '' if it is not one."""
    try:
        r, g, b = (int(hex_value[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return ''
    return f'\x1b[38;2;{r};{g};{b}m'


def swatch(hex_value: str) -> str:
    """A block in the colour itself, for terminals that can show it."""
    code = rgb(hex_value)
    return f'{code}██\x1b[0m' if code else '  '


def tint(text: str, hex_value: str) -> str:
    code = rgb(hex_value)
    return f'{code}{text}\x1b[0m' if code else text


# Bold, and only bold. An underline was here too, on the argument that weight
# alone can be hard to place at a glance — but it draws a rule through a
# preview whose whole job is to show what a palette looks like, and the arrow
# in the margin already says which line is meant.
STANDOUT = '\x1b[1m'


def embolden(line: str) -> str:
    """The same line made to stand out, without losing any of its colours.

    The styling cannot simply wrap the line: each coloured run already ends in
    a reset, and a reset clears weight along with colour — so a single
    sequence in front would survive exactly as far as the first `tint`.
    Setting it again after every reset is what carries it across the whole
    line rather than its first few characters.
    """
    return STANDOUT + line.replace('\x1b[0m', '\x1b[0m' + STANDOUT) + '\x1b[0m'


# What a Kimi session looks like, in the tokens that colour it. Every line is
# here because a token drives it: change `roleUser` and the prompt line moves,
# change `diffAdded` and the `+` line does. A palette is judged by looking at
# it, and this is the smallest thing worth looking at.
PREVIEW_WIDTH = 40


def preview(palette: dict, highlight: str = '') -> list[str]:
    """A mock Kimi transcript in `palette`, as lines ready to be drawn.

    Find the thing you want to change on screen, and the row that changes it
    is the token drawing it here. `highlight` names the token being edited, so
    the preview can say which of its lines is the one to watch — with
    nineteen tokens and a dozen lines, "it changed somewhere" is not an
    answer.
    """
    def c(token: str) -> str:
        return palette.get(token, '#888888')

    # Each line is paired with the tokens that draw it, so the picker can mark
    # the one being edited. Every token in TOKENS appears at least once — a
    # palette entry with nothing to point at is one you have to change blind.
    w = PREVIEW_WIDTH
    body = [
        ('primary', tint('🌕 Kimi Code' + (f' {kimi_version()}' if kimi_version()
                                           else ''), c('primary'))),
        ('textMuted', tint('   ~/.kimi-code-mods', c('textMuted'))),
        ('', ''),
        ('roleUser', tint('> list the dir', c('roleUser'))),
        ('shellMode', tint('! ls -la', c('shellMode'))),
        ('borderFocus', tint('╭ composer, focused ─────╮', c('borderFocus'))),
        ('', ''),
        ('accent text', tint('● Read', c('accent')) + tint('(config.toml)', c('text'))),
        ('textDim', tint(' ⎿ 42 lines', c('textDim'))),
        ('diffGutter diffRemoved diffRemovedStrong',
         tint('  1 ', c('diffGutter')) + tint('- reserved_context_size = ', c('diffRemoved'))
         + tint('50000', c('diffRemovedStrong'))),
        ('diffGutter diffAdded diffAddedStrong',
         tint('  2 ', c('diffGutter')) + tint('+ reserved_context_size = ', c('diffAdded'))
         + tint('80000', c('diffAddedStrong'))),
        ('diffMeta', tint('  @@ config.toml', c('diffMeta'))),
        ('', ''),
        ('textDim', tint('✻ Thinking… (esc to interrupt)', c('textDim'))),
        ('success warning error',
         tint('✓ done', c('success')) + '  '
         + tint('⚠ careful', c('warning')) + '  '
         + tint('✗ failed', c('error'))),
        ('textStrong', tint('The directory holds 123 files.', c('textStrong'))),
    ]
    # `border` draws the frame around all of this rather than any line in
    # it, so it is the frame that goes bold when it is the one selected. A
    # placeholder row would be the one token in the palette whose highlight
    # shows nothing.
    frame_lit = highlight == 'border'
    heavy = embolden if frame_lit else (lambda x: x)
    top = heavy(tint('┌' + '─' * w + '┐', c('border')))
    bottom = heavy(tint('└' + '─' * w + '┘', c('border')))
    edge = heavy(tint('│', c('border')))
    out = ['', ' Preview', '', top + ('◀' if frame_lit else '')]
    for owner, line in body:
        pad = ' ' * max(0, w - 1 - m.visible(line))
        # `highlight in owner` would match `text` inside `textDim`, so the
        # owners are compared as whole words.
        mine = bool(highlight) and highlight in owner.split()
        mark = '◀' if mine else ' '
        out.append(f'{edge} {embolden(line) if mine else line}{pad}{edge}{mark}')
    out.append(bottom + ('◀' if frame_lit else ''))
    if highlight:
        drawn = frame_lit or any(highlight in owner.split()
                                 for owner, _ in body if owner)
        out += ['', f'  {highlight} draws the marked line' if drawn else
                f'  {highlight} draws nothing in this preview']
    return out


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

    def clear_token(s: ThemeState, item: Item) -> None:
        s.theme.get('colors', {}).pop(item.key[4:], None)
        write_theme(s.theme, s.dir)
        s.message = f'{item.key[4:]} back to the base palette'

    def build(s: ThemeState) -> list[Item]:
        palette = effective(s.theme)
        overrides = s.theme.get('colors', {})
        in_use = active_theme()
        rows = [Item('info', f'{s.dir / (s.name + ".json")}'),
                Item('info', f'base: {s.theme.get("base", "dark")}   '
                             f'{len(overrides)} of {len(TOKENS)} tokens overridden')]
        # Editing a theme that is not the one in use changes a file and
        # nothing you can see, which reads as the editor not working.
        if in_use == s.name:
            rows.append(Item('info', 'in use — Kimi reads it when it starts; '
                                     '/theme switches a running session'))
        else:
            rows.append(Item('info', f'not in use — tui.toml says "{in_use}", so '
                                     f'nothing here shows up until you switch'))
        if s.message:
            rows.append(Item('info', s.message))
        rows.append(Item('sep'))
        # Putting it into use comes first, because it is what the line above
        # says is missing: a theme not in use shows nothing, so the row that
        # fixes that belongs where the eye lands, not under the palette
        # setting it makes no difference to yet.
        if in_use != s.name:
            rows.append(Item('action', 'Use this theme',
                             lambda x: f'tui.toml says "{in_use}"', key='__use',
                             help='Writes it to tui.toml, so what you change here '
                                  'is what you see at the next start.'))
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
                key=f'tok:{token}', on_delete=clear_token,
                help=what + '   (enter sets it, backspace clears it)'))
        rows += [Item('sep'), Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def act(s: ThemeState, item: Item) -> bool:
        s.message = ''
        if item.key == 'back':
            return False
        if item.key == '__use':
            problem = set_active_theme(s.name)
            s.message = f'not written — {problem}' if problem else \
                f'tui.toml now says {s.name}'
            return True
        if item.key.startswith('tok:'):
            token = item.key[4:]
            current = effective(s.theme).get(token, '')

            # The picker rather than a field. Six hex digits are a description
            # of a colour and not the colour itself; the difficult part is
            # getting from the one you can picture to those digits, and three
            # bars drawn in the colours they select turn that back into
            # looking at something. The preview follows the bars, so the
            # question being answered is "does this look right" rather than
            # "is this the number I meant".
            def with_token(hex_value: str) -> list[str]:
                trial = dict(s.theme)
                trial['colors'] = dict(s.theme.get('colors', {}))
                trial['colors'][token] = hex_value
                return preview(effective(trial), token)

            raw = m.color(f'{token} — {dict(TOKENS).get(token, "")}', current,
                          hint='Kimi accepts #RRGGBB only.',
                          preview=with_token)
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
                    aside=lambda s, sel: preview(
                        effective(s.theme),
                        sel.key[4:] if sel is not None and sel.key.startswith('tok:')
                        else ''),
                    help_line=m.HELP_DEL, title='Theme')


def screen_themes(st: ThemeState) -> m.Screen:
    """The list of custom themes, and the way to make another."""

    def build(s: ThemeState) -> list[Item]:
        ensure_presets(s.dir)
        names = [n for n in list_themes(s.dir) if n not in PRESETS]
        rows = [Item('info', f'{s.dir}'),
                Item('info', 'Kimi ships dark, light and auto; the two below are '
                             'this project\'s, the rest are yours. Switch with '
                             '/theme.')]
        if s.message:
            rows.append(Item('info', s.message))
        rows.append(Item('sep'))
        in_use = active_theme()

        def theme_row(n: str, preset: bool) -> Item:
            th = read_theme(n, s.dir)
            label = th.get('displayName') or n
            return Item('action', label,
                        (lambda t_, mine: lambda x:
                         f'{len(t_.get("colors", {}))} token(s) over '
                         f'{t_.get("base", "dark")}'
                         + ('   ← in use' if mine else ''))(th, n == in_use),
                        key=f'edit:{n}',
                        # The two presets carry no `on_delete`, which is the
                        # whole of "cannot be deleted": backspace asks the row
                        # to remove itself and this row does not answer.
                        on_delete=None if preset else delete,
                        help='enter edits it' if preset
                        else 'enter edits it, backspace deletes the file')

        presets = [theme_row(n, True) for n in PRESETS]
        mine = [theme_row(n, False) for n in names]

        # The rules above and below the presets are drawn to the width of the
        # rows they bracket, not to the menu's standard `RULE_WIDTH`: a row
        # ending in `← in use` runs past that, and a rule stopping short of the
        # thing it is separating looks like it belongs to something else. A row
        # is the mark, a space, the label column, the arrow column, a space,
        # and the value — everything but the two-space indent every line
        # already carries.
        widest = max([m.RULE_WIDTH]
                     + [m.LABEL_WIDTH + 4 + m.visible(r.value(s))
                        for r in presets + mine])
        rule = Item('info', '─' * widest)

        rows[-1] = rule                      # the separator opened above
        rows += presets
        rows.append(rule)
        rows += mine
        rows += [rule,
                 Item('action', 'New theme', lambda x: '', key='new',
                      help='Starts from a built-in palette; you override what you want.'),
                 Item('action', 'Theme in use',
                      lambda x: in_use, key='use',
                      help='What tui.toml is set to. Kimi reads it at the next '
                           'start; /theme changes it for a running session.'),
                 Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def act(s: ThemeState, item: Item) -> bool:
        s.message = ''
        if item.key == 'back':
            return False
        if item.key == 'new':
            name = (_ask('Theme name',
                         hint='Letters, digits, dot, dash or underscore — it is a '
                              'filename. dark, light and auto are reserved.')
                    or '').strip()
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
        if item.key == 'use':
            # `auto`, `dark` and `light` are Kimi's own and always available;
            # everything else has to be a theme that exists, or Kimi falls
            # back without saying so.
            choice = m.pick('Theme in use',
                            ['auto', 'dark', 'light'] + list_themes(s.dir),
                            hint='Written to tui.toml. Kimi reads it at the next '
                                 'start.',
                            note=lambda n: 'Kimi\'s own' if n in
                            ('auto', 'dark', 'light') else 'yours')
            if choice:
                why = set_active_theme(choice)
                s.message = f'not written — {why}' if why else \
                    f'tui.toml now says {choice}'
            return True
        if item.key.startswith('edit:'):
            inner = ThemeState(s.dir, item.key[5:])
            m.loop(screen_tokens(inner), inner)
        return True

    def delete(s: ThemeState, item: Item) -> None:
        """Remove a theme's file. There is nothing else to it — the file *is*
        the theme, and Kimi stops offering it the moment it is gone."""
        name = item.key[5:]
        path = s.dir / f'{name}.json'
        try:
            path.unlink()
            s.message = f'deleted {path.name}'
        except OSError as e:
            s.message = f'not deleted — {e}'

    return m.Screen(build, activate=act, reload=lambda s: s,
                    aside=lambda s, sel: preview(effective(
                        read_theme(_hovered(s), s.dir))) if list_themes(s.dir) else [],
                    help_line=m.HELP_DEL, title='Themes')


# The theme created on demand when a colour is changed from a screen that is
# not the theme editor. One name, so a second colour changed a week later
# lands in the same file rather than in a pile of them.
OURS = 'kimi-code-mods'


def make_theme_to_edit(directory: Path | None = None) -> tuple[str, str]:
    """A theme that can be written to, creating one if there is none.

    Asking someone to go and set up a theme before they may change a colour
    is a step they did not ask for and cannot have wanted. So the step is
    taken for them: a theme of ours over whichever built-in palette is in
    play, written to `tui.toml` as the one in use. It overrides nothing until
    a colour is actually changed, so creating it changes how nothing looks.

    Returns the name and a line saying what happened, or an empty name and
    the reason it could not be done.
    """
    name, _ = editable_theme(directory)
    if name:
        return name, ''
    directory = directory or themes_dir()
    base = 'light' if active_theme() == 'light' else 'dark'
    made = ''
    if OURS not in list_themes(directory):
        try:
            write_theme({'name': OURS, 'base': base, 'colors': {}}, directory)
        except OSError as e:
            return '', f'could not create a theme — {e}'
        made = f'created {OURS} over {base}'
    problem = set_active_theme(OURS)
    if problem:
        return '', f'created it, but tui.toml not written — {problem}'
    return OURS, (f'{made} and set it as the theme in use' if made
                  else f'{OURS} is now the theme in use')


def editable_theme(directory: Path | None = None) -> tuple[str, str]:
    """The theme a colour change would land in, and why there might not be one.

    Kimi's own three cannot be edited — they are compiled in, and a file
    called `dark.json` is filtered out of its picker anyway. So a colour
    changed from anywhere else in kimi-code-mods needs a theme of your own that is
    also the one in use, and when there is not one the honest answer is to say
    so and offer to make it.
    """
    name = active_theme()
    if name in RESERVED:
        return '', f'Kimi is set to "{name}", which is built in and cannot be edited'
    if name not in list_themes(directory):
        return '', f'tui.toml names "{name}", but there is no such theme file'
    return name, ''


def screen_colors(tokens: list[str], title: str,
                  directory: Path | None = None) -> m.Screen:
    """A few palette tokens, reachable from the screen they affect.

    Every colour in Kimi comes from the palette, so "what colour is my own
    message" and "what colour is the composer frame" are questions about a
    theme token. Rather than answer them twice — once here, once in the theme
    editor — this is the theme editor, narrowed to the tokens that matter for
    the screen you came from.
    """
    directory = directory or themes_dir()
    state = ThemeState(directory)

    def build(s: ThemeState) -> list[Item]:
        name, why = editable_theme(directory)
        rows = [Item('info', 'These are palette tokens: the same values the '
                             'theme editor writes.'),
                Item('info', 'Kimi reads the theme when it starts; /theme '
                             'switches a running session.')]
        # The rows are offered either way. Without a theme of your own there
        # is nothing to write to *yet*, and the answer to that is to make one
        # when a colour is actually chosen — not to withhold the rows until
        # some preparation has been done.
        rows.append(Item('info', f'changes go to "{name}"' if name
                         else f'{why}; changing a colour will create "{OURS}" '
                              f'and use it'))
        if s.message:
            rows.append(Item('info', s.message))
        rows.append(Item('sep'))

        theme = read_theme(name, directory) if name else \
            {'name': OURS, 'base': 'light' if active_theme() == 'light' else 'dark',
             'colors': {}}
        palette = effective(theme)
        overrides = theme.get('colors', {})
        for token in tokens:
            value = palette.get(token, '')
            rows.append(Item(
                'action', token,
                (lambda v, own: lambda x:
                 f'{swatch(v)} {v}{"" if own else "   (base)"}')(value, token in overrides),
                key=f'tok:{token}', on_delete=clear,
                help=dict(TOKENS).get(token, '') + '   (backspace restores the base)'))
        rows += [Item('sep'), Item('action', 'Open the whole palette', lambda x: '',
                                   key='all'),
                 Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def clear(s: ThemeState, item: Item) -> None:
        name, _ = editable_theme(directory)
        if not name:
            return
        theme = read_theme(name, directory)
        theme.get('colors', {}).pop(item.key[4:], None)
        write_theme(theme, directory)
        s.message = f'{item.key[4:]} back to the base palette'

    def act(s: ThemeState, item: Item) -> bool:
        s.message = ''
        if item.key == 'back':
            return False
        if item.key == 'all':
            name, note = make_theme_to_edit(directory)
            if not name:
                s.message = note
                return True
            inner = ThemeState(directory, name)
            m.loop(screen_tokens(inner), inner)
            return True
        if item.key.startswith('tok:'):
            # A theme is made here rather than demanded up front. Nothing
            # about it changes how Kimi looks until the colour below is
            # written into it.
            name, note = make_theme_to_edit(directory)
            if not name:
                s.message = note
                return True
            token = item.key[4:]
            theme = read_theme(name, directory)

            def with_token(hex_value: str) -> list[str]:
                trial = dict(theme)
                trial['colors'] = dict(theme.get('colors', {}))
                trial['colors'][token] = hex_value
                return preview(effective(trial), token)

            raw = m.color(f'{token} — {dict(TOKENS).get(token, "")}',
                          effective(theme).get(token, ''),
                          hint='Kimi accepts #RRGGBB only.', preview=with_token)
            if not raw:
                return True
            why = valid_color(raw)
            if why:
                s.message = f'not written — {why}'
                return True
            theme.setdefault('colors', {})[token] = raw
            write_theme(theme, directory)
            s.message = f'{token} = {raw}' + (f' — {note}' if note else '')
        return True

    def aside(s: ThemeState, sel=None) -> list[str]:
        name, _ = editable_theme(directory)
        theme = read_theme(name, directory) if name else \
            {'base': 'light' if active_theme() == 'light' else 'dark', 'colors': {}}
        token = sel.key[4:] if sel is not None and sel.key.startswith('tok:') else ''
        return preview(effective(theme), token)

    return m.Screen(build, activate=act, reload=lambda s: s, aside=aside,
                    help_line=m.HELP_DEL, title=title), state


def _hovered(s: ThemeState) -> str:
    """Which theme the list preview should show.

    The list screen has no idea which row the cursor is on — that lives in
    `loop`. Rather than thread it through, the preview shows the first theme,
    which is what the cursor starts on; opening one shows its own.
    """
    names = list_themes(s.dir)
    return names[0] if names else ''


def _ask(title: str, value: str = '', hint: str = ''):
    """One typed value, in a field. See `menu.field` for why not `input()`."""
    return m.field(title, value, hint)


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
        # `tui.toml` is found through KIMI_CODE_HOME, the same variable that
        # moves the theme directory, so the checks below have a home of their
        # own rather than writing into the real one.
        was_home = os.environ.get('KIMI_CODE_HOME')
        os.environ['KIMI_CODE_HOME'] = td

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
                      m.title_case(rows[ri].label) in lines[line_no],
                      lines[line_no])

        # -- the theme in use ------------------------------------------------
        # It lives in tui.toml, not config.toml — Kimi splits its settings and
        # says so in the file it writes. A menu looking only at config.toml
        # could edit every palette and never know which one was in use.
        cfg = Path(td) / 'tui.toml'
        cfg.unlink(missing_ok=True)
        check('no tui.toml reads as auto', active_theme() == 'auto', active_theme())

        cfg.write_text('# mine\ntheme = "midnight"\nrender_latex = true\n')
        check('the theme in use is read', active_theme() == 'midnight', active_theme())

        check('setting it writes cleanly', set_active_theme('sunset') == '')
        check('and the theme in use follows', active_theme() == 'sunset')
        kept = cfg.read_text()
        check('the rest of the file survives',
              '# mine' in kept and 'render_latex = true' in kept, kept)
        check('and the key is not duplicated', kept.count('theme =') == 1, kept)

        # Kimi's own file explains the allowed values in a comment on that
        # very line. Replacing the whole line would take the note with it.
        cfg.write_text('theme = "auto" # "auto" | "dark" | "light" | custom\n'
                       '[editor]\ncommand = ""\n')
        set_active_theme('midnight')
        after = cfg.read_text()
        check('the note after the value is kept',
              '# "auto" | "dark" | "light" | custom' in after, after)
        check('and the value did change', active_theme() == 'midnight', after)
        check('the sections below are untouched', '[editor]' in after, after)

        cfg.unlink()
        check('a missing file is created with a header',
              set_active_theme('midnight') == '' and 'tui.toml' in cfg.read_text(),
              cfg.read_text())
        check('and reads back', active_theme() == 'midnight')

        # -- colours reached from another screen ------------------------------
        # Kimi's own three cannot be edited, so a colour changed from anywhere
        # else needs a theme of your own that is also the one in use.
        set_active_theme('dark')
        name, why = editable_theme(d)
        check('a built-in theme is not editable', name == '' and 'built in' in why, why)
        set_active_theme('nothing-like-this')
        name, why = editable_theme(d)
        check('a theme with no file is not editable',
              name == '' and 'no such theme' in why, why)
        set_active_theme('midnight')
        name, why = editable_theme(d)
        check('a theme of your own that is in use is editable',
              name == 'midnight' and why == '', (name, why))

        narrow, nstate = screen_colors(['roleUser'], 'Your message colour', d)
        nrows = narrow.build(nstate)
        check('the narrowed screen offers the token asked for',
              any(r.key == 'tok:roleUser' for r in nrows), [r.key for r in nrows])
        check('and no others',
              len([r for r in nrows if r.key.startswith('tok:')]) == 1)
        check('it can open the whole palette from there',
              any(r.key == 'all' for r in nrows))
        check('and it previews the theme it is editing',
              any('Preview' in l for l in narrow.aside(nstate)))

        # With Kimi's own theme in use the rows are still there — asking
        # someone to go and set up a theme before they may change a colour is
        # a step they did not ask for. The screen says what will happen, and
        # the theme is made when a colour is actually chosen.
        set_active_theme('dark')
        rows_none = narrow.build(nstate)
        check('the token rows are offered even with a built-in theme in use',
              any(r.key == 'tok:roleUser' for r in rows_none),
              [r.key for r in rows_none])
        check('and the screen says what changing one will do',
              any(r.kind == 'info' and OURS in r.label for r in rows_none),
              [r.label for r in rows_none if r.kind == 'info'])
        check('the preview still shows the palette it would start from',
              any('Preview' in l for l in narrow.aside(nstate)))

        # Making it is the act of changing a colour, not a step before it. The
        # themes screen seeds the same file as a preset, so it is removed first
        # — otherwise this would exercise the reuse path that the next check
        # covers and never the create path it is written for.
        (d / f'{OURS}.json').unlink(missing_ok=True)
        name2, note = make_theme_to_edit(d)
        check('a theme is created on demand', name2 == OURS, (name2, note))
        check('and put into use', active_theme() == OURS, active_theme())
        check('it says what it did', 'created' in note and OURS in note, note)
        check('it overrides nothing to begin with',
              read_theme(OURS, d)['colors'] == {}, read_theme(OURS, d))
        again, note2 = make_theme_to_edit(d)
        check('asking twice reuses it rather than making a second',
              again == OURS and 'created' not in note2, (again, note2))
        check('and it takes the base from the palette in play',
              read_theme(OURS, d)['base'] == 'dark', read_theme(OURS, d)['base'])

        set_active_theme('light')
        (d / f'{OURS}.json').unlink()
        make_theme_to_edit(d)
        check('a light palette in use gives a light base',
              read_theme(OURS, d)['base'] == 'light', read_theme(OURS, d)['base'])
        (d / f'{OURS}.json').unlink()
        set_active_theme('midnight')

        # Editing a theme that is not in use changes a file and nothing you
        # can see, which reads as the editor not working. The screen says so,
        # and offers the one keystroke that fixes it.
        set_active_theme('sunset')
        st_off = ThemeState(d, 'midnight')
        rows_off = screen_tokens(st_off).build(st_off)
        check('a theme that is not in use says so',
              any(r.kind == 'info' and 'not in use' in r.label for r in rows_off),
              [r.label for r in rows_off if r.kind == 'info'])
        check('and offers to switch to it',
              any(r.key == '__use' for r in rows_off))
        m.handle(screen_tokens(st_off), st_off, rows_off,
                 next(i for i, r in enumerate(rows_off) if r.key == '__use'), 'enter')
        check('which writes tui.toml', active_theme() == 'midnight', active_theme())

        rows_on = screen_tokens(st_off).build(st_off)
        check('the theme in use says that instead',
              any(r.kind == 'info' and 'in use —' in r.label for r in rows_on),
              [r.label for r in rows_on if r.kind == 'info'])
        check('and has nothing to switch to',
              not any(r.key == '__use' for r in rows_on))
        check('it also says when the change takes effect',
              any('starts' in r.label for r in rows_on if r.kind == 'info'))

        # Every token has to draw something in the preview, or it is one you
        # can only change blind — pick a colour, look, and see nothing move.
        import re as _re
        src = Path(__file__).read_text()
        seg = src[src.index('body = ['):src.index('    ]', src.index('body = ['))]
        owners = set()
        for hit in _re.finditer(r"\('([a-zA-Z ]*)',", seg):
            owners |= set(hit.group(1).split())
        owners.add('border')          # the frame, emboldened rather than a row
        names = {t for t, _ in TOKENS}
        check('every token draws something in the preview',
              names <= owners, sorted(names - owners))
        check('the preview names no token that does not exist',
              owners <= names | {'border'}, sorted(owners - names))

        # And the preview marks the one under the cursor, so "it changed
        # somewhere" is not the answer to a nudge on a bar. Bold rather than
        # only an arrow: the line itself is what you are looking at.
        marked = preview(BUILT_IN['dark'], 'roleUser')
        check('the edited token is marked', any('◀' in l for l in marked))
        check('and its line is drawn bold',
              any(STANDOUT in l and 'list the dir' in l for l in marked),
              [l for l in marked if 'list the dir' in l])
        check('and named under the frame',
              any('roleUser' in l for l in marked), marked[-2:])
        check('only that line stands out',
              len([l for l in marked if STANDOUT in l]) == 1,
              [m.ANSI.sub('', l) for l in marked if STANDOUT in l])

        # Bold has to survive the colours already in the line: each coloured
        # run ends in a reset, and a reset clears weight too, so a single
        # bold in front would stop at the first one.
        line = tint('a', '#ff0000') + tint('b', '#00ff00')
        heavy = embolden(line)
        check('every coloured run in a line carries the styling',
              heavy.count(STANDOUT) == 3, heavy.count(STANDOUT))
        check('and it is bold, with no underline through the preview',
              STANDOUT == '\x1b[1m', STANDOUT)
        check('and the text is unchanged', m.ANSI.sub('', heavy) == 'ab',
              m.ANSI.sub('', heavy))
        check('bolding does not change how wide a line is',
              m.visible(heavy) == m.visible(line))

        # `text` is a token and so is `textDim`; a substring match would
        # bold the wrong line every time the plain one is selected.
        only_dim = preview(BUILT_IN['dark'], 'textDim')
        bold_dim = [m.ANSI.sub('', l) for l in only_dim if STANDOUT in l]
        check('a token is matched as a whole word',
              all('Read' not in l for l in bold_dim), bold_dim)
        check('and textDim finds its own lines', len(bold_dim) == 2, bold_dim)

        plain = preview(BUILT_IN['dark'])
        check('with nothing to mark, nothing is marked',
              not any('◀' in l for l in plain))
        check('and nothing stands out',
              not any(STANDOUT in l for l in plain))

        # The screen hands the cursor's row to the preview, which is what
        # makes any of this follow the selection.
        st_tok = ThemeState(d, 'midnight')
        scr_tok = screen_tokens(st_tok)
        rows_tok = scr_tok.build(st_tok)
        on_role = next(r for r in rows_tok if r.key == 'tok:roleUser')
        check('the token screen highlights the row under the cursor',
              any('◀' in l for l in scr_tok.aside(st_tok, on_role)))
        on_base = next(r for r in rows_tok if r.key == '__base')
        check('a row that is not a token highlights nothing',
              not any('◀' in l for l in scr_tok.aside(st_tok, on_base)))

        # `border` draws the frame rather than a line inside it, so that is
        # what goes bold — the one token whose highlight would otherwise
        # point at an empty row.
        framed = preview(BUILT_IN['dark'], 'border')
        check('selecting border makes the frame stand out',
              STANDOUT in framed[3] and framed[3].rstrip().endswith('◀'),
              m.ANSI.sub('', framed[3]))
        check('and says so rather than calling it missing',
              any('draws the marked line' in l for l in framed), framed[-2:])
        check('and neither does no row at all',
              not any('◀' in l for l in scr_tok.aside(st_tok, None)))

        # Backspace on a token row clears the override and writes the file;
        # ‹›, which used to do it, leaves the colour alone.
        inner = ThemeState(d, 'midnight')
        screen = screen_tokens(inner)
        rows = screen.build(inner)
        idx = next(i for i, r in enumerate(rows) if r.key == 'tok:roleUser')
        m.handle(screen, inner, rows, idx, 'right')
        check('‹› no longer clears a token',
              read_theme('midnight', d)['colors'] != {},
              read_theme('midnight', d)['colors'])
        m.handle(screen, inner, rows, idx, 'backspace')
        check('backspace clears a token and writes through',
              read_theme('midnight', d)['colors'] == {},
              read_theme('midnight', d)['colors'])

        # and the base can be cycled the same way
        idx = next(i for i, r in enumerate(rows) if r.key == '__base')
        m.handle(screen, inner, rows, idx, 'right')
        check('the base cycles and is written',
              read_theme('midnight', d)['base'] == 'dark',
              read_theme('midnight', d)['base'])

    if was_home is None:
        os.environ.pop('KIMI_CODE_HOME', None)
    else:
        os.environ['KIMI_CODE_HOME'] = was_home

    print(f'theme-menu selfcheck: ok ({ok} checks)')
    return 0


def main() -> int:
    if '--selfcheck' in sys.argv:
        return _selfcheck()
    st = ThemeState()
    return m.loop(screen_themes(st), st)


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""The tweakkimi menu — everything adjustable, in one place.

tweakcc keeps its own `config.json` and applies it to the binary on demand, so
its banner has one thing to say: configured, not yet applied. Here the picture
is split in three, and the banner has to be honest about which part you are
looking at.

  * `config.toml` and `env-profile.conf` are read by Kimi and by the launcher.
    Change one and the next start picks it up — nothing to apply.
  * `patch-settings.conf` is read by the patches *while they are applied*, so a
    change there needs a patch run to take effect.
  * `patches/` and `system-prompts/` are compiled into the binary and do
    nothing at all until `kimi-patch.sh` runs.

So the banner only appears when something is genuinely outstanding, and it
names what. "Pending" is derived, never stored: the installed binary's mtime is
the timestamp of the last run, and anything newer has not reached it yet. No
state file to go stale, and it stays right even when a Kimi update replaces the
binary behind your back.

Navigation is by arrow key. Digits still work as shortcuts, but they are no
longer the way through.

usage: main-menu.py [--selfcheck] [--dry-run]
"""

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import patch_settings as ps                                  # noqa: E402
from keyreader import FakeKeys, Mouse, raw_mode, read_key, sgr  # noqa: E402
from oscruft import is_os_cruft, usable_files                # noqa: E402

PATCH_GLOB = '*.js'
CURSOR = '❯'                    # ❯, the tweakcc marker


def _load(name: str, filename: str):
    """Import a hyphenated sibling module by path."""
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# config-menu.py stays the owner of the TOML editing: it holds the lossless
# line editor, the key spellings, the tool catalogue and Kimi's own validator,
# all with their own self-check. The menu below imports it as a library rather
# than reimplementing any of that, and `--config-menu` remains a working alias.
cfg = _load('config_menu', 'config-menu.py')


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------


class State:
    """Everything the menu shows, derived from files rather than remembered."""

    def __init__(self, root: Path, status_text: str, binary: Path | None = None,
                 settings_path: Path | None = None, config_path: Path | None = None):
        self.root = root
        self.raw = status_text
        self.binary = binary or self._field('binary', Path('/nonexistent'), Path)
        self.version = self._field('version', 'unknown')
        self.binary_state = self._field('state', 'unknown')
        self.signature = self._field('signature', 'unknown')
        self.settings_path = settings_path or (root / 'patch-settings.conf')
        self.config_path = config_path or cfg.CONFIG

        m = re.search(r'^prompts\s*:\s*(\d+) extracted, (\d+) edited', self.raw, re.M)
        self.prompts_total, self.prompts_edited = (int(m.group(1)), int(m.group(2))) if m else (0, 0)

        self.patch_dir = root / 'patches'
        self.prompt_dir = root / 'system-prompts'
        self.patches = sorted(p for p in self.patch_dir.glob(PATCH_GLOB)
                              if not is_os_cruft(p.name)) if self.patch_dir.is_dir() else []
        self.is_patched = self.binary_state.startswith('patched')
        self.settings = ps.load(self.settings_path)

    def _field(self, name, default, cast=str):
        m = re.search(rf'^{name}\s*:\s*(.+?)\s*$', self.raw, re.M)
        return cast(m.group(1)) if m else default

    # -- pending work ------------------------------------------------------

    def changed_since_run(self) -> list[Path]:
        """Inputs modified after the binary was last written.

        The binary's mtime *is* the last-run timestamp: every successful run
        installs a freshly built file.
        """
        try:
            cutoff = self.binary.stat().st_mtime
        except OSError:
            return []
        out = [p for p in self.patches if p.stat().st_mtime > cutoff]
        if self.settings_path.exists() and self.settings_path.stat().st_mtime > cutoff:
            out.append(self.settings_path)
        if self.prompt_dir.is_dir():
            out += [p for p in usable_files(self.prompt_dir) if p.stat().st_mtime > cutoff]
        return out

    def pending(self) -> list[str]:
        reasons = []
        if not self.is_patched:
            if self.patches or self.prompts_edited:
                what = []
                if self.patches:
                    what.append(f'{len(self.patches)} patch(es)')
                if self.prompts_edited:
                    what.append(f'{self.prompts_edited} edited override(s)')
                reasons.append(f'the binary is not patched — {" and ".join(what)} waiting')
            return reasons

        if self.prompts_edited:
            reasons.append(f'{self.prompts_edited} prompt override(s) edited')
        changed = self.changed_since_run()
        if changed:
            names = ', '.join(sorted({p.name for p in changed})[:3])
            more = '' if len(changed) <= 3 else f' and {len(changed) - 3} more'
            reasons.append(f'{len(changed)} file(s) changed since the last run: {names}{more}')
        return reasons

    # -- patch-backed features --------------------------------------------

    def patch_file(self, *needles: str) -> Path | None:
        """The patch implementing a feature, matched loosely on its filename.

        Loose on purpose: the patches are written by hand and renamed freely,
        so binding the menu to an exact filename would break on a rename in a
        way nobody would connect to this file.
        """
        for p in self.patches:
            low = p.name.lower()
            if all(n in low for n in needles):
                return p
        return None

    def feature_note(self, patch: Path | None) -> str:
        """Why a patch-backed setting may not be doing anything yet."""
        if patch is None:
            return 'patch not installed'
        if not self.is_patched:
            return 'waiting for apply'
        try:
            if patch.stat().st_mtime > self.binary.stat().st_mtime:
                return 'waiting for apply'
            if self.settings_path.exists() and \
                    self.settings_path.stat().st_mtime > self.binary.stat().st_mtime:
                return 'waiting for apply'
        except OSError:
            return 'waiting for apply'
        return ''


def read_status(root: Path) -> str:
    r = subprocess.run([str(root / 'kimi-patch.sh'), '--status'],
                       capture_output=True, text=True)
    return r.stdout if r.stdout.strip() else r.stderr


def binary_path(state_raw: str) -> Path | None:
    m = re.search(r'^binary\s*:\s*(.+?)\s*$', state_raw, re.M)
    return Path(m.group(1)) if m else None


def env_value(root: Path, name: str) -> str | None:
    """One variable's value in the launcher profile, or None if unset."""
    profile = Path(os.environ.get('TWEAKKIMI_PROFILE', root / 'env-profile.conf'))
    try:
        text = profile.read_text()
    except OSError:
        return None
    for line in text.splitlines():
        if line.lstrip().startswith('#') or '=' not in line:
            continue
        key, _, val = line.partition('=')
        if key.strip() == name:
            return val.strip()
    return None


def env_count(root: Path) -> int:
    profile = Path(os.environ.get('TWEAKKIMI_PROFILE', root / 'env-profile.conf'))
    try:
        text = profile.read_text()
    except OSError:
        return 0
    return sum(1 for l in text.splitlines()
               if l.strip() and not l.lstrip().startswith('#') and '=' in l)


def config_summary(st: State) -> dict:
    """Tools, skills, permission and loop, straight from config.toml."""
    import tomllib
    try:
        data = tomllib.loads(st.config_path.read_text())
    except Exception:
        return {}
    return data


def terminal_rows() -> int:
    """The window height the patch will see, or its fallback."""
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 24


def suggestion_entries(level: str, rows: int | None = None) -> int:
    """How many entries a level yields, mirroring the patch's arithmetic.

    Computed rather than tabulated: the numbers depend on the window, and a
    fixed table would start lying the moment it is resized. The formulas match
    `patches/20-suggestion-list-half-height.js`; the 5 subtracted by `full` is
    the composer plus the status lines.
    """
    rows = rows if rows is not None else terminal_rows()
    if level == 'half':
        return min(rows // 2, max(1, rows - 5))
    if level == 'full':
        return max(1, rows - 5)
    return 5                                    # Kimi's own default


# --------------------------------------------------------------------------
# menu model
# --------------------------------------------------------------------------


class Item:
    """One row.

    `kind` decides what the arrow keys do:
      submenu  enter opens it
      cycle    left/right/enter step through `choices`, writing as they go
      action   enter runs it
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
        return self.kind != 'sep'


def build_items(st: State) -> list[Item]:
    data = config_summary(st)
    disabled = (data.get(cfg.S_TOOLS) or {}).get('disabled') or []
    extra = data.get(cfg.K_EXTRA_SKILL_DIRS) or []
    builtin = data.get(cfg.K_BUILTIN_SKILLS)
    perm = data.get(cfg.K_PERMISSION)
    loop = data.get(cfg.S_LOOP) or {}

    sugg_patch = st.patch_file('suggestion')
    wd_patch = st.patch_file('wd')
    click_patch = st.patch_file('cursor') or st.patch_file('click')

    def note_for(patch):
        return lambda s: s.feature_note(patch)

    items = [
        Item('submenu', 'System prompts',
             lambda s: f'{s.prompts_total} files, {s.prompts_edited} edited',
             key='prompts',
             help='View, price and migrate the overrides in system-prompts/.'),
        Item('submenu', 'Tools',
             lambda s: f'{len(disabled)} disabled' if disabled else 'none disabled',
             key='tools',
             help='Every tool description ships in every request; an unused tool is a per-turn tax.'),
        Item('submenu', 'Skills',
             lambda s: 'builtin off' if builtin is False else 'builtin on',
             key='skills',
             help='Kimi\'s builtin product skills, on or off.'),
        Item('submenu', 'Extra skill directories',
             lambda s: f'{len(extra)} configured' if extra else 'none',
             key='extradirs',
             help='Mount skill collections from elsewhere without copying them.'),
        Item('submenu', 'Merge skill directories',
             lambda s: ('on' if data.get(cfg.K_MERGE_SKILLS) is not False
                        else 'off') + '   [no effect in 0.36.0]',
             key='mergeskills',
             help='Search every brand directory or only the first — identical while each lists one.'),
        Item('submenu', 'Permission mode',
             lambda s: str(perm) if perm else 'manual (Kimi default)',
             key='permission',
             help='What Kimi does before running a tool call. yolo skips the prompt.'),
        Item('submenu', 'Loop control',
             lambda s: (f"{loop.get(cfg.K_ATTEMPTS, 3)} attempts, "
                        f"{loop.get(cfg.K_RESERVED, 50000)} reserved"),
             key='loop',
             help='Attempts per step, and context held back for the answer.'),

        Item('sep'),

        Item('cycle', 'Command suggestion',
             lambda s: (lambda lv: f'{lv}   ~{suggestion_entries(lv)} entries')(
                 s.settings.get('suggestion_height', 'default')),
             note_for(sugg_patch), key='suggestion_height',
             choices=ps.CHOICES['suggestion_height'],
             help='Height of the slash-command list: Kimi\'s five, half the window, or nearly full.'),
        Item('cycle', 'Fullscreen renderer',
             lambda s: 'always' if env_value(s.root, 'KIMI_CODE_TUI_FULL_SCREEN') == '1' else 'default',
             key='fullscreen', choices=['default', 'always'],
             help='Run Kimi in the alternate screen buffer. Applied by bin/kimi.'),
        Item('cycle', 'Working directory /wd',
             lambda s: s.settings.get('wd_command', 'off'),
             note_for(wd_patch), key='wd_command',
             choices=ps.CHOICES['wd_command'],
             help='Adds a /wd slash command for changing the working directory.'),
        Item('cycle', 'Click to position cursor',
             lambda s: s.settings.get('click_cursor', 'off'),
             note_for(click_patch), key='click_cursor',
             choices=ps.CHOICES['click_cursor'],
             help='Place the cursor in the composer with a mouse click.'),
        Item('submenu', 'Transcript window',
             lambda s: f'{env_count(s.root)} variable(s) set',
             key='display',
             help='How much history is re-sent each turn — the only lever on running cost.'),

        Item('sep'),

        Item('submenu', 'Patches',
             lambda s: f'{len(s.patches)} in patches/', key='patches',
             help='The JavaScript patches compiled into the binary.'),
        Item('action', 'Cost report', lambda s: 'what the prompts weigh', key='cost',
             help='Token cost per prompt, and what your edits have saved.'),

        Item('sep'),

        Item('action', 'Apply', lambda s: 'run kimi-patch.sh', key='apply',
             help='Extract, patch, repack, re-sign and install.'),
        Item('action', 'Restore', lambda s: 'put the pristine binary back', key='restore',
             help='Reinstall the untouched baseline binary.'),
        Item('action', 'Open config.toml', lambda s: '', key='open-config'),
        Item('action', 'Open env profile', lambda s: '', key='open-env'),
        Item('action', 'Open bundle', lambda s: '', key='open-bundle'),
        Item('action', 'Exit', lambda s: '', key='quit'),
    ]
    return items


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def banner(st: State) -> list[str]:
    reasons = st.pending()
    if not reasons:
        return []
    out = ['', '| Changes are waiting for a patch run.']
    for r in reasons:
        out.append(f'|   {r}')
    out.append('|  Run ./kimi-patch.sh, or pick Apply below.')
    return out


def render(st: State, items: list[Item], cursor: int,
           row_map: dict | None = None) -> list[str]:
    """The menu as lines, optionally recording which line each entry landed on.

    The mapping is built here rather than recomputed later, because here it is
    free: the index of the line about to be appended is simply `len(lines)`.
    Working it out afterwards would mean counting banner lines and separators a
    second time, in a second place, with a second chance of drifting apart.
    """
    lines = ['', 'tweakkimi',
             f'Kimi {st.version} — {st.binary_state}, {st.signature} signature']
    lines += banner(st)
    lines.append('')

    n = 0
    for i, it in enumerate(items):
        if it.kind == 'sep':
            lines.append('   ' + '─' * 66)
            continue
        n += 1
        mark = CURSOR if i == cursor else ' '
        value = it.value(st)
        note = it.note(st)
        if note:
            value = f'{value}   [{note}]' if value else f'[{note}]'
        arrows = ' ‹›' if it.kind == 'cycle' else '   '
        if row_map is not None:
            row_map[len(lines)] = i
        lines.append(f' {mark} {n:>2}  {it.label:<26}{arrows} {value}')

    lines.append('')
    sel = items[cursor] if 0 <= cursor < len(items) else None
    if sel is not None and sel.help:
        lines.append(f'   {sel.help}')
        lines.append('')
    lines.append('   ↑↓ or wheel move · enter or click open · ‹› change · q quit')
    return lines


def draw(st: State, items: list[Item], cursor: int) -> dict:
    """Paint the menu and return the line-to-entry mapping for the mouse.

    Clear-and-home puts the first line at screen row 0, which is what makes the
    mapping usable directly: a click's zero-based row *is* an index into the
    list that was just printed. That holds as long as the menu fits the window;
    on a very short terminal the top scrolls away and clicks land one entry off.
    """
    sys.stdout.write('\x1b[2J\x1b[H')
    row_map: dict[int, int] = {}
    print('\n'.join(render(st, items, cursor, row_map)))
    sys.stdout.flush()
    return row_map


# --------------------------------------------------------------------------
# actions
# --------------------------------------------------------------------------


def run(cmd: list[str], root: Path) -> None:
    """Hand the terminal over to a component, then come back."""
    subprocess.run(cmd, cwd=str(root))
    try:
        input('\n[enter] back to the menu ')
    except (EOFError, KeyboardInterrupt):
        print()


def open_file(path: Path) -> None:
    if not path.exists():
        print(f'not there: {path}')
        return
    editor = os.environ.get('VISUAL') or os.environ.get('EDITOR')
    subprocess.run([editor, str(path)] if editor else ['open', str(path)])


def config_item(st: State, item: str) -> None:
    """Open one entry of the TOML editor, which owns the writing."""
    run([sys.executable, str(HERE / 'config-menu.py'), '--item', item], st.root)


def menu_prompts(st: State) -> None:
    print('\nSystem prompts')
    print(f'   {st.prompts_total} files in system-prompts/, {st.prompts_edited} edited\n')
    print('   1  Cost report')
    print('   2  Re-extract from the binary')
    print('   3  Migrate onto a newly extracted tree')
    print('   q  back')
    try:
        c = input('\n > ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if c == '1':
        run([sys.executable, str(HERE / 'prompt-cost.py'), str(st.prompt_dir)], st.root)
    elif c == '2':
        run([str(st.root / 'kimi-patch.sh'), '--extract-prompts'], st.root)
    elif c == '3':
        tree = input('freshly extracted tree: ').strip()
        if tree:
            run([str(st.root / 'kimi-patch.sh'), '--migrate', tree], st.root)


def menu_display(st: State) -> None:
    """The transcript window — environment-only, applied by bin/kimi."""
    env = str(HERE / 'kimi-env.sh')
    print('\nTranscript window and other launcher variables')
    subprocess.run(['bash', env, 'show'])
    print('\n   1  Set a variable      2  Unset a variable      3  List what is accepted')
    print('   q  back')
    try:
        c = input('\n > ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if c == '1':
        name = input('variable: ').strip()
        val = input('value: ').strip()
        if name and val:
            subprocess.run(['bash', env, 'set', name, val])
            input('\n[enter] back ')
    elif c == '2':
        name = input('variable: ').strip()
        if name:
            subprocess.run(['bash', env, 'unset', name])
            input('\n[enter] back ')
    elif c == '3':
        subprocess.run(['bash', env, 'list'])
        input('\n[enter] back ')


def menu_patches(st: State) -> None:
    print('\nPatches in patches/')
    if not st.patches:
        print('   none')
    try:
        cutoff = st.binary.stat().st_mtime
    except OSError:
        cutoff = None
    for p in st.patches:
        if cutoff is None:
            mark = 'unknown'
        elif p.stat().st_mtime > cutoff:
            mark = 'changed since the last run'
        else:
            mark = 'in the binary' if st.is_patched else 'not applied'
        print(f'   {p.name:<46} {mark}')
    print('\n   Add a patch by dropping a .js file here; see the README for the shape.')
    try:
        input('\n[enter] back to the menu ')
    except (EOFError, KeyboardInterrupt):
        print()


def cycle_item(st: State, item: Item, forward: bool) -> None:
    """Advance a cycle entry and persist it where that setting lives."""
    if item.key == 'fullscreen':
        env = str(HERE / 'kimi-env.sh')
        now = env_value(st.root, 'KIMI_CODE_TUI_FULL_SCREEN') == '1'
        if now:
            subprocess.run(['bash', env, 'unset', 'KIMI_CODE_TUI_FULL_SCREEN'],
                           capture_output=True)
        else:
            subprocess.run(['bash', env, 'set', 'KIMI_CODE_TUI_FULL_SCREEN', '1'],
                           capture_output=True)
        return
    ps.cycle(item.key, forward, st.settings_path)


def activate(st: State, item: Item) -> bool:
    """Run an entry. Returns False when the menu should close."""
    k = item.key
    if k == 'quit':
        return False
    if k == 'prompts':
        menu_prompts(st)
    elif k == 'tools':
        config_item(st, '1')
    elif k == 'skills':
        config_item(st, '2')
    elif k == 'extradirs':
        config_item(st, '4')
    elif k == 'mergeskills':
        config_item(st, '3')
    elif k == 'permission':
        config_item(st, '5')
    elif k == 'loop':
        config_item(st, '6')
    elif k == 'display':
        menu_display(st)
    elif k == 'patches':
        menu_patches(st)
    elif k == 'cost':
        run([sys.executable, str(HERE / 'prompt-cost.py'), str(st.prompt_dir)], st.root)
    elif k == 'apply':
        run([str(st.root / 'kimi-patch.sh')], st.root)
    elif k == 'restore':
        run([str(st.root / 'kimi-patch.sh'), '--restore'], st.root)
    elif k == 'open-config':
        open_file(st.config_path)
    elif k == 'open-env':
        open_file(st.root / 'env-profile.conf')
    elif k == 'open-bundle':
        bundle = st.root / '.work' / 'bundle.js'
        if bundle.exists():
            open_file(bundle)
        else:
            print('no bundle yet — run ./kimi-patch.sh --extract')
    return True


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------


def first_selectable(items: list[Item], start: int = 0, step: int = 1) -> int:
    i = start
    for _ in range(len(items)):
        if 0 <= i < len(items) and items[i].selectable:
            return i
        i = (i + step) % len(items)
    return 0


def move(items: list[Item], cursor: int, step: int) -> int:
    """Next selectable row, wrapping, skipping separators."""
    i = cursor
    for _ in range(len(items)):
        i = (i + step) % len(items)
        if items[i].selectable:
            return i
    return cursor


def handle_mouse(st: State, items: list[Item], cursor: int,
                 ev: Mouse, row_map: dict) -> tuple[int, bool, bool]:
    """One click or wheel step. Same return shape as `handle`.

    A click both selects and acts, because a menu row is a button: making it
    select first and act on a second click would be a keyboard habit imposed on
    a pointer. Anything that is not an entry — header, banner, separator, the
    help line — is inert rather than treated as the nearest entry; guessing
    what a stray click meant is worse than doing nothing.
    """
    if ev.wheel_up:
        return move(items, cursor, -1), True, False
    if ev.wheel_down:
        return move(items, cursor, 1), True, False
    if not ev.is_left:                      # middle and right have no meaning here
        return cursor, True, False

    idx = row_map.get(ev.row)
    if idx is None or not (0 <= idx < len(items)) or not items[idx].selectable:
        return cursor, True, False

    item = items[idx]
    if item.kind == 'cycle':
        cycle_item(st, item, True)
        return idx, True, True
    return idx, activate(st, item), True


def handle(st: State, items: list[Item], cursor: int, key,
           row_map: dict | None = None) -> tuple[int, bool, bool]:
    """One keystroke or click. Returns (cursor, keep_running, needs_reload)."""
    if isinstance(key, Mouse):
        return handle_mouse(st, items, cursor, key, row_map or {})
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

    if key in ('left', 'right') and item is not None and item.kind == 'cycle':
        cycle_item(st, item, key == 'right')
        return cursor, True, True
    if key == 'enter' and item is not None:
        if item.kind == 'cycle':
            cycle_item(st, item, True)
            return cursor, True, True
        return cursor, activate(st, item), True

    if key.isdigit():
        want = int(key)
        n = 0
        for i, it in enumerate(items):
            if it.kind == 'sep':
                continue
            n += 1
            if n == want:
                return i, True, False
    return cursor, True, False


def interactive(root: Path) -> int:
    raw = read_status(root)
    st = State(root, raw, binary_path(raw))
    if st.version == 'unknown':
        print('Cannot read Kimi\'s state. Is it installed?\n')
        print(raw.strip()[:400])
        return 1

    items = build_items(st)
    cursor = first_selectable(items)

    if not sys.stdin.isatty():
        # No terminal: print the menu once and stop, rather than spinning on
        # EOF. Keeps `| less`, CI and `--dry-run` honest.
        print('\n'.join(render(st, items, cursor)))
        return 0

    while True:
        row_map = draw(st, items, cursor)
        # Raw mode and mouse tracking wrap the keystroke only. Everything an
        # entry may run — the TOML editor, kimi-patch.sh, an editor — reads
        # lines from this same terminal: cbreak mode would break their prompts,
        # and tracking left on would feed them escape sequences every time the
        # pointer moved. Switching both off between keystrokes costs a few
        # bytes and removes a whole class of interference.
        with raw_mode(mouse=True):
            key = read_key()
        cursor, keep, reload_ = handle(st, items, cursor, key, row_map)
        if not keep:
            break
        if reload_:
            raw = read_status(root)
            st = State(root, raw, binary_path(raw))
            items = build_items(st)
            cursor = min(cursor, len(items) - 1)
            if not items[cursor].selectable:
                cursor = first_selectable(items)
    print()
    return 0


# --------------------------------------------------------------------------
# selfcheck
# --------------------------------------------------------------------------


def _selfcheck() -> int:
    ok = 0

    def check(name, cond, detail=''):
        nonlocal ok
        if cond:
            ok += 1
        else:
            raise AssertionError(f'{name}: {detail}')

    patched = ('binary    : {bin}\n'
               'version   : 0.36.0\n'
               'state     : patched by tweakkimi\n'
               'signature : ad-hoc\n'
               'prompts   : 69 extracted, 0 edited (applied on the next run)\n')
    pristine = patched.replace('patched by tweakkimi', 'pristine (baseline, unpatched)')

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'patches').mkdir()
        (root / 'system-prompts').mkdir()
        settings = root / 'patch-settings.conf'
        config = root / 'config.toml'
        config.write_text('default_model = "kimi-code/k3"\n')
        binary = root / 'kimi-bin'
        binary.write_text('x')
        raw = patched.format(bin=binary)

        def state(text=None, bin_=None):
            return State(root, text or raw, bin_ or binary,
                         settings_path=settings, config_path=config)

        # -- state parsing and pending detection (as before) ---------------
        (root / 'patches' / '00-a.js').write_text('return js;')
        os.utime(root / 'patches' / '00-a.js', (1000, 1000))
        st = state()
        check('parse version', st.version == '0.36.0', st.version)
        check('parse prompts', (st.prompts_total, st.prompts_edited) == (69, 0))
        check('patched detected', st.is_patched)
        check('nothing pending', st.pending() == [], st.pending())
        check('no banner', banner(st) == [])

        newer = root / 'patches' / '10-b.js'
        newer.write_text('return js;')
        os.utime(newer, (2 ** 31, 2 ** 31))
        st = state()
        p = st.pending()
        check('changed file pending', len(p) == 1 and '10-b.js' in p[0], p)
        check('banner names the run', any('kimi-patch.sh' in l for l in banner(st)))

        os.utime(newer, (1000, 1000))
        st = state(raw.replace('69 extracted, 0 edited', '69 extracted, 3 edited'))
        check('edited override pending', any('3 prompt override' in r for r in st.pending()),
              st.pending())

        st = state(pristine.format(bin=binary))
        check('pristine is pending', any('not patched' in r for r in st.pending()), st.pending())
        check('pristine counts patches', '2 patch(es)' in st.pending()[0], st.pending())

        (root / 'patches' / '._sidecar.js').write_text('junk')
        st = state()
        check('sidecar ignored', len(st.patches) == 2, [p.name for p in st.patches])

        st = state(bin_=root / 'gone')
        check('missing binary tolerated', st.changed_since_run() == [])

        # -- patch-settings changes are pending too ------------------------
        settings.write_text('suggestion_height=half\n')
        os.utime(settings, (2 ** 31, 2 ** 31))
        st = state()
        check('settings change is pending',
              any('patch-settings.conf' in r for r in st.pending()), st.pending())
        os.utime(settings, (1000, 1000))

        # -- feature notes -------------------------------------------------
        st = state()
        check('missing patch reported', st.feature_note(None) == 'patch not installed')
        check('applied patch has no note', st.feature_note(root / 'patches' / '00-a.js') == '',
              st.feature_note(root / 'patches' / '00-a.js'))
        st_pristine = state(pristine.format(bin=binary))
        check('unpatched binary waits',
              st_pristine.feature_note(root / 'patches' / '00-a.js') == 'waiting for apply')

        # a patch is found by a loose name match, so renames do not break it
        (root / 'patches' / '20-suggestion-list-half-height.js').write_text('return js;')
        os.utime(root / 'patches' / '20-suggestion-list-half-height.js', (1000, 1000))
        st = state()
        check('patch located by name', st.patch_file('suggestion') is not None)
        check('absent patch is None', st.patch_file('nothing-like-this') is None)

        # -- navigation ----------------------------------------------------
        items = build_items(st)
        check('menu has entries', len([i for i in items if i.selectable]) >= 15)
        start = first_selectable(items)
        check('starts on a real row', items[start].selectable)

        pos = start
        pos, keep, _ = handle(st, items, pos, 'down')
        check('down moves', pos != start and keep)
        seps = [i for i, it in enumerate(items) if not it.selectable]
        for _ in range(len(items)):
            pos, _, _ = handle(st, items, pos, 'down')
            check('never lands on a separator', pos not in seps, pos)
        pos2, _, _ = handle(st, items, pos, 'up')
        check('up moves back', pos2 != pos)

        pos3, _, _ = handle(st, items, start, 'end')
        check('end jumps to the last row', items[pos3].selectable and pos3 > start)
        pos4, _, _ = handle(st, items, pos3, 'home')
        check('home returns to the first', pos4 == start)

        # digits still work as a shortcut
        pos5, _, _ = handle(st, items, start, '3')
        check('digit shortcut selects the third row', items[pos5].label == 'Skills',
              items[pos5].label)

        # q and friends leave
        for key in ('q', 'esc', 'ctrl-c', 'eof'):
            _, keep, _ = handle(st, items, start, key)
            check(f'{key} quits', keep is False)

        # -- value cycling writes through --------------------------------
        settings.write_text('')
        idx = next(i for i, it in enumerate(items) if it.key == 'suggestion_height')
        _, _, reload_ = handle(st, items, idx, 'right')
        check('cycling asks for a reload', reload_)
        check('cycle wrote half', ps.get('suggestion_height', settings) == 'half',
              ps.get('suggestion_height', settings))
        handle(st, items, idx, 'right')
        check('cycle advanced to full', ps.get('suggestion_height', settings) == 'full')
        handle(st, items, idx, 'left')
        check('left steps back', ps.get('suggestion_height', settings) == 'half')

        idx = next(i for i, it in enumerate(items) if it.key == 'wd_command')
        handle(st, items, idx, 'enter')
        check('enter cycles too', ps.get('wd_command', settings) == 'on')

        # the rendered value follows the file
        st = state()
        items = build_items(st)
        row = next(it for it in items if it.key == 'wd_command')
        check('value reflects the file', row.value(st) == 'on', row.value(st))

        # -- rendering -----------------------------------------------------
        out = '\n'.join(render(st, items, first_selectable(items)))
        check('cursor drawn', CURSOR in out)
        check('separators drawn', '─' * 10 in out)
        check('help line drawn', 'system-prompts/' in out)
        check('cycle rows show arrows', '‹›' in out)
        check('patch note shown for missing patch', 'patch not installed' in out, out[:400])

        # -- key decoding end to end --------------------------------------
        src = FakeKeys(['down', 'down', 'up', 'enter', 'q'])
        seq = [read_key(src) for _ in range(5)]
        check('scripted keys decode', seq == ['down', 'down', 'up', 'enter', 'q'], seq)

        # -- mouse ---------------------------------------------------------
        # The mapping is built by the same pass that draws, so it can be
        # checked against the drawn lines rather than against a second model.
        row_map: dict[int, int] = {}
        lines = render(st, items, first_selectable(items), row_map)
        check('every entry is mapped',
              len(row_map) == len([i for i in items if i.selectable]), len(row_map))
        for line_no, item_idx in row_map.items():
            check('mapped line holds its entry',
                  items[item_idx].label in lines[line_no],
                  f'line {line_no}: {lines[line_no]!r} vs {items[item_idx].label!r}')

        # Lines that are not entries must not be in the mapping at all.
        sep_lines = [n for n, l in enumerate(lines) if l.startswith('   ─')]
        check('separators are unmapped', all(n not in row_map for n in sep_lines))
        check('header is unmapped', 0 not in row_map and 1 not in row_map)

        # A click on an entry selects it; on a cycle row it also advances the
        # value, which is the one case that can be exercised without launching
        # a subprocess.
        settings.write_text('')
        idx = next(i for i, it in enumerate(items) if it.key == 'suggestion_height')
        line_no = next(n for n, i in row_map.items() if i == idx)
        pos, keep, reload_ = handle(st, items, 0, Mouse(0, 5, line_no, False), row_map)
        check('click selects the clicked row', pos == idx, pos)
        check('click on a cycle row advances it',
              ps.get('suggestion_height', settings) == 'half',
              ps.get('suggestion_height', settings))
        check('click asks for a reload', reload_ and keep)

        # A click anywhere else is inert — it must not move the cursor and
        # must not act.
        before = ps.get('suggestion_height', settings)
        for dead in (0, 1, sep_lines[0] if sep_lines else len(lines) - 1, len(lines) - 1):
            pos2, keep2, reload2 = handle(st, items, idx, Mouse(0, 3, dead, False), row_map)
            check(f'click on line {dead} does nothing',
                  (pos2, keep2, reload2) == (idx, True, False), (pos2, keep2, reload2))
        check('inert clicks changed no setting',
              ps.get('suggestion_height', settings) == before)

        # A click far below the menu maps to nothing.
        pos3, _, _ = handle(st, items, idx, Mouse(0, 0, 999, False), row_map)
        check('click past the end is inert', pos3 == idx)

        # Buttons other than the left one are ignored.
        pos4, _, reload4 = handle(st, items, idx, Mouse(2, 5, line_no, False), row_map)
        check('right button ignored', pos4 == idx and not reload4)

        # The wheel moves the selection without acting on anything.
        start = first_selectable(items)
        posw, _, reloadw = handle(st, items, start, Mouse(65, 0, 0, True), row_map)
        check('wheel down moves', posw != start and not reloadw, posw)
        posu, _, _ = handle(st, items, posw, Mouse(64, 0, 0, True), row_map)
        check('wheel up moves back', posu == start, posu)

        # End to end: the bytes a terminal sends for a click on that row are
        # decoded and dispatched to the same entry.
        settings.write_text('')
        ev = read_key(FakeKeys([sgr(0, 5, line_no, press=True), sgr(0, 5, line_no)]))
        check('click bytes decode to a Mouse', isinstance(ev, Mouse), ev)
        pos5, _, _ = handle(st, items, 0, ev, row_map)
        check('decoded click reaches the entry', pos5 == idx, pos5)

        # -- suggestion levels mirror the patch's arithmetic ---------------
        # The patch computes: half = min(floor(rows/2), max(1, rows-5)),
        # full = max(1, rows-5), default = Kimi's five.
        check('default is five', suggestion_entries('default', 44) == 5)
        check('half of a 44-row window', suggestion_entries('half', 44) == 22)
        check('full of a 44-row window', suggestion_entries('full', 44) == 39)
        # On a tiny window `half` is clamped by the chrome allowance, not by
        # the halving — the same order the patch applies.
        check('half clamped on a short window', suggestion_entries('half', 8) == 3,
              suggestion_entries('half', 8))
        check('full never returns zero', suggestion_entries('full', 3) == 1)

    print(f'main-menu selfcheck: ok ({ok} checks)')
    return 0


def main() -> int:
    args = sys.argv[1:]
    if '--selfcheck' in args:
        return _selfcheck()
    if '--dry-run' in args:
        raw = read_status(ROOT)
        st = State(ROOT, raw, binary_path(raw))
        items = build_items(st)
        print('\n'.join(render(st, items, first_selectable(items))))
        return 0
    return interactive(ROOT)


if __name__ == '__main__':
    sys.exit(main())

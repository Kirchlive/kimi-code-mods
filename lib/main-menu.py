#!/usr/bin/env python3
"""The kimi-code-mods menu — everything adjustable, in one place.

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

import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import menu as m                                             # noqa: E402
import patch_settings as ps                                  # noqa: E402
from keyreader import (FakeKeys, Mouse, drain_input,        # noqa: E402
                       read_key, sgr)
from menu import Item, first_selectable, move                # noqa: E402
from oscruft import is_os_cruft, usable_files                # noqa: E402

PATCH_GLOB = '*.js'
CURSOR = m.CURSOR               # ❯, the tweakcc marker

# The one thing a row still has to say about its patch. "Waiting for apply" is
# not: the banner at the top of the menu already says a run is outstanding,
# and repeating it against every changed row buried the two states worth
# telling apart — untouched, and everything else. A missing patch is different
# in kind: the row cannot ever do anything, however it is set.
NO_PATCH = 'patch not installed'


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

# The theme editor is its own module for the same reason: it owns the schema
# Kimi's loader enforces, and validating a colour in two places would mean
# disagreeing about it eventually.
themes = _load('theme_menu', 'theme-menu.py')


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
        self.status_key = status_key(self.root, self.binary)

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
            return NO_PATCH
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


def status_key(root: Path, binary: Path) -> tuple:
    """What `kimi-patch.sh --status` could possibly have to say something new about.

    Asking it costs six seconds, because deciding whether the installed binary
    is one of ours means hashing 180 MB of it. The menu asks after every
    action, so changing a permission mode used to be followed by a six-second
    pause on a screen that had already been redrawn — which reads as the menu
    hanging, and is the reason this exists.

    Everything in that answer is derived from two things: the installed binary,
    and the prompt overrides. Neither changes when you edit `config.toml`, the
    launcher profile or a patch switch, so the answer is reused whenever both
    are untouched. Cheap to compute, and wrong only if something rewrites the
    binary with the same size and timestamp.
    """
    try:
        s = binary.stat()
        binary_stamp = (s.st_mtime, s.st_size)
    except OSError:
        binary_stamp = None
    prompts = root / 'system-prompts'
    newest = max((f.stat().st_mtime for f in usable_files(prompts)), default=0.0) \
        if prompts.is_dir() else 0.0
    return (binary_stamp, newest)


def binary_path(state_raw: str) -> Path | None:
    m = re.search(r'^binary\s*:\s*(.+?)\s*$', state_raw, re.M)
    return Path(m.group(1)) if m else None


def env_value(root: Path, name: str) -> str | None:
    """One variable's value in the launcher profile, or None if unset."""
    profile = Path(os.environ.get('KIMICODEMODS_PROFILE', root / 'env-profile.conf'))
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
    profile = Path(os.environ.get('KIMICODEMODS_PROFILE', root / 'env-profile.conf'))
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


def group_value(st: State, keys: list[str]) -> str:
    """What a group of switches shows on its root row.

    One switch shows its value. Several show only the ones that are no longer
    at their default, because a row reading "default, default, off" says
    nothing while "braille, 80" says exactly what you changed.
    """
    if len(keys) == 1:
        return str(st.settings.get(keys[0], ps.DEFAULTS[keys[0]]))
    changed = [str(st.settings.get(k, ps.DEFAULTS[k])) for k in keys
               if st.settings.get(k, ps.DEFAULTS[k]) != ps.DEFAULTS[k]]
    if not changed:
        return 'default'
    # Two values still read as values. More than that and a list of bare
    # settings ("full, on, on") says less than its own length does.
    return ', '.join(changed) if len(changed) <= 2 else f'{len(changed)} changed'


def build_items(st: State) -> list[Item]:
    data = config_summary(st)
    disabled = (data.get(cfg.S_TOOLS) or {}).get('disabled') or []
    builtin = data.get(cfg.K_BUILTIN_SKILLS)
    extra = data.get(cfg.K_EXTRA_SKILL_DIRS) or []
    perm = data.get(cfg.K_PERMISSION)
    loop = data.get(cfg.S_LOOP) or {}

    def switches(group: str):
        """The value cell for a group row, read from patch-settings.conf."""
        keys = SETTING_GROUPS[group][1]
        return lambda s: group_value(s, keys)

    def group_note(group: str, value_fn=None):
        """`default` for an untouched group, otherwise whether it is live yet."""
        keys = SETTING_GROUPS[group][1]
        needles = {PATCH_HELP[k][2] for k in keys}
        patches = [st.patch_file(n) for n in sorted(needles)]
        if any(p is None for p in patches):
            live = lambda s: 'patch not installed'                    # noqa: E731
        else:
            live = lambda s: next(                                     # noqa: E731
                (n for n in (s.feature_note(p) for p in patches) if n), '')
        return value_note(value_fn or switches(group), at_default(*keys), live)

    # The order is tweakcc's, so that muscle memory carries over from it: the
    # appearance settings first, then the model and routing ones, then Kimi's
    # own configuration, and the doors out at the bottom. Two tweakcc entries
    # have nothing behind them here — Fable plan mode and Better Claude in
    # Chrome are Claude-only — and their places are taken by the two settings
    # tweakcc has no equivalent for, tool and hook setup.
    # No values here. Every one of these rows opens a screen that shows the
    # same setting in full, so a summary beside the label is the same fact
    # twice — and the summaries were what pushed the notes, and then the
    # explanations, off the end of the line. What the row you are on is *for*
    # is the thing worth saying, and it is said on the row itself.
    items = [
        Item('submenu', 'Themes', key='themes',
             help='Modify Kimi Code\'s built-in themes or create your own.'),
        Item('submenu', 'Thinking verbs', key='verbs',
             help='Rotate the word beside the spinner instead of always saying "working".'),
        Item('submenu', 'Thinking style', key='style',
             help='The spinner while Kimi thinks and composes, and how fast it turns.'),
        Item('submenu', 'Working style', key='working',
             help='The spinner while Kimi waits on the model or a tool, not '
                  'while it thinks.'),
        Item('submenu', 'User message display', key='usermsg',
             help='How your own messages are drawn in the transcript.'),
        Item('submenu', 'Misc', key='misc',
             help='The switches that belong to no group of their own.'),
        Item('submenu', 'Toolsets', key='toolsets',
             help='Named lists of disabled tools, applied in one keystroke.'),
        Item('submenu', 'Subagent models', key='subagent',
             help='Which model a subagent runs on. Needs the secondary-model flag.'),
        Item('submenu', 'Complexity effort router', key='router',
             help='Set reasoning effort per turn from the prompt. pin only ever raises it.'),
        Item('submenu', 'Tool setup', key='tools',
             help='Every tool description ships in every request; an unused tool is a tax.'),
        Item('submenu', 'AGENTS.md alternative names', key='agentsmd',
             help='Also read CLAUDE.md and friends. AGENTS.md keeps priority.'),
        Item('submenu', 'Skill setup', key='skills',
             help='Kimi\'s own product skills, and where else skills are read from.'),
        Item('submenu', 'Hook setup', key='hooks',
             help='Run a shell command on one of Kimi\'s 20 events.'),
        Item('submenu', 'Loop control', key='loop',
             help='Attempts per step, and context held back for the answer.'),
        Item('submenu', 'Reasoning', key='thinking',
             help='How hard the model thinks, and whether thinking is re-sent.'),
        Item('submenu', 'Transcript window', key='display',
             help='How much history is re-sent each turn — the only lever on running cost.'),
        Item('submenu', 'Patches', key='patches',
             help='The JavaScript patches compiled into the binary.'),
        Item('action', 'Cost report', key='cost',
             help='Token cost per prompt, and what your edits have saved.'),
        Item('submenu', 'View system prompts', key='prompts',
             help='View, price and migrate the overrides in system-prompts/.'),

        Item('sep'),

        Item('action', 'Apply', lambda s: 'run kimi-patch.sh', key='apply',
             help='Extract, patch, repack, re-sign and install.'),
        Item('action', 'Restore original Kimi Code',
             lambda s: 'keeps your settings', key='restore',
             help='Reinstall the untouched baseline binary. Nothing you configured is lost.'),
        Item('action', 'Open config.toml', lambda s: '', key='open-config'),
        Item('action', 'Open env profile', lambda s: '', key='open-env'),
        Item('action', 'Open Kimi Code\'s bundle.js', lambda s: '', key='open-bundle'),
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


def header(st: State) -> list[str]:
    """tweakcc's three-line opening, saying what is true here.

    The one line tweakcc uses to say where its settings go has to name three
    places here rather than one file, so it names the directory that holds
    them: `patch-settings.conf`, `env-profile.conf`, `patches/` and
    `system-prompts/` all live in it. `config.toml` is Kimi's own and stays
    where Kimi reads it, which is why it is named separately.
    """
    return ['', ' kimi-code-mods', '',
            f'{m.SPIN_SLOT} Customize your Kimi Code installation. Settings will '
            f'be saved to {tilde(st.root)} and {tilde(st.config_path)}.', '',
            f' Kimi {st.version} — {st.binary_state}, {st.signature} signature'] + banner(st)


def tilde(path: Path) -> str:
    """`~/…` where that is shorter, because a home path is noise."""
    try:
        return '~/' + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def reload_state(st: State) -> State:
    """The state again, asking the patcher only when it could have new news.

    A fresh `State` is built either way: the patches, the switches and the
    config are read from disk every time, which is what makes an edit made in
    an external editor show up the moment you come back.
    """
    if status_key(st.root, st.binary) == st.status_key:
        return State(st.root, st.raw, st.binary, st.settings_path, st.config_path)
    raw = read_status(st.root)
    return State(st.root, raw, binary_path(raw), st.settings_path, st.config_path)


# The root screen. Everything about drawing, arrow keys, the wheel and clicks
# lives in menu.py; what stays here is only what is specific to this screen.
SCREEN = m.Screen(build=lambda st: build_items(st), header=header,
                  activate=lambda st, item: activate(st, item),
                  cycle=lambda st, item, fwd: cycle_item(st, item, fwd),
                  reload=reload_state, inline_help=True, help_line=m.HELP_ROOT)


def render(st: State, items: list[Item], cursor: int,
           row_map: dict | None = None) -> list[str]:
    return m.render(SCREEN, st, items, cursor, row_map)


def draw(st: State, items: list[Item], cursor: int) -> dict:
    return m.draw(SCREEN, st, items, cursor)


# --------------------------------------------------------------------------
# actions
# --------------------------------------------------------------------------


def run(cmd: list[str], root: Path, wait: bool = True,
        hold: float = 0.0) -> None:
    """Hand the terminal over to a component, then come back.

    `wait` is for the commands whose output *is* the result — a cost report is
    read on screen and nowhere else, so the menu waits before repainting over
    it. A patch run reports its own outcome in the header you come back to, so
    it returns straight to the menu.

    Either way the input queue is dropped: a command that ran for a minute has
    collected every key pressed at it, and the menu must not read them.

    The screen is cleared first, so the command starts on a blank one. Without
    that its output lands wherever the cursor happens to be — and since the
    header's moon leaves it parked in line four, a patch run overwrote the
    menu row by row instead of replacing it.
    """
    m.clear_screen()
    sys.stdout.flush()
    subprocess.run(cmd, cwd=str(root))
    drain_input()
    if wait:
        m.press_any()
    elif hold:
        # Long enough to read the summary the command printed, short enough
        # that nobody waits on it: any key returns to the menu at once.
        m.hold_for(hold)


def open_file(path: Path) -> None:
    if not path.exists():
        print(f'not there: {path}')
        return
    editor = os.environ.get('VISUAL') or os.environ.get('EDITOR')
    # Same reason as `run`: an editor taking over the terminal should find it
    # empty rather than draw itself over half a menu.
    m.clear_screen()
    sys.stdout.flush()
    subprocess.run([editor, str(path)] if editor else ['open', str(path)])


# Paths already backed up in this run. A row that writes on every ‹› would
# otherwise leave a backup per keystroke, and three presses to walk a list of
# three is a normal thing to do. One copy per session is the state worth
# keeping anyway: how the file looked before you started.
_backed_up: set[Path] = set()


def write_config_value(st: State, section: str, key: str, value) -> str:
    """Set or remove one `config.toml` key, straight away.

    The deliberate omission is `kimi doctor`. It takes about 1.7 seconds, and
    this is called from rows you step through with an arrow key — three
    presses would be five seconds of waiting to walk a list of three. What
    makes that safe is the shape of these particular settings: the value comes
    from a list taken out of Kimi's own schema rather than from a field, and
    the line editor touches nothing but that one line. Anything typed still
    goes through the full path in `config_item`, validator included.
    """
    path = st.config_path
    original = path.read_text() if path.exists() else ''
    editing = cfg.Editing(path, cfg.TomlLines(original), dry_run=False)
    if value is None:
        editing.doc.remove(section, key)
    else:
        editing.doc.set(section, key, cfg.lit(value))
    text = editing.doc.text()
    if text == original:
        return ''
    try:
        if path.exists() and path not in _backed_up:
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            shutil.copy2(path, path.with_suffix(f'.toml.kimi-code-mods-{stamp}.bak'))
            _backed_up.add(path)
        path.write_text(text)
    except OSError as e:
        return str(e)
    return ''


def config_item(st: State, item: str) -> None:
    """Open one config.toml screen inside this process, and write what changed.

    It used to be a subprocess. That put a process boundary in the middle of a
    keystroke, and the boundary was visible: `--item N` opens the screen, but
    when you left it the editor fell into *its own* top-level menu — a
    different title, a different row set, a "Write changes" row — so coming
    back from a setting landed you somewhere you had never chosen to go.

    In-process there is no second menu to fall into: the screen returns here,
    to the row you opened it from. The cost is that the editor's deferred write
    has to be resolved here instead, and it is resolved the way the rest of
    kimi-code-mods behaves — a change to a setting is written when you leave the
    screen that made it. `config-menu.py` run on its own keeps its Write row;
    that is its interface, and this is ours.
    """
    original = st.config_path.read_text() if st.config_path.exists() else ''
    editing = cfg.Editing(st.config_path, cfg.TomlLines(original), dry_run=False)
    cfg.open_item(editing, item)
    if editing.doc.text() == original:
        return
    # `commit` prints the diff, keeps a backup and runs Kimi's own validator,
    # which is the one thing that must not be skipped: a rejected file is
    # rolled back and the reason only exists on screen. A successful write
    # needs no acknowledgement — the value it changed is visible in the row
    # you came back to.
    if not cfg.commit(st.config_path, editing.doc.text(), False):
        m.press_any()


def ask(title: str, value: str = '', hint: str = '', width: int | None = None):
    """One typed value, in a field. `None` means the user changed their mind.

    Never `input()`: a line read in cooked mode takes an arrow key as the
    bytes of its escape sequence and hands them back inside the string. See
    `menu.field`, which is where that crash is explained and prevented.

    `width` is the field's own width, for the values that are known to be
    short. A marker is one character; a box wide enough for a command line
    around it suggests there is more to say than there is.
    """
    return m.field(title, value, hint, width) if width else m.field(title, value, hint)


def sub(screen: m.Screen, st: State) -> None:
    """Run a submenu, then repaint the caller's screen on the way out."""
    m.loop(screen, st)


def screen_prompts(st: State) -> m.Screen:
    def build(s: State) -> list[Item]:
        return [
            Item('info', f'{s.prompts_total} files in system-prompts/, '
                         f'{s.prompts_edited} edited'),
            Item('sep'),
            Item('action', 'Cost report', lambda x: 'what the prompts weigh',
                 key='cost', help='Token cost per prompt, and what your edits have saved.'),
            Item('action', 'Re-extract from the binary', lambda x: '', key='extract',
                 help='Writes to system-prompts.<version>.new/ when a tree already exists.'),
            Item('action', 'Migrate onto a new tree', lambda x: '', key='migrate',
                 help='Three-way merge of your overrides onto freshly extracted prompts.'),
            Item('action', 'Open the prompt directory', lambda x: '', key='open'),
            Item('sep'),
            Item('action', 'Back', lambda x: '', key='back'),
        ]

    def act(s: State, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key == 'cost':
            run([sys.executable, str(HERE / 'prompt-cost.py'), str(s.prompt_dir)], s.root)
        elif item.key == 'extract':
            run([str(s.root / 'kimi-patch.sh'), '--extract-prompts'], s.root)
        elif item.key == 'migrate':
            tree = ask('Freshly extracted tree',
                       hint='The directory --extract-prompts wrote, '
                            'e.g. system-prompts.0.36.0.new')
            if tree:
                run([str(s.root / 'kimi-patch.sh'), '--migrate', tree], s.root)
        elif item.key == 'open':
            open_file(s.prompt_dir)
        return True

    return m.Screen(build, activate=act, reload=reload_state,
                    title='System prompts')


def env_rows(root: Path) -> list[tuple[str, str]]:
    """Every variable the launcher accepts, with its value in the profile."""
    r = subprocess.run(['bash', str(HERE / 'kimi-env.sh'), 'list'],
                       capture_output=True, text=True)
    names = []
    for line in r.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    return [(n, env_value(root, n) or '') for n in names]


def screen_display(st: State) -> m.Screen:
    """The launcher's environment profile, one row per accepted variable."""
    env = str(HERE / 'kimi-env.sh')

    def build(s: State) -> list[Item]:
        rows = [Item('info', 'enter sets a value, backspace clears it; '
                             'cleared means Kimi\'s own default'),
                Item('sep')]
        for name, value in env_rows(s.root):
            rows.append(Item('action', name,
                             (lambda v: lambda x: v or '—')(value),
                             key=f'env:{name}', on_delete=clear))
        rows += [Item('sep'), Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def act(s: State, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key.startswith('env:'):
            name = item.key[4:]
            current = env_value(s.root, name) or ''
            val = ask(name, current, hint='Escape leaves it as it is; '
                                          'backspace on the row clears it.')
            if val is None:
                return True
            if val:
                subprocess.run(['bash', env, 'set', name, val])
            else:
                subprocess.run(['bash', env, 'unset', name], capture_output=True)
        return True

    def clear(s: State, item: Item) -> None:
        if item.key.startswith('env:'):
            subprocess.run(['bash', env, 'unset', item.key[4:]], capture_output=True)

    return m.Screen(build, activate=act, reload=reload_state,
                    help_line=m.HELP_DEL, title='Launcher environment')


# Every patch-backed switch, with the sentence that explains what it costs.
# The table is keyed by the setting rather than by the patch file, because the
# setting is what the menu writes and what the patch reads; a patch renamed or
# split in two changes nothing here.
#
# Anything in `ps.CHOICES` missing from this table is still offered, without
# help text and marked as such. That is deliberate: a new patch is usable the
# moment it registers its default, and the gap is visible instead of silent,
# which is what a hardcoded list of rows would have made it.
PATCH_HELP = {
    'suggestion_height': (
        'Command suggestions',
        'Height of the slash-command list: Kimi\'s five, half the window, or nearly full.', 'suggestion'),
    'wd_command': (
        'Working directory /wd',
        'Adds a /wd slash command that starts a session in another directory.', 'wd'),
    'click_cursor': (
        'Click to position cursor',
        'Place the cursor in the composer with a mouse click. Fullscreen only.', 'click'),
    'agents_md_names': (
        'Project instruction files',
        'Also read CLAUDE.md and friends. AGENTS.md keeps priority; one file per directory.', 'agents-md'),
    'read_line_numbers': (
        'Line numbers in Read',
        'Off saves tokens on every read, and costs the model the ability to cite a line.', 'line-numbers'),
    'expanded_by_default': (
        'Expanded by default',
        'Show thinking blocks and tool output unfolded. Costs screen, not tokens.', 'expanded'),
    'read_limits': (
        'Read limits',
        'How much one Read returns. Higher trades round trips for context.', 'read-limits'),
    'auto_accept_plan': (
        'Auto-accept plans',
        'Skip the plan approval prompt. A multi-option plan then has no option chosen.', 'auto-accept'),
    'effort_router': (
        'Effort router',
        'Set reasoning effort per turn from the prompt. pin only ever raises it.', 'effort-router'),
    'spinner_style': (
        'Spinner shape',
        'Which characters the working indicator cycles through.', 'spinner'),
    'spinner_interval_ms': (
        'Spinner speed',
        'Milliseconds per frame, 20 to 2000. Lower is faster.', 'spinner'),
    'thinking_verbs': (
        'Thinking verbs',
        'Rotate the word beside the spinner instead of always saying "working".', 'verbs'),
    'thinking_verbs_list': (
        'Thinking verb list',
        'The words to rotate through. `default` uses the patch\'s own list.', 'verbs'),
    'thinking_verbs_format': (
        'Thinking verb format',
        'Where the word goes; {} is the word.', 'verbs'),
    'working_style': (
        'Working spinner',
        'The spinner while Kimi waits on the model or a tool, not while it '
        'thinks.', 'spinner'),
    'working_mirror': (
        'Reverse-mirror run',
        'Run the working frames forwards then backwards, so the spinner swings '
        'instead of jumping back to the first.', 'spinner'),
    'working_frames': (
        'Your own working frames',
        'The frames the working spinner\'s `custom` style uses. Separate with '
        'spaces.', 'spinner'),
    'spinner_frames': (
        'Your own spinner frames',
        'The frames the `custom` style uses. Separate with spaces.', 'spinner'),
    'spinner_mirror': (
        'Reverse-mirror run',
        'Run the frames forwards then backwards, so the spinner swings '
        'instead of jumping back to the first.', 'spinner'),
    'user_message_marker': (
        'Your message marker',
        'The prefix in front of what you typed. Kimi\'s own is a sparkle.', 'user-message'),
    'user_message_border': (
        'Your message border',
        'Draw a frame around your own messages in the transcript.', 'user-message'),
    'user_message_style': (
        'Your message style',
        'How your own text is drawn. Kimi\'s own is bold.', 'user-message'),
    'welcome_banner': (
        'Welcome banner',
        'Greet with "Welcome to Kimi Code Mods!" and give the logo its horns.',
        'welcome-banner'),
    'fullscreen': (
        'Fullscreen renderer',
        'Draw Kimi in the alternate screen buffer, however it was started. '
        'The shell keeps its scrollback; Kimi\'s is gone when it exits.',
        'fullscreen'),
    'input_box_border': (
        'Composer border',
        'The frame around the input box. off leaves the space blank.', 'input-box'),
    'cron_drop_dir': (
        'Cron drop directory',
        'Fire JSON files dropped into <sessionDir>/cron/ as one-shot cron '
        'turns. For an external bus daemon; nothing typed reaches the session.',
        'cron-drop'),
}


# The patch switches, split into the screens tweakcc splits them into. Every
# key in `ps.DEFAULTS` belongs to exactly one group; the self-check proves it,
# so a switch cannot be registered and then be unreachable from the menu — the
# failure a single "Patch settings" screen made impossible and this split
# makes possible again.
SETTING_GROUPS: dict[str, tuple[str, list[str]]] = {
    'verbs': ('Thinking verbs', ['thinking_verbs', 'thinking_verbs_list',
                                 'thinking_verbs_format']),
    'style': ('Thinking style', ['spinner_style', 'spinner_interval_ms',
                                 'spinner_frames', 'spinner_mirror']),
    'working': ('Working style', ['working_style', 'working_frames',
                                  'working_mirror']),
    'usermsg': ('User message display', ['user_message_marker',
                                         'user_message_border',
                                         'user_message_style']),
    'router': ('Complexity effort router', ['effort_router']),
    'agentsmd': ('AGENTS.md alternative names', ['agents_md_names']),
    'misc': ('Miscellaneous settings', ['suggestion_height', 'wd_command',
                                        'click_cursor', 'read_line_numbers',
                                        'expanded_by_default', 'read_limits',
                                        'auto_accept_plan', 'input_box_border',
                                        'fullscreen', 'welcome_banner',
                                        'cron_drop_dir']),
}

# tweakcc draws a two-state switch as a checkbox and everything else as its
# value. Worth copying: a checkbox is read without reading, and a switch with
# four states cannot be one honestly.
BOX = {'on': '☑ Enabled', 'off': '☐ Disabled'}


def default_note(value_text) -> str:
    """`default` beside a value, unless the value already says so.

    A row reading `default   [default]` says one thing twice, which is worse
    than either half on its own — it reads as though the two were different
    facts.
    """
    return '' if 'default' in str(value_text).lower() else 'default'


def value_note(value_fn, at_default_fn, live_note_fn):
    """The note beside a value: `default` when untouched, otherwise why it is
    not in effect yet.

    Two states are worth telling apart and only two: a row still on Kimi's own
    value, and a row that is not. The first says `default`; the second says
    nothing, because the value it is showing *is* what changed. `waiting for
    apply` said the same thing beside every changed row as the banner says
    once at the top of the menu, which left the notes carrying no information
    at all.
    """
    def read(st):
        if at_default_fn(st):
            return default_note(value_fn(st))
        # Changed: the value speaks for itself. Only a patch that is not
        # there at all is worth a word, because that is a row which cannot
        # work rather than one that has not been applied yet.
        return NO_PATCH if live_note_fn(st) == NO_PATCH else ''
    return read


def at_default(*keys: str):
    """Whether every one of these switches is still on Kimi's own value."""
    return lambda st: all(str(st.settings.get(k, ps.DEFAULTS[k]))
                          == str(ps.DEFAULTS[k]) for k in keys)


# What Kimi's own value actually is, where the setting spells it `default`.
# A row reading `default` names the fact that nothing was changed twice — the
# note beside it already says that — while saying nothing about what Kimi
# will do. These are the words for what it does.
DEFAULT_MEANS = {
    'user_message_style': 'bold',
    'suggestion_height': 'five',
    'read_limits': '1000 lines',
    'spinner_style': 'braille',
    'spinner_interval_ms': '80/120 ms',
    'input_box_border': 'round',
    'spinner_frames': '—',
    'thinking_verbs_list': 'built-in',
}


def restore_default(st, item) -> None:
    """Backspace on any switch puts Kimi's own value back.

    One key, one meaning, on every screen: ‹› changes a value, backspace
    removes what you did to it. Before this it worked on some rows and not
    others, which is worse than not having it — a key that does nothing on
    the row you are on reads as a key that does nothing.
    """
    if item.key in ps.DEFAULTS:
        ps.set_value(item.key, ps.DEFAULTS[item.key], st.settings_path)


def switch_value(key: str):
    """The value cell for one switch, as a checkbox where that is truthful."""
    two_state = set(ps.CHOICES.get(key) or []) == {'on', 'off'}

    def read(st: State) -> str:
        raw = str(st.settings.get(key, ps.DEFAULTS.get(key, '')))
        if raw == 'default' and key in DEFAULT_MEANS:
            return DEFAULT_MEANS[key]
        return BOX.get(raw, raw) if two_state else raw
    return read


def screen_settings(st: State, group: str) -> m.Screen:
    """One screen of patch switches — a group of `SETTING_GROUPS`."""
    title, keys = SETTING_GROUPS[group]

    def build(s: State) -> list[Item]:
        rows = [Item('info', 'read while the patches are applied — '
                             'a change here needs a patch run'),
                Item('sep')]
        for key in keys:
            label, help_text, needle = PATCH_HELP.get(
                key, (key.replace('_', ' ').capitalize(),
                      'No description registered in PATCH_HELP yet.', key.split('_')[0]))
            patch = s.patch_file(needle)
            value = switch_value(key)
            note = value_note(value, at_default(key),
                              (lambda q: lambda x: x.feature_note(q))(patch))
            if key in ps.CHOICES:
                rows.append(Item('cycle', label, value, note,
                                 key=key, choices=ps.CHOICES[key], help=help_text))
            else:
                # No list can hold a prefix or a set of frames, so this one is
                # typed — in the row itself, where the value it replaces is.
                rows.append(Item('action', label, value, note, key=key,
                                 edit_start=(lambda k: lambda x, i: str(
                                     x.settings.get(k, ps.DEFAULTS[k])))(key),
                                 on_edit=free_text_edit,
                                 help=help_text + '  (enter types a value)'))
        # Everything else on the root menu opens a screen of its own. The
        # fullscreen renderer never did — it was one switch sitting among the
        # doors — so it belongs here with the other switches. It is the one
        # row on this screen the patches do not read: `bin/kimi` exports it,
        # so it takes effect at the next start with no patch run at all.
        if group == 'misc':
            # Two rows here are not patch switches. Both are settings you
            # step through rather than doors into a screen, which is what
            # they have in common with everything else on this list — and
            # what they did not have in common with the root menu. They go
            # under a rule of their own, because the line at the top of this
            # screen does not describe them: neither waits for a patch run.
            rows.append(Item('sep'))
            rows.append(Item('info', 'read by Kimi and the launcher, not by a '
                                     'patch — no patch run needed'))
            data = config_summary(s)
            perm = data.get(cfg.K_PERMISSION)
            # The note says `default` where the key is absent, and the help
            # line below carries what the chosen mode means — putting the
            # explanation in the note as well would crowd out the one word
            # that says whether anything was changed.
            rows.append(Item('cycle', 'Default permission mode',
                             lambda x: str(perm) if perm else 'manual',
                             lambda x: '' if perm else 'default',
                             key='permission', choices=cfg.PERMISSION_MODES,
                             on_delete=drop_permission,
                             help='What Kimi does before it runs a tool call: '
                                  + cfg.PERMISSION_HELP.get(perm or 'manual', '')
                                  + '. Read at the next start; backspace hands '
                                    'it back to Kimi.'))
            rows.append(Item('submenu', 'Composer frame colours',
                             lambda x: 'border, borderFocus',
                             key='colors:border,borderFocus',
                             help='The frame the composer border setting draws '
                                  'is coloured by these two palette tokens.'))
        rows += [Item('sep'), Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def free_text_edit(s: State, item: Item, text: str) -> None:
        """An emptied row means the default, which is what backspace does too."""
        ps.set_value(item.key, text.strip() or ps.DEFAULTS[item.key], s.settings_path)

    def act(s: State, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key.startswith('colors:'):
            open_colors(item.key[7:].split(','), 'Composer frame colours')
            return True
        return True

    def drop_permission(s: State, item: Item) -> None:
        write_config_value(s, '', cfg.K_PERMISSION, None)

    def cyc(s: State, item: Item, forward: bool) -> None:
        if item.key == 'fullscreen':
            cycle_item(s, item, forward)
        elif item.key == 'permission':
            modes = cfg.PERMISSION_MODES
            now = (config_summary(s).get(cfg.K_PERMISSION)
                   or cfg.KIMI_DEFAULTS[cfg.K_PERMISSION])
            here = modes.index(now) if now in modes else 0
            write_config_value(s, '', cfg.K_PERMISSION,
                               modes[(here + (1 if forward else -1)) % len(modes)])
        else:
            ps.cycle(item.key, forward, s.settings_path)

    return m.Screen(build, activate=act, cycle=cyc, delete=restore_default,
                    reload=reload_state, help_line=m.HELP_DEL, title=title)


def open_colors(tokens: list[str], title: str) -> None:
    """Open the palette tokens that decide how one screen looks.

    Every colour in Kimi comes from the theme, so a colour row here would be a
    second place to set one value. This opens the first place instead, showing
    only the tokens the screen you came from is drawn with.
    """
    screen, state = themes.screen_colors(tokens, title)
    m.loop(screen, state)


def patch_list(patch: Path | None, name: str) -> list[str]:
    """A list literal read out of a patch, so the menu shows what will be used.

    The spinner presets and the built-in verbs live in the patches, because
    that is where they are spliced into the bundle from. The menu needs them
    too — a row that says `wave` without showing `▁▃▄▅▆▇█` is asking you to
    choose blind. Copying the tables here would mean two lists that agree
    until the day someone edits one, so they are read from the one that is
    authoritative instead.

    A patch that has been rewritten past recognition yields an empty list, and
    the screen then shows names without examples rather than failing.
    """
    if patch is None:
        return []
    try:
        text = patch.read_text(encoding='utf8')
    except OSError:
        return []
    match = re.search(rf'{re.escape(name)}\s*=\s*\[(.*?)\]', text, re.S)
    return re.findall(r"'([^']*)'", match.group(1)) if match else []


def patch_table(patch: Path | None, name: str) -> dict[str, list[str]]:
    """The same, for a `{key: [...], …}` literal."""
    if patch is None:
        return {}
    try:
        text = patch.read_text(encoding='utf8')
    except OSError:
        return {}
    match = re.search(rf'{re.escape(name)}\s*=\s*{{(.*?)\n}};', text, re.S)
    if not match:
        return {}
    out = {}
    for key, body in re.findall(r'(\w+):\s*\[([^\]]*)\]', match.group(1)):
        out[key] = re.findall(r"'([^']*)'", body)
    return out


def spinner_frames(st: State) -> list[str]:
    """The frames the current setting will actually produce."""
    style = st.settings.get('spinner_style', 'default')
    presets = patch_table(st.patch_file('spinner'), 'PRESETS')
    if style == 'custom':
        raw = st.settings.get('spinner_frames', 'default')
        if raw in ('', 'default'):
            return []
        parts = raw.split()
        return parts if len(parts) > 1 else list(raw.strip())
    if style in presets:
        return presets[style]
    return ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']


def mirrored(frames: list[str], on: bool) -> list[str]:
    """The frames as the patch will write them, mirror included.

    A still preview could not show the difference between a run and a swing,
    so `mirror` used to be a word the preview ignored. A moving one can: the
    swing *is* the sequence, once the reversed frames are appended.

    Guarded the way the patch guards it — an even-length palindrome is already
    mirrored — so a set that swings by itself is not doubled.
    """
    if not on or not frames:
        return frames
    if len(frames) % 2 == 0 and all(f == frames[len(frames) - 1 - i]
                                    for i, f in enumerate(frames)):
        return frames
    return frames + frames[::-1]


def _preview_box(line: str, filled: int) -> list[str]:
    """A framed preview line, with the frame sized to what will be drawn in it.

    `filled` is how wide the line becomes once the animated cell is filled —
    which is not how wide `line` looks now, because the placeholder is six
    characters and a frame is whatever the screen cycles through. The box
    grows rather than clipping: the longest of the rotating verbs is wider
    than the old fixed frame, and a preview that cut its own words off would
    be worse than a wide one.
    """
    inner = max(33, filled)
    return ['', ' Preview', '', '  ┌' + '─' * (inner + 1) + '┐',
            '  │ ' + line + ' ' * (inner - filled) + '│',
            '  └' + '─' * (inner + 1) + '┘']


def spinner_interval(st: State) -> float:
    """How long one frame is held, in seconds, as the patch will hold it.

    `default` is Kimi's own: 120 ms for the moon, 80 ms for everything else,
    which is what `MoonLoader` uses. Anything else is the millisecond value
    the setting carries, clamped to the range the patch accepts so a preview
    cannot spin faster than the thing it is previewing.
    """
    raw = st.settings.get('spinner_interval_ms', 'default')
    if raw in ('', 'default'):
        return 0.12 if st.settings.get('spinner_style') == 'moon' else 0.08
    try:
        return min(2000, max(20, int(raw))) / 1000
    except (TypeError, ValueError):
        return 0.08


def spinner_preview(st: State, sel=None) -> list[str]:
    """The working indicator on one line, turning the way it will turn.

    A column of six stills was the old answer to "what does `wave` look
    like", and it answered the wrong question: a spinner is a thing in
    motion, and six frames stacked up read as six spinners. One line that
    actually moves is both smaller and closer to what you will see.
    """
    rate = st.settings.get('spinner_interval_ms', 'default')
    verb = 'working…' if st.settings.get('thinking_verbs') == 'on' else 'working...'
    # The frame is a placeholder rather than a character: `menu.render` fills
    # it in and `menu.loop` cycles it in place. Padded to the width of the
    # widest frame there, so the box does not breathe as it turns.
    line = f'{m.SPIN_SLOT} {verb} (esc to interrupt)'
    # Counted and measured after mirroring, because that is what will run: a
    # swing is twice the frames, and saying eight while sixteen go past would
    # be the preview disagreeing with itself.
    frames = mirrored(spinner_frames(st),
                      st.settings.get('spinner_mirror') == 'on')
    widest = max(frames or ['—'], key=m.visible)
    return _preview_box(line, m.visible(line.replace(m.SPIN_SLOT, widest))) + [
        '', f'  {len(frames)} frame(s), '
            + ('Kimi\'s own speed' if rate == 'default' else f'{rate} ms each')]


def working_frames(st: State) -> list[str]:
    """The frames the working spinner will actually turn.

    `follow` is not a set of its own — it means "whatever the thinking spinner
    was given", which is what the single setting used to do to both arrays.
    `default` is the one way to keep Kimi's moon while changing the other.
    """
    style = st.settings.get('working_style', 'follow')
    if style == 'follow':
        return spinner_frames(st)
    if style == 'custom':
        raw = st.settings.get('working_frames', 'default')
        if raw in ('', 'default'):
            return []
        parts = raw.split()
        return parts if len(parts) > 1 else list(raw.strip())
    presets = patch_table(st.patch_file('spinner'), 'PRESETS')
    if style in presets:
        return presets[style]
    return ['🌑', '🌒', '🌓', '🌔', '🌕', '🌖', '🌗', '🌘']


def working_preview(st: State, sel=None) -> list[str]:
    """The working spinner on one line, turning the way it will turn."""
    line = f'{m.SPIN_SLOT} Waiting on the model…'
    frames = mirrored(working_frames(st),
                      st.settings.get('working_mirror') == 'on')
    widest = max(frames or ['—'], key=m.visible)
    return _preview_box(line, m.visible(line.replace(m.SPIN_SLOT, widest))) + [
        '', f'  {len(frames)} frame(s), '
            + ('same as thinking'
               if st.settings.get('working_style', 'follow') == 'follow'
               else 'its own set')]


def screen_working_style(st: State) -> m.Screen:
    """The other spinner: the one Kimi turns while it waits, not while it thinks.

    Kimi keeps two alphabets. `BRAILLE_SPINNER_FRAMES` runs while it composes
    and thinks; `MOON_SPINNER_FRAMES` runs while it waits on the model or on a
    tool — the moon you see when it is working. They were set together here
    until this screen existed, which made a chosen style follow Kimi around
    rather than say what it was doing.
    """
    presets = patch_table(st.patch_file('spinner'), 'PRESETS')
    keys = SETTING_GROUPS['working'][1]

    def frames_value(x: State) -> str:
        raw = x.settings.get('working_frames', 'default')
        return DEFAULT_MEANS['spinner_frames'] if raw in ('', 'default') else str(raw)

    def build(s: State) -> list[Item]:
        current = s.settings.get('working_style', 'follow')
        note = value_note(lambda x: current, at_default(*keys),
                          (lambda q: lambda x: x.feature_note(q))(s.patch_file('spinner')))
        rows = [Item('info', 'read while the patches are applied — '
                             'a change here needs a patch run'),
                Item('sep')]
        for name in ps.CHOICES['working_style']:
            if name == 'follow':
                shown = 'same as thinking'
            elif name == 'default':
                shown = 'Kimi\'s own moon'
            elif name == 'custom':
                raw = s.settings.get('working_frames', 'default')
                shown = '—' if raw in ('', 'default') else ' '.join(working_frames(s)[:10])
            else:
                shown = ' '.join(presets.get(name, []))
            rows.append(Item('action', name,
                             (lambda tx, on: lambda x: ('● ' if on else '○ ') + tx)(
                                 shown, name == current),
                             note if name == current else (lambda x: ''),
                             key=f'wstyle:{name}'))
        rows += [
            Item('sep'),
            Item('cycle', 'Reverse-mirror run', switch_value('working_mirror'),
                 value_note(switch_value('working_mirror'),
                            at_default('working_mirror'), lambda x: ''),
                 key='working_mirror', choices=ps.CHOICES['working_mirror'],
                 help='Off runs the frames start to end and starts over; on '
                      'runs them there and back.'),
            Item('action', 'Your own frames', frames_value,
                 value_note(frames_value, at_default('working_frames'),
                            lambda x: ''),
                 key='working_frames',
                 on_delete=lambda s, i: ps.set_value('working_frames', 'default',
                                                     s.settings_path),
                 edit_start=lambda x, i: (lambda v: '' if v in ('', 'default')
                                          else str(v))(
                     x.settings.get('working_frames', 'default')),
                 on_edit=edit_working_frames,
                 help='Separate frames with spaces, or write them run together. '
                      'Two or more; typing them picks the custom row above.'),
            Item('sep'),
            Item('action', 'Back', lambda x: '', key='back'),
        ]
        return rows

    def act(s: State, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key.startswith('wstyle:'):
            ps.set_value('working_style', item.key[7:], s.settings_path)
        return True

    def edit_working_frames(s: State, item: Item, text: str) -> None:
        if not text.strip():
            ps.set_value('working_frames', 'default', s.settings_path)
            return
        ps.set_value('working_frames', text.strip(), s.settings_path)
        ps.set_value('working_style', 'custom', s.settings_path)

    def cyc(s: State, item: Item, forward: bool) -> None:
        if item.key in ps.CHOICES:
            ps.cycle(item.key, forward, s.settings_path)

    # Kimi holds the moon 120 ms and the braille set 80; the working spinner is
    # the moon's slot, so its preview turns at the moon's speed unless the
    # interval setting says otherwise.
    return m.Screen(build, activate=act, cycle=cyc, delete=restore_default,
                    reload=reload_state, aside=working_preview,
                    frames=lambda x: mirrored(working_frames(x),
                                              x.settings.get('working_mirror') == 'on')
                    or ['—'],
                    frame_interval=spinner_interval(st),
                    help_line=m.HELP_DEL, title='Working style')


def screen_thinking_style(st: State) -> m.Screen:
    """The spinner: which characters it cycles through, and how fast.

    Every preset is a row showing its own frames, because that is the only
    form of this question anyone can answer — `glow` and `wave` are names for
    something you recognise on sight and not otherwise.
    """
    presets = patch_table(st.patch_file('spinner'), 'PRESETS')
    keys = SETTING_GROUPS['style'][1]

    def interval_value(x: State) -> str:
        raw = x.settings.get('spinner_interval_ms', 'default')
        return DEFAULT_MEANS['spinner_interval_ms'] if raw == 'default' else f'{raw} ms'

    def frames_value(x: State) -> str:
        raw = x.settings.get('spinner_frames', 'default')
        return DEFAULT_MEANS['spinner_frames'] if raw in ('', 'default') else str(raw)

    def build(s: State) -> list[Item]:
        current = s.settings.get('spinner_style', 'default')
        note = value_note(lambda x: current, at_default(*keys),
                          (lambda q: lambda x: x.feature_note(q))(s.patch_file('spinner')))
        rows = [Item('info', 'read while the patches are applied — '
                             'a change here needs a patch run'),
                Item('sep')]
        for name in ps.CHOICES['spinner_style']:
            if name == 'default':
                shown = 'Kimi\'s own'
            elif name == 'custom':
                raw = s.settings.get('spinner_frames', 'default')
                shown = '—' if raw in ('', 'default') else ' '.join(spinner_frames(s)[:10])
            else:
                shown = ' '.join(presets.get(name, []))
            rows.append(Item('action', name,
                             (lambda t, on: lambda x: ('● ' if on else '○ ') + t)(
                                 shown, name == current),
                             note if name == current else (lambda x: ''),
                             key=f'style:{name}'))
        rows += [
            Item('sep'),
            # The note is asked about the *shown* value, not the stored one:
            # a row showing `80/120 ms` has had nothing changed, and a note
            # deciding on the word `default` behind it would stay silent.
            Item('cycle', 'Update interval', interval_value,
                 value_note(interval_value, at_default('spinner_interval_ms'),
                            lambda x: ''),
                 key='spinner_interval_ms', choices=ps.CHOICES['spinner_interval_ms'],
                 help='How long one frame stays on screen. Lower is faster.'),
            Item('cycle', 'Reverse-mirror run', switch_value('spinner_mirror'),
                 value_note(switch_value('spinner_mirror'),
                            at_default('spinner_mirror'), lambda x: ''),
                 key='spinner_mirror', choices=ps.CHOICES['spinner_mirror'],
                 help='Off runs the frames start to end and starts over; on '
                      'runs them there and back.'),
            Item('action', 'Your own frames', frames_value,
                 value_note(frames_value, at_default('spinner_frames'),
                            lambda x: ''),
                 key='spinner_frames',
                 on_delete=lambda s, i: ps.set_value('spinner_frames', 'default',
                                                     s.settings_path),
                 edit_start=lambda x, i: (lambda v: '' if v in ('', 'default')
                                          else str(v))(
                     x.settings.get('spinner_frames', 'default')),
                 on_edit=edit_frames,
                 help='Separate frames with spaces, or write them run together. '
                      'Two or more; typing them picks the custom row above.'),
            Item('sep'),
            Item('submenu', 'Colours', lambda x: 'primary, textDim',
                 key='colors:primary,textDim',
                 help='The spinner while composing is `primary`; the thinking '
                      'line is `textDim`.'),
            Item('action', 'Back', lambda x: '', key='back'),
        ]
        return rows

    def act(s: State, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key.startswith('colors:'):
            open_colors(item.key[7:].split(','), 'Spinner colours')
            return True
        if item.key.startswith('style:'):
            ps.set_value('spinner_style', item.key[6:], s.settings_path)
        return True

    def edit_frames(s: State, item: Item, text: str) -> None:
        """Frames typed in are the frames you want, so the style follows them."""
        if not text.strip():
            ps.set_value('spinner_frames', 'default', s.settings_path)
            return
        ps.set_value('spinner_frames', text.strip(), s.settings_path)
        ps.set_value('spinner_style', 'custom', s.settings_path)

    def cyc(s: State, item: Item, forward: bool) -> None:
        if item.key in ps.CHOICES:
            ps.cycle(item.key, forward, s.settings_path)

    # The preview turns at the speed the setting asks for, so `20 ms` and
    # `600 ms` are told apart by watching rather than by reading the number.
    return m.Screen(build, activate=act, cycle=cyc, delete=restore_default,
                    reload=reload_state, aside=spinner_preview,
                    frames=lambda x: mirrored(spinner_frames(x),
                                              x.settings.get('spinner_mirror') == 'on')
                    or ['—'],
                    frame_interval=spinner_interval(st),
                    help_line=m.HELP_DEL, title='Thinking style')


def verb_words(st: State) -> list[str]:
    """The words the rotation will use — your own, or the patch's own list."""
    raw = st.settings.get('thinking_verbs_list', 'default')
    if raw in ('', 'default'):
        return patch_list(st.patch_file('verbs'), 'BUILT_IN_VERBS')
    return [w.strip() for w in raw.split(',') if w.strip()]


def verb_preview(st: State, sel=None) -> list[str]:
    """The rotating word on one line, rotating.

    Six words listed under each other are a list, which the row above already
    is. What the setting actually does is swap one word for the next, so the
    preview swaps one word for the next — held long enough to read, unlike
    the spinner beside it.
    """
    words = verb_words(st)
    frame = (spinner_frames(st) or ['✻'])[0]
    line = f'{frame} {m.SPIN_SLOT} (esc to interrupt)'
    widest = max(verb_phrases(st) or ['—'], key=m.visible)
    return _preview_box(line, m.visible(line.replace(m.SPIN_SLOT, widest))) + [
        '', f'  {len(words)} word(s), one every 3.5 s']


def verb_phrases(st: State) -> list[str]:
    """Each word already put through the format — what the preview cycles."""
    fmt = st.settings.get('thinking_verbs_format', '{}')
    return [fmt.replace('{}', w) for w in verb_words(st)]


def screen_thinking_verbs(st: State) -> m.Screen:
    """The words beside the spinner: whether they rotate, which ones, and how."""

    def format_value(x: State) -> str:
        return str(x.settings.get('thinking_verbs_format', '{}'))

    def build(s: State) -> list[Item]:
        rotate = lambda x: BOX.get(x.settings.get('thinking_verbs', 'off'), '?')  # noqa: E731
        note = value_note(rotate, at_default(*SETTING_GROUPS['verbs'][1]),
                          (lambda q: lambda x: x.feature_note(q))(s.patch_file('verbs')))
        rows = [Item('info', 'read while the patches are applied — '
                             'a change here needs a patch run'),
                Item('sep'),
                Item('cycle', 'Rotate the verb', rotate,
                     note, key='thinking_verbs', choices=ps.CHOICES['thinking_verbs'],
                     help='Off keeps Kimi\'s two fixed words.'),
                Item('action', 'Format',
                     format_value,
                     value_note(format_value, at_default('thinking_verbs_format'),
                                lambda x: ''),
                     key='thinking_verbs_format',
                     on_delete=lambda s2, i: ps.set_value('thinking_verbs_format', '{}',
                                                          s2.settings_path),
                     edit_start=lambda x, i: str(
                         x.settings.get('thinking_verbs_format', '{}')),
                     on_edit=edit_format,
                     help='Where the word goes. {} is the word.'),
                Item('sep'),
                Item('info', 'the words, in the order they rotate'),
                ]
        for i, word in enumerate(verb_words(s)):
            rows.append(Item('action', f'  {word}', lambda x: '', key=f'verb:{i}',
                             on_delete=drop_word,
                             help='backspace removes it from the list'))
        rows += [Item('action', 'Add a word', lambda x: '', key='add',
                      edit_start=lambda x, i: '', on_edit=add_word,
                      help='Shown beside the spinner. Punctuation is yours to '
                           'include.'),
                 Item('action', 'Kimi-mods\' own list', lambda x: '', key='reset',
                      help='Puts the built-in words back.'),
                 Item('sep'),
                 Item('submenu', 'Colours', lambda x: 'textDim',
                      key='colors:textDim',
                      help='The word beside the spinner is drawn in `textDim`.'),
                 Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def write_words(s: State, words: list[str]) -> None:
        """Persist the list, or hand it back to the patch's own when it is empty."""
        ps.set_value('thinking_verbs_list',
                     ', '.join(words) if words else 'default', s.settings_path)

    def drop_word(s: State, item: Item) -> None:
        words = verb_words(s)
        i = int(item.key[5:])
        if 0 <= i < len(words):
            del words[i]
            write_words(s, words)

    def act(s: State, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key.startswith('colors:'):
            open_colors(item.key[7:].split(','), 'Thinking colours')
            return True
        if item.key == 'reset':
            ps.set_value('thinking_verbs_list', 'default', s.settings_path)
        return True

    def add_word(s: State, item: Item, text: str) -> None:
        if text.strip():
            write_words(s, verb_words(s) + [text.strip()])

    def edit_format(s: State, item: Item, text: str) -> None:
        """A format with nowhere for the word would show one fixed string."""
        if '{}' in text:
            ps.set_value('thinking_verbs_format', text, s.settings_path)

    def cyc(s: State, item: Item, forward: bool) -> None:
        if item.key in ps.CHOICES:
            ps.cycle(item.key, forward, s.settings_path)

    # Slower than a spinner on purpose: this one is read, not watched. Kimi
    # holds each word for 3.5 s, which is longer than anyone will stand in
    # front of a preview, so it is shortened rather than copied.
    return m.Screen(build, activate=act, cycle=cyc, delete=restore_default,
                    reload=reload_state, aside=verb_preview,
                    frames=lambda x: verb_phrases(x) or ['—'],
                    frame_interval=0.9,
                    help_line=m.HELP_DEL, title='Thinking verbs')


# The frame each border setting draws, read the same way the patch draws it.
USER_FRAMES = {
    'round': ('╭', '╮', '╰', '╯', '─', '│'),
    'single': ('┌', '┐', '└', '┘', '─', '│'),
    'double': ('╔', '╗', '╚', '╝', '═', '║'),
    'bold': ('┏', '┓', '┗', '┛', '━', '┃'),
    'topbottom': ('', '', '', '', '─', ''),
}

STYLE_SGR = {'default': '\x1b[1m', 'plain': '', 'italic': '\x1b[3m',
             'dim': '\x1b[2m', 'underline': '\x1b[4m',
             'strikethrough': '\x1b[9m'}


# What Kimi puts in front of your own messages when nothing says otherwise.
# The trailing space is part of it, which is why the patch adds one to any
# marker that does not already end in one.
KIMI_MARKER = '✨'

# A marker is a character or two. The general field is wide enough for a path
# or a command, and a box that size in front of one glyph suggests there is
# more to say than there is.
MARKER_FIELD_WIDTH = 10


def marker_value(st: State) -> str:
    """The marker itself, rather than the word `default`.

    A row that reads `default` answers the wrong question: what you want to
    know is which character will be sitting in front of your messages, and
    for that there is no substitute for showing it. The two words that are
    not characters — `default` and `none` — are shown as what they produce,
    with the word kept alongside so the value in the file is still readable
    from the row.
    """
    raw = str(st.settings.get('user_message_marker', 'default'))
    if raw in ('', 'default'):
        # No `(default)` here: the note beside the row says that, for every
        # row, and saying it twice reads as though the two were different
        # facts. `none` is not the default, so it keeps its word — a dash on
        # its own is a riddle.
        return KIMI_MARKER
    if raw == 'none':
        return '—   (none)'
    return raw


def marker_field(current: str) -> str:
    """What the field starts out holding, for a marker.

    The word `default` is not something anyone wants to edit — it is a name
    for a character. The field opens on the character itself, so changing it
    is a matter of replacing what is there rather than knowing that the word
    has to be deleted first.
    """
    if current in ('', 'default'):
        return KIMI_MARKER
    return '' if current == 'none' else current


def marker_setting(typed):
    """What to store for a marker typed into the field. `None` leaves it alone.

    Empty means no marker. That follows from the field opening on the
    character: clearing it is the obvious way to say "nothing there", and it
    would be a poor answer to that to store an empty string the patch then has
    to interpret. It is stored as `none`, which is the word the patch already
    understands.

    Typing Kimi's own character back is stored as `default` rather than as a
    marker of your own. Both draw the same thing, but `default` leaves the
    patch a no-op instead of splicing a replacement that changes nothing.
    """
    if typed is None:
        return None
    value = typed.strip()
    if not value:
        return 'none'
    return 'default' if value == KIMI_MARKER else value


def user_message_preview(st: State, sel=None) -> list[str]:
    """Your own message drawn twice: as Kimi does it, and as you asked for it."""
    marker = st.settings.get('user_message_marker', 'default')
    border = st.settings.get('user_message_border', 'off')
    style = st.settings.get('user_message_style', 'default')

    text = 'list the dir'
    prefix = KIMI_MARKER + ' ' if marker in ('default', '') else \
        ('' if marker == 'none' else
         (marker if marker.endswith(' ') else marker + ' '))
    sgr = STYLE_SGR.get(style, '')
    body = f'{prefix}{sgr}{text}\x1b[0m' if sgr else f'{prefix}{text}'

    out = ['', ' Preview', '', '  Kimi\'s own:', '',
           f'    {KIMI_MARKER} \x1b[1m{text}\x1b[0m',
           '', '  Yours:', '']
    if border == 'off':
        out.append('    ' + body)
    else:
        tl, tr, bl, br, h, v = USER_FRAMES[border]
        width = m.visible(body) + 2
        if border == 'topbottom':
            out += ['    ' + h * width, '    ' + body, '    ' + h * width]
        else:
            out += ['    ' + tl + h * width + tr,
                    '    ' + v + ' ' + body + ' ' + v,
                    '    ' + bl + h * width + br]
    out += ['', '  ● The directory holds 123 files.']
    return out


def screen_user_message(st: State) -> m.Screen:
    """The marker, the frame and the styling of your own messages."""
    keys = SETTING_GROUPS['usermsg'][1]

    def build(s: State) -> list[Item]:
        live = (lambda q: lambda x: x.feature_note(q))(s.patch_file('user-message'))
        rows = [Item('info', 'read while the patches are applied — '
                             'a change here needs a patch run'),
                Item('info', 'the colour is the `roleUser` token in your theme, '
                             'not a setting here'),
                Item('sep')]
        for key in keys:
            label, help_text, _ = PATCH_HELP[key]
            value = marker_value if key == 'user_message_marker' else switch_value(key)
            note = value_note(value, at_default(key), live)
            if key in ps.CHOICES:
                rows.append(Item('cycle', label, value, note, key=key,
                                 choices=ps.CHOICES[key], help=help_text))
            else:
                rows.append(Item('action', label, value, note, key=key,
                                 edit_start=lambda x, i: marker_field(
                                     str(x.settings.get(i.key, ps.DEFAULTS[i.key]))),
                                 on_edit=edit_marker,
                                 help=help_text + '  (enter types one, empty '
                                                  'means no marker at all)'))
        rows += [Item('sep'),
                 Item('submenu', 'Colours', lambda x: 'roleUser in your theme',
                      key='colors:roleUser',
                      help='Every colour in Kimi comes from the palette; this '
                           'opens the token your own messages are drawn in.'),
                 Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def restore(s: State, item: Item) -> None:
        ps.set_value(item.key, ps.DEFAULTS[item.key], s.settings_path)

    def edit_marker(s: State, item: Item, text: str) -> None:
        value = marker_setting(text)
        if value is not None:
            ps.set_value(item.key, value, s.settings_path)

    def act(s: State, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key.startswith('colors:'):
            open_colors(item.key[7:].split(','), 'Your message colour')
            return True
        return True

    def cyc(s: State, item: Item, forward: bool) -> None:
        if item.key in ps.CHOICES:
            ps.cycle(item.key, forward, s.settings_path)

    return m.Screen(build, activate=act, cycle=cyc, delete=restore_default,
                    reload=reload_state, aside=user_message_preview,
                    help_line=m.HELP_DEL, title='User message display')


# Four of the groups are not a list of switches but a thing you look at:
# two spinners, a rotating word, a framed message. Each has a screen written for it,
# and `SETTING_GROUPS` still owns which keys belong where — so the check that
# every switch is reachable holds for these too.
DEDICATED = {
    'style': lambda st: screen_thinking_style(st),
    'working': lambda st: screen_working_style(st),
    'verbs': lambda st: screen_thinking_verbs(st),
    'usermsg': lambda st: screen_user_message(st),
}


def screen_skills(st: State) -> m.Screen:
    """Kimi's own skills and the directories they are read from.

    Three config.toml settings that tweakcc shows as one "Skills" entry. They
    are three separate keys in the file, so they stay three rows here; what
    they share is the question being asked, which is what a screen is for.
    """

    def build(s: State) -> list[Item]:
        data = config_summary(s)
        extra = data.get(cfg.K_EXTRA_SKILL_DIRS) or []
        return [
            Item('submenu', 'Builtin product skills',
                 lambda x: 'off' if data.get(cfg.K_BUILTIN_SKILLS) is False else 'on',
                 key='2', help='Kimi\'s own product skills, on or off.'),
            Item('submenu', 'Extra skill directories',
                 lambda x: f'{len(extra)} configured' if extra else 'none',
                 key='4', help='Mount skill collections from elsewhere without copying them.'),
            Item('submenu', 'Merge skill directories',
                 lambda x: ('on' if data.get(cfg.K_MERGE_SKILLS) is not False else 'off'),
                 lambda x: 'no effect in 0.36.0', key='3',
                 help='Search every brand directory or only the first — identical while each lists one.'),
            Item('sep'),
            Item('action', 'Back', lambda x: '', key='back'),
        ]

    def act(s: State, item: Item) -> bool:
        if item.key == 'back':
            return False
        config_item(s, item.key)
        return True

    return m.Screen(build, activate=act, reload=reload_state, title='Skill setup')


def screen_patches(st: State) -> m.Screen:
    def mark_for(s: State, p: Path) -> str:
        try:
            cutoff = s.binary.stat().st_mtime
        except OSError:
            return 'unknown'
        if p.stat().st_mtime > cutoff:
            return 'changed since the last run'
        return 'in the binary' if s.is_patched else 'not applied'

    def build(s: State) -> list[Item]:
        rows: list[Item] = []
        for p in s.patches:
            rows.append(Item('action', p.name,
                             (lambda q: lambda x: mark_for(x, q))(p),
                             key=f'open:{p}',
                             help='enter opens it in your editor'))
        if not rows:
            rows.append(Item('info', 'none — drop a .js file into patches/'))
        rows += [Item('sep'),
                 Item('info', 'Add a patch by dropping a .js file here; '
                              'see the README for the shape.'),
                 Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def act(s: State, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key.startswith('open:'):
            open_file(Path(item.key[5:]))
        return True

    return m.Screen(build, activate=act, reload=reload_state,
                    title='Patches in patches/')


def cycle_item(st: State, item: Item, forward: bool) -> None:
    """Advance a cycle entry and persist it where that setting lives."""
    ps.cycle(item.key, forward, st.settings_path)


def activate(st: State, item: Item) -> bool:
    """Run an entry. Returns False when the menu should close."""
    k = item.key
    if k == 'quit':
        return False
    if k in DEDICATED:
        sub(DEDICATED[k](st), st)
    elif k in SETTING_GROUPS:
        sub(screen_settings(st, k), st)
    elif k == 'prompts':
        sub(screen_prompts(st), st)
    elif k == 'tools':
        config_item(st, '1')
    elif k == 'skills':
        sub(screen_skills(st), st)
    elif k == 'loop':
        config_item(st, '6')
    elif k == 'thinking':
        config_item(st, '7')
    elif k == 'toolsets':
        config_item(st, '8')
    elif k == 'subagent':
        config_item(st, '9')
    elif k == 'hooks':
        config_item(st, '10')
    elif k == 'themes':
        state = themes.ThemeState()
        sub(themes.screen_themes(state), state)
    elif k == 'display':
        sub(screen_display(st), st)
    elif k == 'patches':
        sub(screen_patches(st), st)
    elif k == 'cost':
        run([sys.executable, str(HERE / 'prompt-cost.py'), str(st.prompt_dir)], st.root)
    elif k == 'apply':
        run([str(st.root / 'kimi-patch.sh')], st.root, wait=False, hold=5.0)
    elif k == 'restore':
        run([str(st.root / 'kimi-patch.sh'), '--restore'], st.root,
            wait=False, hold=5.0)
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


def handle_mouse(st: State, items: list[Item], cursor: int,
                 ev: Mouse, row_map: dict) -> tuple[int, bool, bool]:
    return m.handle_mouse(SCREEN, st, items, cursor, ev, row_map)


def handle(st: State, items: list[Item], cursor: int, key,
           row_map: dict | None = None) -> tuple[int, bool, bool]:
    """One keystroke or click. Returns (cursor, keep_running, needs_reload)."""
    return m.handle(SCREEN, st, items, cursor, key, row_map)


def interactive(root: Path) -> int:
    raw = read_status(root)
    st = State(root, raw, binary_path(raw))
    if st.version == 'unknown':
        print('Cannot read Kimi\'s state. Is it installed?\n')
        print(raw.strip()[:400])
        return 1

    rc = m.loop(SCREEN, st)
    print()
    return rc


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
               'state     : patched by kimi-code-mods\n'
               'signature : ad-hoc\n'
               'prompts   : 69 extracted, 0 edited (applied on the next run)\n')
    pristine = patched.replace('patched by kimi-code-mods', 'pristine (baseline, unpatched)')

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
        check('digit shortcut selects the third row',
              items[pos5].label == 'Thinking style', items[pos5].label)

        # q and friends leave
        for key in ('q', 'esc', 'ctrl-c', 'eof'):
            _, keep, _ = handle(st, items, start, key)
            check(f'{key} quits', keep is False)

        # -- value cycling writes through --------------------------------
        # Every patch switch lives on one screen now, so the cycling checks
        # belong there rather than on the root menu.
        # Every switch has to be reachable from exactly one group, or it is
        # registered and invisible — the failure the old single screen could
        # not have and this split can.
        grouped = [k for _, keys in SETTING_GROUPS.values() for k in keys]
        check('every registered switch is in a group',
              set(grouped) == set(ps.DEFAULTS),
              sorted(set(ps.DEFAULTS) ^ set(grouped)))
        check('no switch is in two groups',
              len(grouped) == len(set(grouped)),
              [k for k in grouped if grouped.count(k) > 1])
        check('every group is reachable from the root menu',
              set(SETTING_GROUPS) <= {i.key for i in items},
              sorted(set(SETTING_GROUPS) - {i.key for i in items}))

        settings.write_text('')
        rows_by_group = {g: screen_settings(st, g).build(st) for g in SETTING_GROUPS}
        for group, grows in rows_by_group.items():
            keys = SETTING_GROUPS[group][1]
            # One row on the misc screen is not a patch switch: the permission
            # mode is a config.toml key. It moved here from the root menu,
            # where it was a row that changed a value rather than a door. The
            # fullscreen renderer used to sit beside it as a launcher variable
            # and is a patch switch now, so it counts like the rest.
            check(f'{group}: one row per switch',
                  [r.key for r in grows if r.selectable
                   and r.key not in ('back', 'permission')
                   and not r.key.startswith('colors:')] == keys,
                  [r.key for r in grows])
            check(f'{group}: every switch row carries help',
                  all(r.help for r in grows if r.key in keys),
                  [r.key for r in grows if r.key in keys and not r.help])

        screen = screen_settings(st, 'misc')
        rows = screen.build(st)

        idx = next(i for i, r in enumerate(rows) if r.key == 'suggestion_height')
        _, _, reload_ = m.handle(screen, st, rows, idx, 'right')
        check('cycling asks for a reload', reload_)
        check('cycle wrote half', ps.get('suggestion_height', settings) == 'half',
              ps.get('suggestion_height', settings))
        m.handle(screen, st, rows, idx, 'right')
        check('cycle advanced to full', ps.get('suggestion_height', settings) == 'full')
        m.handle(screen, st, rows, idx, 'left')
        check('left steps back', ps.get('suggestion_height', settings) == 'half')

        idx = next(i for i, r in enumerate(rows) if r.key == 'wd_command')
        m.handle(screen, st, rows, idx, 'enter')
        check('enter cycles too', ps.get('wd_command', settings) == 'on')

        # A click on a switch row advances it, the same as enter.
        rmap: dict[int, int] = {}
        m.render(screen, st, rows, 0, rmap)
        line_no = next(n for n, i in rmap.items() if i == idx)
        m.handle(screen, st, rows, 0, Mouse(0, 5, line_no, False), rmap)
        check('a click advances a switch', ps.get('wd_command', settings) == 'off',
              ps.get('wd_command', settings))

        # the rendered value follows the file
        st = state()
        rows = screen_settings(st, 'misc').build(st)
        row = next(r for r in rows if r.key == 'suggestion_height')
        check('value reflects the file', row.value(st) == 'half', row.value(st))

        # -- rendering -----------------------------------------------------
        out = '\n'.join(render(st, items, first_selectable(items)))
        check('cursor drawn', CURSOR in out)
        check('separators drawn', '─' * 10 in out)
        check('the selected row explains itself',
              items[first_selectable(items)].help.split('.')[0] in out, out[:400])
        check('the header says where settings go',
              '🌕' in out and str(root) in out and str(config) in out, out[:300])
        check('a home path is shortened', tilde(Path.home() / 'x') == '~/x', tilde(Path.home()))
        check('a path outside home is left alone', tilde(Path('/tmp/x')) == '/tmp/x')
        check('cycle rows show arrows', '‹›' in out)
        # A row sitting at its default has nothing pending, so it says
        # `default`. The patch behind it only becomes worth mentioning once
        # the value differs — before that, whether the patch is installed
        # changes nothing about what Kimi does.
        settings.write_text('')
        misc0 = screen_settings(state(), 'misc')
        sw = '\n'.join(m.render(misc0, state(), misc0.build(state()), 0))
        check('an untouched switch says default rather than waiting',
              '[default]' in sw and 'waiting for apply' not in sw, sw[:700])
        check('and a switch whose value already reads default says it once',
              'default   [default]' not in sw, sw[:700])

        # `expanded_by_default` has no patch in this sandbox, so once it is
        # moved off its default there is something worth saying about it.
        ps.set_value('expanded_by_default', 'both', settings)
        misc1 = screen_settings(state(), 'misc')
        sw = '\n'.join(m.render(misc1, state(), misc1.build(state()), 0))
        check('a changed switch reports its patch instead',
              'patch not installed' in sw, sw[:700])
        check('and the untouched ones still say default', '[default]' in sw, sw[:700])
        settings.write_text('')

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
            # Compared against the drawn form: a label is capitalised on its
            # way to the screen, so the raw string is no longer what is there.
            drawn = m.title_case(items[item_idx].label)
            check('mapped line holds its entry',
                  drawn in lines[line_no],
                  f'line {line_no}: {lines[line_no]!r} vs {drawn!r}')

        # Lines that are not entries must not be in the mapping at all.
        sep_lines = [n for n, l in enumerate(lines) if l.startswith('  ─')]
        check('separators are unmapped', all(n not in row_map for n in sep_lines))
        check('header is unmapped', 0 not in row_map and 1 not in row_map)

        # Clicking a row acts on it, which on this screen means launching a
        # subprocess or opening a submenu. The click-to-act path is exercised
        # on the switch screen above, where advancing a value is the whole
        # effect; here the interesting half is what a click must *not* do.
        idx = next(i for i, it in enumerate(items) if it.key == 'misc')

        # A click anywhere that is not a row is inert — it must not move the
        # cursor and must not act.
        before = ps.get('suggestion_height', settings)
        for dead in (0, 1, sep_lines[0] if sep_lines else len(lines) - 1, len(lines) - 1):
            pos2, keep2, reload2 = handle(st, items, idx, Mouse(0, 3, dead, False), row_map)
            check(f'click on line {dead} does nothing',
                  (pos2, keep2, reload2) == (idx, True, False), (pos2, keep2, reload2))
        check('inert clicks changed no setting',
              ps.get('suggestion_height', settings) == before)

        line_no = next(n for n, i in row_map.items() if i == idx)

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

        # -- the switches a patch reads and the ones the menu offers --------
        # These are two lists in two languages that have to agree, and nothing
        # forces them to. A patch that reads an unregistered key gets its
        # fallback for ever and has no row; a registered key no patch reads is
        # a row that does nothing. Both are silent, so they are checked here
        # against the patches on disk rather than trusted.
        asked = set()
        for patch in (ROOT / 'patches').glob('*.js'):
            if is_os_cruft(patch.name):
                continue
            asked |= set(re.findall(r"settings\.get\(\s*'([a-z_]+)'",
                                    patch.read_text(encoding='utf8', errors='replace')))
        check('every switch a patch reads is registered',
              asked <= set(ps.DEFAULTS), sorted(asked - set(ps.DEFAULTS)))
        check('every registered switch is read by a patch',
              set(ps.DEFAULTS) <= asked, sorted(set(ps.DEFAULTS) - asked))
        check('every switch has a menu row and help',
              set(ps.DEFAULTS) <= set(PATCH_HELP),
              sorted(set(ps.DEFAULTS) - set(PATCH_HELP)))
        check('every help entry names a switch that exists',
              set(PATCH_HELP) <= set(ps.DEFAULTS),
              sorted(set(PATCH_HELP) - set(ps.DEFAULTS)))
        # The third element of a help entry locates the patch behind the row.
        # A needle that matches nothing would show "patch not installed" on a
        # switch whose patch is right there.
        for key, (_, _, needle) in PATCH_HELP.items():
            check(f'{key}: its patch is findable by "{needle}"',
                  any(needle in p.name.lower() for p in (ROOT / 'patches').glob('*.js')),
                  needle)

        # -- submenus are screens too --------------------------------------
        # Every submenu used to end in `input()` and a digit. The point of the
        # rewrite is that they are now the same kind of object as the root
        # menu, so the same navigation checks apply to all of them.
        st = state()
        for name, screen in (('prompts', screen_prompts(st)),
                             ('display', screen_display(st)),
                             ('patches', screen_patches(st))):
            rows = screen.build(st)
            check(f'{name} builds rows', len(rows) > 0)
            check(f'{name} has a selectable row', any(r.selectable for r in rows))

            # Navigation must never come to rest on a fact or a rule.
            dead = [i for i, r in enumerate(rows) if not r.selectable]
            pos = m.first_selectable(rows)
            for _ in range(len(rows) * 2):
                pos, _, _ = m.handle(screen, st, rows, pos, 'down')
                check(f'{name}: never lands on an unselectable row', pos not in dead, pos)

            # Back closes, and nothing else does.
            idx = next(i for i, r in enumerate(rows) if r.key == 'back')
            _, keep, _ = m.handle(screen, st, rows, idx, 'enter')
            check(f'{name}: back closes the screen', keep is False)

            # The mouse mapping is built by the same pass that draws.
            row_map2: dict[int, int] = {}
            lines2 = m.render(screen, st, rows, m.first_selectable(rows), row_map2)
            check(f'{name}: title drawn',
                  any(m.title_case(screen.title) in l for l in lines2))
            check(f'{name}: every selectable row mapped',
                  len(row_map2) == len([r for r in rows if r.selectable]))
            for line_no, ri in row_map2.items():
                check(f'{name}: mapped line holds its row',
                      m.title_case(rows[ri].label) in lines2[line_no],
                      lines2[line_no])
            check(f'{name}: esc leaves', m.handle(screen, st, rows, 0, 'esc')[1] is False)

        # the patch screen names the patches that are actually there
        rows = screen_patches(st).build(st)
        check('patch screen lists the patches',
              any('00-a.js' == r.label for r in rows), [r.label for r in rows])

        # the environment screen offers what the launcher accepts, no more
        rows = screen_display(st).build(st)
        env_names = [r.key[4:] for r in rows if r.key.startswith('env:')]
        check('environment screen lists variables', len(env_names) > 5, env_names)
        check('every environment row is a launcher variable',
              all(n.startswith('KIMI') for n in env_names), env_names)

        # -- the rows that write config.toml on a keystroke -----------------
        # The permission mode is stepped through rather than opened, so it
        # writes on every press. That is only safe because the value comes
        # from Kimi's own list and the line editor touches nothing else —
        # both of which are checked here rather than assumed.
        config.write_text('# a comment worth keeping\n'
                          'default_model = "kimi-code/k3"\n'
                          '[loop_control]\n'
                          'max_attempts_per_step = 3\n')
        st = state()
        misc = screen_settings(st, 'misc')
        row = next(r for r in misc.build(st) if r.key == 'permission')
        check('the permission row is a cycle', row.kind == 'cycle', row.kind)
        check('and offers exactly Kimi\'s own modes',
              row.choices == cfg.PERMISSION_MODES, row.choices)
        check('an unset value reads as Kimi\'s default',
              row.value(st) == 'manual', row.value(st))

        _backed_up.clear()
        m.handle(misc, st, misc.build(st),
                 next(i for i, r in enumerate(misc.build(st)) if r.key == 'permission'),
                 'right')
        written = config.read_text()
        check('‹› writes the file',
              'default_permission_mode' in written, written)
        check('and the rest of it survives',
              '# a comment worth keeping' in written
              and 'max_attempts_per_step = 3' in written, written)
        import tomllib as _toml
        first = _toml.loads(written)[cfg.K_PERMISSION]
        check('the value written is one Kimi accepts',
              first in cfg.PERMISSION_MODES, first)

        backups = list(root.glob('*.bak'))
        check('the first write keeps a copy of what was there', len(backups) == 1,
              [b.name for b in backups])
        check('and that copy is the original', '# a comment worth keeping'
              in backups[0].read_text() and 'default_permission_mode'
              not in backups[0].read_text())

        st = state()
        misc = screen_settings(st, 'misc')
        rows_p = misc.build(st)
        idx_p = next(i for i, r in enumerate(rows_p) if r.key == 'permission')
        m.handle(misc, st, rows_p, idx_p, 'right')
        m.handle(misc, st, misc.build(state()), idx_p, 'right')
        check('stepping again does not pile up backups',
              len(list(root.glob('*.bak'))) == 1,
              [b.name for b in root.glob('*.bak')])
        check('and the mode kept moving',
              _toml.loads(config.read_text())[cfg.K_PERMISSION] != first,
              _toml.loads(config.read_text()).get(cfg.K_PERMISSION))

        # Backspace hands it back, which for a config key means removing it
        # rather than writing Kimi's default into the file.
        st = state()
        misc = screen_settings(st, 'misc')
        rows_p = misc.build(st)
        m.handle(misc, st, rows_p,
                 next(i for i, r in enumerate(rows_p) if r.key == 'permission'),
                 'backspace')
        check('backspace removes the key',
              cfg.K_PERMISSION not in _toml.loads(config.read_text()),
              _toml.loads(config.read_text()))
        check('and leaves the rest of the file alone',
              '# a comment worth keeping' in config.read_text())
        for b in root.glob('*.bak'):
            b.unlink()
        config.write_text('default_model = "kimi-code/k3"\n')

        # The real spinner and verb patches are copied in: these screens read
        # their tables out of the patch rather than keeping a copy, and the
        # notes below need a switch with a patch actually on disk.
        for real in (ROOT / 'patches').glob('7[01]-*.js'):
            shutil.copy(real, root / 'patches' / real.name)
            os.utime(root / 'patches' / real.name, (1000, 1000))

        # -- what a note says, and what the root menu shows -----------------
        # Two states, and only two: on Kimi's own value, or not. `waiting for
        # apply` said the same thing beside every changed row that the banner
        # says once at the top, which left the notes carrying nothing.
        settings.write_text('')
        # The verb rotation is the one switch in this sandbox that has both a
        # patch on disk and a default that is not the word `default` — so it
        # is the row where all three states are visible.
        def verb_note():
            here = state()
            value = switch_value('thinking_verbs')
            note = value_note(value, at_default('thinking_verbs'),
                              lambda x: x.feature_note(x.patch_file('verbs')))
            return note(here)

        check('the verb patch is there to be found',
              state().patch_file('verbs') is not None,
              [p.name for p in state().patches])

        check('an untouched row says default', verb_note() == 'default', verb_note())
        ps.set_value('thinking_verbs', 'on', settings)
        check('a changed row whose patch is installed says nothing at all',
              verb_note() == '', verb_note())
        ps.set_value('thinking_verbs', 'off', settings)

        # The one thing still worth a word: a switch with no patch behind it
        # cannot work however it is set, which is different in kind from one
        # that has not been applied yet.
        ps.set_value('read_line_numbers', 'off', settings)
        misc2 = screen_settings(state(), 'misc')
        notes = {r.key: r.note(state()) for r in misc2.build(state()) if r.selectable}
        check('a changed row with no patch behind it still says so',
              notes.get('read_line_numbers') == NO_PATCH, notes)
        # `read_limits` used to *show* the word `default`, which named the
        # fact that nothing was changed twice while saying nothing about what
        # Kimi does. It shows what Kimi does now, so the note carries the
        # other half.
        misc_rows = {r.key: r for r in misc2.build(state()) if r.selectable}
        # Every switch that is untouched has to say so, whatever word its
        # value happens to show. The two that got this wrong showed what Kimi
        # does — `80/120 ms`, `—` — while the note looked at the stored word
        # `default` behind it and stayed silent.
        settings.write_text('')
        for screen_name, maker in (('style', screen_thinking_style),
                                   ('verbs', screen_thinking_verbs),
                                   ('usermsg', screen_user_message)):
            here = state()
            silent = [r.key for r in maker(here).build(here)
                      if r.selectable and r.key in ps.DEFAULTS
                      and r.note(here) not in ('default', NO_PATCH)]
            check(f'{screen_name}: every untouched switch says default',
                  not silent, silent)

        check('a value that spelled itself `default` now says what Kimi does',
              misc_rows['read_limits'].value(state()) == DEFAULT_MEANS['read_limits'],
              misc_rows['read_limits'].value(state()))
        check('and the note carries the other half',
              notes.get('read_limits') == 'default', notes)
        check('nothing anywhere still says it is waiting',
              'waiting' not in ' '.join(
                  str(r.note(state())) for g in SETTING_GROUPS
                  for r in screen_settings(state(), g).build(state()) if r.selectable))
        settings.write_text('')

        # The root menu is a list of doors. Every one of them opens a screen
        # showing the same setting in full, so a summary beside the label is
        # the same fact twice — and it was what pushed the explanation off
        # the end of the line.
        root_items = build_items(state())
        doors = [i for i in root_items if i.kind == 'submenu']
        check('no door on the root menu carries a value',
              all(i.value(state()) == '' for i in doors),
              [(i.label, i.value(state())) for i in doors if i.value(state())])
        check('and none carries a note',
              all(i.note(state()) == '' for i in doors),
              [(i.label, i.note(state())) for i in doors if i.note(state())])
        check('every door says what it is for',
              all(i.help for i in doors), [i.label for i in doors if not i.help])
        check('the ways out keep theirs',
              next(i for i in root_items if i.key == 'apply').value(state())
              == 'run kimi-patch.sh')

        rmap_root: dict[int, int] = {}
        drawn = m.render(SCREEN, state(), root_items, 0, rmap_root, width=100)
        check('the explanation is on the selected row',
              any(l.startswith(CURSOR) and ' - ' in l for l in drawn), drawn[:14])
        check('and not repeated below the list',
              not any(l.strip() == doors[0].help for l in drawn), drawn[-4:])
        # Only the rows: the header carries paths, which are as long as they
        # are, and wrapping one of those costs nothing. A wrapped *row* would
        # take two terminal lines where the mouse mapping counts one.
        long_rows = [drawn[n] for n in rmap_root if m.visible(drawn[n]) > 100]
        check('no row overflows the window', not long_rows, long_rows)

        # -- no row says `default` twice ------------------------------------
        # The note carries that word for every row, so a value that already
        # contains it must not have it appended: `default   [default]` reads
        # as two facts rather than one said twice.
        settings.write_text('')
        config.write_text('default_model = "kimi-code/k3"\n')
        # Compared on the value and the note rather than on the rendered
        # line: two labels contain the word themselves — `Expanded by
        # default`, `Default permission mode` — and those are not repetition.
        doubled = []
        for maker in (lambda: (screen_settings(state(), 'misc'), state()),
                      lambda: (screen_settings(state(), 'router'), state()),
                      lambda: (screen_settings(state(), 'agentsmd'), state()),
                      lambda: (screen_user_message(state()), state()),
                      lambda: (screen_thinking_style(state()), state()),
                      lambda: (screen_thinking_verbs(state()), state()),
                      lambda: (SCREEN, state())):
            screen, here = maker()
            rows_here = build_items(here) if screen is SCREEN else screen.build(here)
            for it in rows_here:
                if not it.selectable:
                    continue
                shown, aside_note = str(it.value(here)).lower(), str(it.note(here)).lower()
                if 'default' in shown and 'default' in aside_note:
                    doubled.append(f'{it.label}: {shown} [{aside_note}]')
        check('no row says default twice', not doubled, doubled)

        check('a value that says default gets no note',
              default_note('default') == '' and default_note('✨   (default)') == '')
        check('any other value does', default_note('off') == 'default')

        # -- the colour rows point at tokens that exist ---------------------
        # A row offering to edit `roleUsr` would open a picker that writes a
        # key Kimi drops without a word. The names are spelled out in five
        # places, so they are checked against the palette rather than trusted.
        known = {t for t, _ in themes.TOKENS}
        colour_rows = []
        for maker in (lambda: screen_user_message(st),
                      lambda: screen_thinking_style(st),
                      lambda: screen_thinking_verbs(st),
                      lambda: screen_settings(st, 'misc')):
            colour_rows += [r.key[7:] for r in maker().build(st)
                            if r.key.startswith('colors:')]
        check('every screen that shows a colour row has one', len(colour_rows) == 4,
              colour_rows)
        named = {t for row in colour_rows for t in row.split(',')}
        check('every colour row names real palette tokens',
              named <= known, sorted(named - known))

        # -- the previews describe the settings they are drawn beside -------
        # A preview that does not follow the setting is worse than none: it
        # invites a choice made on what it showed. So each is checked against
        # the value it is supposed to be showing, not merely for existing.
        settings.write_text('')
        st = state()
        # The preview no longer holds the frames themselves — it holds one
        # slot, and the screen hands `menu.render` the sequence to cycle
        # through it. Both halves are checked: the sequence follows the
        # setting, and the preview is one line with one slot in it.
        check('the spinner preview falls back to Kimi\'s own frames',
              '⠋' in spinner_frames(st), spinner_frames(st)[:4])
        check('and shows them on a single animated line',
              sum(m.SPIN_SLOT in ln for ln in spinner_preview(st)) == 1,
              spinner_preview(st))

        ps.set_value('spinner_style', 'star', settings)
        st = state()
        check('choosing a preset shows that preset\'s frames',
              '✻' in spinner_frames(st), spinner_frames(st))
        check('and the frames come from the patch, not a copy here',
              spinner_frames(st) == patch_table(st.patch_file('spinner'),
                                                'PRESETS')['star'],
              spinner_frames(st))

        # Custom frames: written run together or spaced, they mean the same,
        # and a frame of several characters needs the spaced form.
        ps.set_value('spinner_style', 'custom', settings)
        ps.set_value('spinner_frames', 'abc', settings)
        check('run-together frames split per character',
              spinner_frames(state()) == ['a', 'b', 'c'])
        ps.set_value('spinner_frames', 'ab cd', settings)
        check('spaced frames stay whole',
              spinner_frames(state()) == ['ab', 'cd'])
        ps.set_value('spinner_style', 'default', settings)
        ps.set_value('spinner_frames', 'default', settings)

        # The verbs, the same way: the built-in list is read out of the patch
        # so the screen cannot offer words the patch will not use.
        st = state()
        built_in = verb_words(st)
        check('the built-in verbs are read from the patch',
              built_in == patch_list(st.patch_file('verbs'), 'BUILT_IN_VERBS'),
              built_in[:3])
        check('there are some', len(built_in) > 4, len(built_in))
        ps.set_value('thinking_verbs_list', 'one, two , three', settings)
        check('your own words are split and trimmed',
              verb_words(state()) == ['one', 'two', 'three'], verb_words(state()))
        ps.set_value('thinking_verbs_format', '{}…', settings)
        check('the format reaches the preview',
              'one…' in verb_phrases(state()), verb_phrases(state()))
        check('and the verb preview is one animated line too',
              sum(m.SPIN_SLOT in ln for ln in verb_preview(state())) == 1,
              verb_preview(state()))
        ps.set_value('thinking_verbs_list', 'default', settings)
        ps.set_value('thinking_verbs_format', '{}', settings)

        # The message preview draws the frame the setting names, and both the
        # before and the after, because the point is the comparison.
        ps.set_value('user_message_border', 'double', settings)
        pv = '\n'.join(user_message_preview(state()))
        check('the message preview draws the chosen frame', '╔' in pv and '╚' in pv, pv)
        check('and still shows what Kimi does', 'Kimi\'s own' in pv)
        # The marker row shows the character rather than the word: what you
        # want to know is what will be sitting in front of your messages.
        ps.set_value('user_message_marker', 'default', settings)
        check('the marker row shows Kimi\'s own character',
              marker_value(state()).startswith(KIMI_MARKER), marker_value(state()))
        check('and does not repeat what the note beside it says',
              '(default)' not in marker_value(state()), marker_value(state()))
        check('the note is where default is said',
              default_note(marker_value(state())) == 'default')
        ps.set_value('user_message_marker', 'none', settings)
        check('`none` is shown as the absence it is',
              marker_value(state()).startswith('—'), marker_value(state()))
        for own in ('▌', '🌕', '>>'):
            ps.set_value('user_message_marker', own, settings)
            check(f'a marker of your own is shown as itself ({own})',
                  marker_value(state()) == own, marker_value(state()))
        row = next(r for r in screen_user_message(state()).build(state())
                   if r.key == 'user_message_marker')
        check('and that is what the row draws', row.value(state()) == '>>',
              row.value(state()))

        # The field opens on the character, not on the word naming it — the
        # word is not something anyone wants to edit.
        check('the field starts on Kimi\'s character',
              marker_field('default') == KIMI_MARKER, marker_field('default'))
        check('an unset value is the same as default',
              marker_field('') == KIMI_MARKER)
        check('`none` opens an empty field', marker_field('none') == '')
        check('a marker of your own opens on itself', marker_field('▌') == '▌')

        # And an empty field means no marker, which is the obvious reading of
        # having cleared the character that was in it.
        check('an empty field means no marker', marker_setting('') == 'none')
        check('whitespace alone counts as empty', marker_setting('   ') == 'none')
        check('escape leaves the setting alone', marker_setting(None) is None)
        check('a character of your own is stored as written',
              marker_setting('▌') == '▌')
        check('typing Kimi\'s own character back is stored as default',
              marker_setting(KIMI_MARKER) == 'default')
        check('and so is the same with stray spacing',
              marker_setting(f' {KIMI_MARKER} ') == 'default')

        # Round trip: what the field offers, accepted unchanged, has to leave
        # the setting where it was rather than drifting to another spelling.
        for start in ('default', 'none', '▌', '🌕'):
            check(f'{start} survives being opened and accepted',
                  marker_setting(marker_field(start)) == start,
                  (start, marker_field(start), marker_setting(marker_field(start))))

        ps.set_value('user_message_border', 'off', settings)
        ps.set_value('user_message_marker', '▌', settings)
        pv2 = '\n'.join(user_message_preview(state()))
        check('the marker reaches the preview', '▌ ' in pv2, repr(pv2))
        check('and Kimi\'s own marker is still shown next to it', '✨ ' in pv2)
        ps.set_value('user_message_marker', 'none', settings)
        check('`none` removes the marker without removing the text',
              '✨' in '\n'.join(user_message_preview(state()))
              and 'list the dir' in '\n'.join(user_message_preview(state())))
        ps.set_value('user_message_marker', 'default', settings)

        # A row on a dedicated screen writes the same file the generic one
        # does — these three screens replace the rows, not the settings.
        style_screen = screen_thinking_style(state())
        srows = style_screen.build(state())
        idx = next(i for i, r in enumerate(srows) if r.key == 'style:glow')
        m.handle(style_screen, state(), srows, idx, 'enter')
        check('picking a style row writes the setting',
              ps.get('spinner_style', settings) == 'glow',
              ps.get('spinner_style', settings))
        ps.set_value('spinner_style', 'default', settings)

        verbs_screen = screen_thinking_verbs(state())
        vrows = verbs_screen.build(state())
        first_word = next(r for r in vrows if r.key == 'verb:0')
        m.handle(verbs_screen, state(), vrows, vrows.index(first_word), 'backspace')
        check('backspace drops a word from the list',
              len(verb_words(state())) == len(built_in) - 1,
              len(verb_words(state())))
        ps.set_value('thinking_verbs_list', 'default', settings)
        settings.write_text('')

        # -- the status is only re-read when it could have changed ----------
        # Asking costs six seconds of hashing, and the menu reloads after
        # every action. What it reports depends on the binary and the prompt
        # overrides, so a change to anything else has to reuse the answer.
        st = state()
        calls = []
        real_read = globals()['read_status']
        globals()['read_status'] = lambda root: calls.append(root) or raw
        try:
            again = reload_state(st)
            check('an unchanged binary is not re-hashed', calls == [], calls)
            check('the reused state still reads the files',
                  again.version == '0.36.0' and again.settings_path == settings)
            check('the reused state kept its config path', again.config_path == config)

            os.utime(binary, (2 ** 31, 2 ** 31))
            reload_state(st)
            check('a replaced binary is re-read', len(calls) == 1, calls)

            calls.clear()
            st2 = state()
            (root / 'system-prompts' / 'edited.md').write_text('override')
            reload_state(st2)
            check('an edited prompt override is re-read', len(calls) == 1, calls)
        finally:
            globals()['read_status'] = real_read
            (root / 'system-prompts' / 'edited.md').unlink(missing_ok=True)
            os.utime(binary, (1000, 1000))

        # -- the config screens run in this process now ---------------------
        # They used to be a subprocess, which is what put a foreign top-level
        # menu between a setting and the row it was reached from. What can
        # break in the new path is the wiring: the editor is constructed here
        # and its deferred write is resolved here. The screens themselves are
        # covered by config-menu's own self-check.
        editor = cfg.Editing(config, cfg.TomlLines(config.read_text()), dry_run=False)
        check('the config editor builds from this process',
              editor.data.get('default_model') == 'kimi-code/k3', editor.data)
        check('every config row the menu opens exists',
              all(k in {r.key for r in cfg.screen_main(editor).build(editor)}
                  for k in ('1', '5', '6', '7', '8', '9', '10')),
              sorted(r.key for r in cfg.screen_main(editor).build(editor)))
        check('every skill row the menu opens exists',
              {r.key for r in screen_skills(st).build(st) if r.selectable}
              - {'back'} <= {r.key for r in cfg.screen_main(editor).build(editor)},
              [r.key for r in screen_skills(st).build(st)])
        untouched = config.read_text()
        with contextlib.redirect_stdout(io.StringIO()):
            wrote = cfg.commit(config, untouched, False)
        check('an unchanged document is not rewritten',
              wrote and config.read_text() == untouched)

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

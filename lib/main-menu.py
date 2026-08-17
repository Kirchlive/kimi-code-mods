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

import menu as m                                             # noqa: E402
import patch_settings as ps                                  # noqa: E402
from keyreader import FakeKeys, Mouse, read_key, sgr         # noqa: E402
from menu import Item, first_selectable, move                # noqa: E402
from oscruft import is_os_cruft, usable_files                # noqa: E402

PATCH_GLOB = '*.js'
CURSOR = m.CURSOR               # ❯, the tweakcc marker


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
        Item('submenu', 'Themes',
             lambda s: (lambda n: f'{n} custom' if n else 'built-in only')(
                 len(themes.list_themes())),
             key='themes',
             help='Kimi loads themes from ~/.kimi-code/themes; switch with /theme.'),
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

        # One row for every patch switch, rather than a handful of the popular
        # ones here and the rest nowhere. Each setting then has exactly one
        # place that writes it, which is what keeps the menu and the patches
        # from disagreeing about a default.
        Item('submenu', 'Patch settings',
             lambda s: (lambda n: f'{n} switch(es)')(len(ps.CHOICES)),
             key='patchsettings',
             help='Everything the patches read while they are applied.'),
        Item('cycle', 'Fullscreen renderer',
             lambda s: 'always' if env_value(s.root, 'KIMI_CODE_TUI_FULL_SCREEN') == '1' else 'default',
             key='fullscreen', choices=['default', 'always'],
             help='Run Kimi in the alternate screen buffer. Applied by bin/kimi.'),
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


def header(st: State) -> list[str]:
    return ['', 'tweakkimi',
            f'Kimi {st.version} — {st.binary_state}, {st.signature} signature'] + banner(st)


def reload_state(st: State) -> State:
    raw = read_status(st.root)
    return State(st.root, raw, binary_path(raw))


# The root screen. Everything about drawing, arrow keys, the wheel and clicks
# lives in menu.py; what stays here is only what is specific to this screen.
SCREEN = m.Screen(build=lambda st: build_items(st), header=header,
                  activate=lambda st, item: activate(st, item),
                  cycle=lambda st, item, fwd: cycle_item(st, item, fwd),
                  reload=reload_state, help_line=m.HELP_ROOT)


def render(st: State, items: list[Item], cursor: int,
           row_map: dict | None = None) -> list[str]:
    return m.render(SCREEN, st, items, cursor, row_map)


def draw(st: State, items: list[Item], cursor: int) -> dict:
    return m.draw(SCREEN, st, items, cursor)


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


def ask(prompt: str) -> str:
    """One line of free text, for the few values no list can offer.

    Wrapped so the caller does not have to think about a closed stdin, which
    happens whenever the menu is smoke-tested without a terminal.
    """
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ''


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
            tree = ask('freshly extracted tree: ')
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
        rows = [Item('info', 'set a value with enter, clear it with ‹›; '
                             'blank means Kimi\'s own default'),
                Item('sep')]
        for name, value in env_rows(s.root):
            rows.append(Item('action', name,
                             (lambda v: lambda x: v or '—')(value),
                             key=f'env:{name}'))
        rows += [Item('sep'), Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def act(s: State, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key.startswith('env:'):
            name = item.key[4:]
            val = ask(f'{name} = ')
            if val:
                subprocess.run(['bash', env, 'set', name, val])
            else:
                subprocess.run(['bash', env, 'unset', name], capture_output=True)
        return True

    def clear(s: State, item: Item, forward: bool) -> None:
        if item.key.startswith('env:'):
            subprocess.run(['bash', env, 'unset', item.key[4:]], capture_output=True)

    # `cycle` is wired to the same rows so ‹› clears a variable. An action row
    # never receives a cycle, so this only fires where it is meant to.
    return m.Screen(build, activate=act, cycle=clear, reload=reload_state,
                    title='Launcher environment')


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
    'user_message_marker': (
        'Your message marker',
        'The prefix in front of what you typed. Kimi\'s own is a sparkle.', 'user-message'),
    'user_message_border': (
        'Your message border',
        'Draw a frame around your own messages in the transcript.', 'user-message'),
    'user_message_style': (
        'Your message style',
        'How your own text is drawn. Kimi\'s own is bold.', 'user-message'),
    'input_box_border': (
        'Composer border',
        'The frame around the input box. off leaves the space blank.', 'input-box'),
}


def screen_patch_settings(st: State) -> m.Screen:
    """One row per patch switch, in the order they were registered."""

    def build(s: State) -> list[Item]:
        rows = [Item('info', 'read while the patches are applied — '
                             'a change here needs a patch run'),
                Item('sep')]
        for key in ps.DEFAULTS:
            label, help_text, needle = PATCH_HELP.get(
                key, (key.replace('_', ' ').capitalize(),
                      'No description registered in PATCH_HELP yet.', key.split('_')[0]))
            patch = s.patch_file(needle)
            value = (lambda k: lambda x: x.settings.get(k, ps.DEFAULTS.get(k, '')))(key)
            note = (lambda q: lambda x: x.feature_note(q))(patch)
            if key in ps.CHOICES:
                rows.append(Item('cycle', label, value, note,
                                 key=key, choices=ps.CHOICES[key], help=help_text))
            else:
                # No list can hold a duration or a prefix, so enter asks.
                rows.append(Item('action', label, value, note,
                                 key=key, help=help_text + '  (enter to type a value)'))
        rows += [Item('sep'), Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def act(s: State, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key in ps.DEFAULTS:
            current = s.settings.get(item.key, ps.DEFAULTS[item.key])
            raw = ask(f'{item.key} [{current}] (empty restores the default): ')
            ps.set_value(item.key, raw or ps.DEFAULTS[item.key], s.settings_path)
        return True

    def cyc(s: State, item: Item, forward: bool) -> None:
        ps.cycle(item.key, forward, s.settings_path)

    return m.Screen(build, activate=act, cycle=cyc, reload=reload_state,
                    title='Patch settings')


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
        sub(screen_prompts(st), st)
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
    elif k == 'themes':
        state = themes.ThemeState()
        sub(themes.screen_themes(state), state)
    elif k == 'patchsettings':
        sub(screen_patch_settings(st), st)
    elif k == 'display':
        sub(screen_display(st), st)
    elif k == 'patches':
        sub(screen_patches(st), st)
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
        # Every patch switch lives on one screen now, so the cycling checks
        # belong there rather than on the root menu.
        settings.write_text('')
        screen = screen_patch_settings(st)
        rows = screen.build(st)
        check('every registered switch has a row',
              {r.key for r in rows if r.kind == 'cycle'} == set(ps.CHOICES),
              {r.key for r in rows if r.kind == 'cycle'} ^ set(ps.CHOICES))
        check('every switch row carries help',
              all(r.help for r in rows if r.kind == 'cycle'),
              [r.key for r in rows if r.kind == 'cycle' and not r.help])

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
        rows = screen_patch_settings(st).build(st)
        row = next(r for r in rows if r.key == 'suggestion_height')
        check('value reflects the file', row.value(st) == 'half', row.value(st))

        # -- rendering -----------------------------------------------------
        out = '\n'.join(render(st, items, first_selectable(items)))
        check('cursor drawn', CURSOR in out)
        check('separators drawn', '─' * 10 in out)
        check('help line drawn', 'system-prompts/' in out)
        check('cycle rows show arrows', '‹›' in out)
        sw = '\n'.join(m.render(screen_patch_settings(st), st,
                                 screen_patch_settings(st).build(st), 0))
        check('patch note shown for a switch with no patch',
              'patch not installed' in sw, sw[:600])

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

        # Clicking a row acts on it, which on this screen means launching a
        # subprocess or opening a submenu. The click-to-act path is exercised
        # on the switch screen above, where advancing a value is the whole
        # effect; here the interesting half is what a click must *not* do.
        idx = next(i for i, it in enumerate(items) if it.key == 'patchsettings')

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
            check(f'{name}: title drawn', any(screen.title in l for l in lines2))
            check(f'{name}: every selectable row mapped',
                  len(row_map2) == len([r for r in rows if r.selectable]))
            for line_no, ri in row_map2.items():
                check(f'{name}: mapped line holds its row',
                      rows[ri].label in lines2[line_no], lines2[line_no])
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

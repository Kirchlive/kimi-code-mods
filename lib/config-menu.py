#!/usr/bin/env python3
"""Interactive menu for the Kimi settings that are worth changing but hard to find.

This writes `~/.kimi-code/config.toml`. It never touches the binary — everything
here is configuration Kimi already supports and simply does not document.

    python3 lib/config-menu.py             # interactive
    python3 lib/config-menu.py --dry-run   # show the diff, write nothing
    python3 lib/config-menu.py --selfcheck # prove the editing and the screens

Every screen here is a `menu.Screen`: arrow keys, wheel and click, with digits
kept only as shortcuts. A path and a number are still typed, because no list
can offer them; everything else is a row.

Two things drove the design.

**Editing has to be surgical.** The file is the user's, with their comments and
their ordering, and it also holds provider credentials. `tomllib` only reads,
and `tomlkit` is not available, so re-serialising the parsed document would
quietly discard every comment. Instead the file is read with `tomllib` for
truth and modified as *lines*: a key is replaced where it stands, inserted at
the end of its section when missing, and removed span-wise when the user hands
a setting back to Kimi. Everything the menu does not touch survives byte for
byte.

**The key names are snake_case.** Kimi maps every top-level TOML key through
`snakeToCamel` on the way in (`transformTomlData`) and `camelToSnake` on the way
out, so the section registered as `mergeAllAvailableSkills` is spelled
`merge_all_available_skills` in the file. Writing the camelCase form parses
fine and does nothing at all, which is the worst possible failure — hence the
constants below are the file spelling, not the internal one.
"""

import contextlib
import difflib
import importlib.util
import io
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
CONFIG = Path.home() / '.kimi-code' / 'config.toml'
KIMI_BIN = Path.home() / '.kimi-code' / 'bin' / 'kimi'

sys.path.insert(0, str(HERE.resolve()))

import menu as m                                             # noqa: E402
from menu import Item                                        # noqa: E402

# TOML spellings. See the module docstring: these are snake_case on purpose.
K_BUILTIN_SKILLS = 'builtin_product_skills'
K_MERGE_SKILLS = 'merge_all_available_skills'
K_EXTRA_SKILL_DIRS = 'extra_skill_dirs'
K_PERMISSION = 'default_permission_mode'
S_TOOLS = 'tools'
S_LOOP = 'loop_control'
K_ATTEMPTS = 'max_attempts_per_step'
K_ATTEMPTS_OLD = 'max_retries_per_step'      # deprecated, renamed on sight
K_RESERVED = 'reserved_context_size'
S_SECONDARY = 'secondary_model'
K_SM_DEFAULT = 'default_model'
K_SM_MODELS = 'models'
K_SM_FORCE = 'force'
S_THINKING = 'thinking'
K_THINK_ENABLED = 'enabled'
K_THINK_EFFORT = 'effort'
K_THINK_FORCED = 'forced_effort'
K_THINK_KEEP = 'keep'

# The levels Kimi's own profiles name. `minimal` is deliberately absent: it
# appears in no profile in 0.36.0, and offering a level the binary never uses
# would be a menu entry that quietly does nothing.
EFFORTS = ['off', 'low', 'medium', 'high', 'xhigh', 'max']

# From PermissionModeSchema = _enum(["yolo","manual","auto"]) in the bundle.
PERMISSION_MODES = ['yolo', 'manual', 'auto']
PERMISSION_HELP = {
    'yolo': 'run tool calls without asking (our default)',
    'manual': 'ask before every tool call',
    'auto': 'ask only for the risky ones',
}

# Kimi's own defaults, shown when a key is absent.
KIMI_DEFAULTS = {
    K_BUILTIN_SKILLS: True,
    K_MERGE_SKILLS: True,
    K_PERMISSION: 'manual',
    K_ATTEMPTS: 3,
    K_RESERVED: 50000,
}

# What the menu marks as recommended. One place, one line each, so a changed
# opinion is a one-line change. `None` means we deliberately have no opinion
# and let Kimi's own default stand — currently the case for merging skill
# directories, which does nothing in 0.36.0 either way.
RECOMMENDED = {
    K_BUILTIN_SKILLS: False,
    K_MERGE_SKILLS: None,
    K_PERMISSION: 'yolo',
}


# --------------------------------------------------------------------------
# Lossless TOML line editing
# --------------------------------------------------------------------------

def _strip_noise(line: str, in_ml: str | None) -> tuple[str, str | None]:
    """Blank out string contents and comments so brackets can be counted.

    Returns the cleaned line and the multi-line-string delimiter still open at
    the end of it, if any. Without this a `#` inside a value, or a `[` inside a
    string, would be read as structure.
    """
    out = []
    i = 0
    n = len(line)
    if in_ml:
        end = line.find(in_ml)
        if end < 0:
            return '', in_ml
        i = end + len(in_ml)
        out.append(' ' * i)
        in_ml = None
    while i < n:
        ch = line[i]
        if ch == '#':
            break
        if line.startswith('"""', i) or line.startswith("'''", i):
            delim = line[i:i + 3]
            end = line.find(delim, i + 3)
            if end < 0:
                out.append(' ' * (n - i))
                return ''.join(out), delim
            out.append(' ' * (end + 3 - i))
            i = end + 3
            continue
        if ch in '"\'':
            j = i + 1
            while j < n:
                if line[j] == '\\' and ch == '"':
                    j += 2
                    continue
                if line[j] == ch:
                    break
                j += 1
            out.append(' ' * (min(j, n - 1) + 1 - i))
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out), in_ml


HEADER_RE = re.compile(r'^\s*\[\[?([^\[\]]+)\]\]?\s*$')


class TomlLines:
    """A TOML file as lines, edited in place.

    Only what is asked for changes; comments, blank lines, ordering and
    unrelated sections are never rewritten.
    """

    def __init__(self, text: str):
        self.lines = text.split('\n')
        # A trailing newline shows up as a final empty element; remember it so
        # writing back does not add or drop one.
        self._trailing_nl = self.lines and self.lines[-1] == ''
        if self._trailing_nl:
            self.lines.pop()

    def text(self) -> str:
        return '\n'.join(self.lines) + ('\n' if self._trailing_nl else '')

    def _map(self):
        """Yield (index, section, cleaned, is_header) for every line."""
        section = ''
        in_ml = None
        depth = 0
        for idx, line in enumerate(self.lines):
            cleaned, next_ml = _strip_noise(line, in_ml)
            is_header = False
            if in_ml is None and depth == 0:
                m = HEADER_RE.match(cleaned)
                if m:
                    is_header = True
                    section = m.group(1).strip()
                    yield idx, section, cleaned, True
                    in_ml = next_ml
                    continue
            yield idx, section, cleaned, False
            if in_ml is None:
                depth += cleaned.count('[') - cleaned.count(']')
                depth = max(depth, 0)
            in_ml = next_ml

    def section_lines(self, section: str) -> list[tuple[int, str, bool]]:
        """(index, cleaned, is_header) for the lines belonging to a section."""
        return [(i, c, h) for i, s, c, h in self._map() if s == section]

    def has_section(self, section: str) -> bool:
        if section == '':
            return True
        return any(h and s == section for _, s, _, h in self._map())

    def find_key(self, section: str, key: str) -> tuple[int, int] | None:
        """Line span (start, end_exclusive) of `key` in `section`, if present."""
        pat = re.compile(r'^\s*(?:"' + re.escape(key) + r'"|\'' + re.escape(key)
                         + r'\'|' + re.escape(key) + r')\s*=')
        rows = self.section_lines(section)
        for pos, (idx, cleaned, is_header) in enumerate(rows):
            if is_header or not pat.match(cleaned):
                continue
            # Walk forward while the value keeps brackets open.
            depth = cleaned.count('[') - cleaned.count(']')
            end = idx + 1
            k = pos + 1
            while depth > 0 and k < len(rows):
                nxt_idx, nxt_clean, nxt_hdr = rows[k]
                if nxt_hdr:
                    break
                depth += nxt_clean.count('[') - nxt_clean.count(']')
                end = nxt_idx + 1
                k += 1
            return idx, end
        return None

    def _inline_comment(self, span: tuple[int, int]) -> str:
        """The trailing comment of the last line of a value, if any."""
        last = self.lines[span[1] - 1]
        cleaned, _ = _strip_noise(last, None)
        # _strip_noise cuts at '#', so anything beyond the cleaned length is it.
        rest = last[len(cleaned.rstrip()):] if cleaned.strip() else last
        hash_at = rest.find('#')
        return ('  ' + rest[hash_at:].strip()) if hash_at >= 0 else ''

    def _insert_at(self, section: str) -> int:
        """Where a new key belongs in `section`.

        After the section's last value line — not after the trailing comments,
        which visually introduce whatever comes next.
        """
        rows = self.section_lines(section)
        if not rows:
            return 0
        header_idx = rows[0][0] if rows[0][2] else None
        last_value = None
        for idx, cleaned, is_header in rows:
            if is_header:
                continue
            if '=' in cleaned:
                span = None
                # Re-derive the end of this value so multi-line arrays count.
                depth = cleaned.count('[') - cleaned.count(']')
                end = idx + 1
                if depth > 0:
                    for j, c2, h2 in rows:
                        if j <= idx or h2:
                            continue
                        depth += c2.count('[') - c2.count(']')
                        end = j + 1
                        if depth <= 0:
                            break
                last_value = end
                del span
        if last_value is not None:
            return last_value
        return (header_idx + 1) if header_idx is not None else 0

    def set(self, section: str, key: str, literal: str):
        """Set `key = literal`, replacing in place or inserting."""
        span = self.find_key(section, key)
        if span:
            comment = self._inline_comment(span)
            indent = re.match(r'\s*', self.lines[span[0]]).group(0)
            self.lines[span[0]:span[1]] = [f'{indent}{key} = {literal}{comment}']
            return
        if not self.has_section(section):
            if self.lines and self.lines[-1].strip():
                self.lines.append('')
            self.lines.append(f'[{section}]')
            self.lines.append(f'{key} = {literal}')
            return
        self.lines.insert(self._insert_at(section), f'{key} = {literal}')

    def remove(self, section: str, key: str):
        span = self.find_key(section, key)
        if span:
            del self.lines[span[0]:span[1]]

    def rename(self, section: str, old: str, new: str) -> bool:
        """Rename a key, keeping its value and any trailing comment."""
        span = self.find_key(section, old)
        if not span:
            return False
        line = self.lines[span[0]]
        self.lines[span[0]] = re.sub(
            r'^(\s*)(?:"' + re.escape(old) + r'"|\'' + re.escape(old) + r'\'|'
            + re.escape(old) + r')(\s*=)', r'\1' + new + r'\2', line, count=1)
        return True


def lit(value) -> str:
    """A TOML literal for the value types this menu writes.

    A dict becomes an inline table, which is what `[secondary_model].models`
    needs — a key whose value is a table of alias to description. Falling
    through to the string branch instead, as this did until the subagent screen
    asked for one, writes the Python `repr` in quotes: valid TOML, accepted by
    the file, and rejected by Kimi's schema at startup.
    """
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return '[' + ', '.join('"' + str(v).replace('"', '\\"') + '"' for v in value) + ']'
    if isinstance(value, dict):
        return '{ ' + ', '.join(f'{k} = {lit(v)}' for k, v in value.items()) + ' }'
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


# --------------------------------------------------------------------------
# Reading the current state
# --------------------------------------------------------------------------

def load(path: Path) -> dict:
    try:
        with open(path, 'rb') as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        print(f'config.toml does not parse: {e}', file=sys.stderr)
        sys.exit(1)


def shown(data: dict, key: str, section: str = '') -> tuple[object, bool]:
    """(value, is_explicit) — falls back to Kimi's default when unset."""
    holder = data.get(section, {}) if section else data
    if isinstance(holder, dict) and key in holder:
        return holder[key], True
    return KIMI_DEFAULTS.get(key), False


# --------------------------------------------------------------------------
# Tool catalogue, borrowed from lib/list-tools.py rather than re-derived
# --------------------------------------------------------------------------

def tool_rows() -> list[tuple[str, int]]:
    """(name, tokens) for every builtin tool that is safe to disable."""
    spec = importlib.util.spec_from_file_location('list_tools', HERE / 'list-tools.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not mod.BUNDLE.exists():
        raise FileNotFoundError(mod.BUNDLE)
    src = mod.BUNDLE.read_text(errors='replace')
    sizes = mod.description_sizes()
    rows = []
    for name in mod.tool_names(src):
        if name in mod.PROTECTED:
            continue                      # not offered at all, by directive
        key = name.replace('-', '').replace('_', '').lower()
        key = mod.ALIASES.get(key, key)
        rows.append((name, round(sizes.get(key, 0) / mod.CHARS_PER_TOKEN)))
    rows.sort(key=lambda r: -r[1])
    return rows


# --------------------------------------------------------------------------
# Writing, with a backup and Kimi's own validator as the safety net
# --------------------------------------------------------------------------

def commit(path: Path, new_text: str, dry_run: bool) -> bool:
    old_text = path.read_text() if path.exists() else ''
    if old_text == new_text:
        print('no changes.')
        return True

    diff = list(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(),
                                     'config.toml', 'config.toml (new)', lineterm='',
                                     n=1))
    print()
    for line in diff:
        print('  ' + line)
    print()

    if dry_run:
        print('dry run — nothing written.')
        return True

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = path.with_suffix(f'.toml.tweakkimi-{stamp}.bak')
    if path.exists():
        shutil.copy2(path, backup)
    path.write_text(new_text)

    ok, detail = validate(path)
    if ok:
        print(f'written. backup at {backup.name}')
        return True

    if backup.exists():
        shutil.copy2(backup, path)
    print('kimi doctor rejected the result — config restored from the backup.',
          file=sys.stderr)
    print(detail, file=sys.stderr)
    return False


def validate(path: Path) -> tuple[bool, str]:
    """Kimi's own validator is the only authority on what it accepts.

    Two things this has to get right. `doctor config <path>` checks the file
    named rather than the one in the home directory, which matters as soon as
    `--config` points somewhere else. And the exit code is **0 even when the
    configuration is rejected** — trusting it would wave through exactly the
    broken file this check exists to catch, so the verdict comes from the
    output instead.
    """
    if not KIMI_BIN.exists():
        return True, 'kimi binary not found — skipped validation'
    try:
        r = subprocess.run([str(KIMI_BIN), 'doctor', 'config', str(path)],
                           capture_output=True, text=True, timeout=120)
    except Exception as e:                                  # noqa: BLE001
        return True, f'could not run kimi doctor ({e}) — skipped'
    out = ((r.stdout or '') + (r.stderr or '')).strip()
    rejected = any(l.lstrip().startswith('ERROR') for l in out.splitlines())
    accepted = any(l.lstrip().startswith('OK') for l in out.splitlines())
    return (accepted and not rejected), out[:800]


# --------------------------------------------------------------------------
# Menu
# --------------------------------------------------------------------------

def ask(prompt: str) -> str:
    """One line of free text, for the few values no list can offer.

    A path and a number cannot be picked from a list, so those two prompts
    stay. Everything else is a row now. Wrapped so a closed stdin — the state
    every smoke test and `--dry-run` runs in — reads as "nothing entered"
    rather than as an exception thrown out of a menu row.
    """
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ''


def pause(*lines: str) -> None:
    """Say something the next repaint would otherwise wipe out."""
    print()
    for line in lines:
        print(line)
    ask('\n   [enter] back ')


def fmt_state(value, explicit: bool) -> str:
    if isinstance(value, bool):
        text = 'on' if value else 'off'
    else:
        text = str(value)
    return text if explicit else f'{text}  (Kimi default, not set)'


class Editing:
    """The file under the cursor: its lines, and the parsed view of them.

    The screens read `data` and write through `doc`. Nothing reaches the disk
    until the Write row runs `commit`, so the parsed view has to be rebuilt
    from the edited lines after every change rather than re-read from the file
    — which is exactly what `reload` on each screen asks for.
    """

    def __init__(self, path: Path, doc: TomlLines, dry_run: bool = False):
        self.path = path
        self.doc = doc
        self.dry_run = dry_run
        self.rc = 0
        self.data: dict = {}
        self.refresh()

    def refresh(self) -> 'Editing':
        self.data = tomllib.loads(self.doc.text())
        return self


def sub(screen: m.Screen, st: Editing) -> None:
    """Run a submenu, then let the caller repaint on the way out."""
    m.loop(screen, st)


def screen_tools(st: Editing, rows: list[tuple[str, int]]) -> m.Screen:
    """Which builtin tools Kimi is told not to load.

    The catalogue is handed in rather than read here. It comes from the
    extracted bundle, which may be missing, and the caller is the only place
    that can say so usefully — a screen that has already been opened has no
    good way to report that it has nothing to show.

    The selection lives in this closure until Save writes it, so leaving with
    Back really does discard it, the way it did when this was a digit menu.
    """
    known = {n for n, _ in rows}
    current = set((st.data.get(S_TOOLS) or {}).get('disabled') or [])
    # Names disabled in the file that are no longer builtin tools: keep them,
    # but say so rather than dropping them silently.
    stale = sorted(current - known)

    def build(s: Editing) -> list[Item]:
        items = [Item('info', 'Each description ships in every request, so an '
                              'unused tool is a fixed per-turn tax.'),
                 Item('info', 'Load-bearing tools are not offered.'),
                 Item('sep')]
        for name, tok in rows:
            items.append(Item(
                'action', name,
                (lambda n, t: lambda x:
                 f'[{"x" if n in current else " "}] {t:>6} tokens')(name, tok),
                key=f'tool:{name}', help='enter toggles it'))
        items.append(Item('sep'))
        if stale:
            items.append(Item('info', 'also disabled, unknown to this build: '
                                      + ', '.join(stale)))
        saved = sum(t for n, t in rows if n in current)
        items.append(Item('info', f'selected: {len(current)}, saving about '
                                  f'{saved} tokens per turn'))
        items += [
            Item('action', 'Disable all', lambda x: '', key='all'),
            Item('action', 'Disable none', lambda x: '', key='none'),
            Item('action', 'Save', lambda x: 'keep this selection', key='save'),
            Item('action', 'Back', lambda x: 'discard the changes', key='back'),
        ]
        return items

    def act(s: Editing, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key == 'save':
            s.doc.set(S_TOOLS, 'disabled', lit(sorted(current | set(stale))))
            return False
        if item.key == 'all':
            current.update(known)
        elif item.key == 'none':
            current.difference_update(known)
        elif item.key.startswith('tool:'):
            current.symmetric_difference_update({item.key[5:]})
        return True

    return m.Screen(build, activate=act, reload=lambda s: s.refresh(),
                    title='Disable builtin tools')


def screen_choice(st: Editing, title: str, body: list[str], options: list[str],
                  current, apply, helps: dict | None = None,
                  recommended=None) -> m.Screen:
    """Pick one of `options`, or hand the setting back to Kimi.

    `apply(st, picked)` writes the choice, with `None` for unset. Picking
    closes the screen, because a screen whose only question has been answered
    has nothing left to offer.
    """

    def mark(opt) -> str:
        marks = []
        if opt == current:
            marks.append('current')
        if recommended is not None and opt == recommended:
            marks.append('recommended')
        return ', '.join(marks)

    def build(s: Editing) -> list[Item]:
        items = [Item('info', line) for line in body if line]
        items.append(Item('sep'))
        for opt in options:
            items.append(Item('action', opt,
                              (lambda o: lambda x: (helps or {}).get(o, ''))(opt),
                              (lambda o: lambda x: mark(o))(opt),
                              key=f'set:{opt}'))
        items += [
            Item('action', 'unset (leave it to Kimi)', lambda x: '',
                 lambda x: 'current' if current is None else '', key='unset'),
            Item('sep'),
            Item('action', 'Back', lambda x: 'change nothing', key='back'),
        ]
        return items

    def act(s: Editing, item: Item) -> bool:
        if item.key == 'unset':
            apply(s, None)
        elif item.key.startswith('set:'):
            apply(s, item.key[4:])
        return False

    return m.Screen(build, activate=act, reload=lambda s: s.refresh(),
                    title=title)


def screen_bool(st: Editing, key: str, title: str, body: list[str]) -> m.Screen:
    value, explicit = shown(st.data, key)
    rec = RECOMMENDED.get(key)

    def apply(s: Editing, picked) -> None:
        if picked is None:
            s.doc.remove('', key)
        else:
            s.doc.set('', key, lit(picked == 'on'))

    return screen_choice(st, title, body, ['on', 'off'],
                         ('on' if value else 'off') if explicit else None,
                         apply,
                         recommended=None if rec is None else ('on' if rec else 'off'))


def screen_permission(st: Editing) -> m.Screen:
    value, explicit = shown(st.data, K_PERMISSION)

    def apply(s: Editing, picked) -> None:
        if picked is None:
            s.doc.remove('', K_PERMISSION)
        else:
            s.doc.set('', K_PERMISSION, lit(picked))

    return screen_choice(st, 'Permission mode', [
        'What Kimi does before it runs a tool call.',
        'yolo skips the prompt entirely — convenient, and it means',
        'shell commands run without a confirmation step.',
    ], PERMISSION_MODES, value if explicit else None, apply, PERMISSION_HELP,
        recommended=RECOMMENDED.get(K_PERMISSION))


def screen_extra_dirs(st: Editing) -> m.Screen:
    """Additional directories to search for skills.

    The one setting in this group with a real effect: it mounts existing skill
    collections without copying them. Kimi expands `~` and resolves a relative
    path against the project root, so both forms are accepted here unchanged.
    """
    dirs = list(st.data.get(K_EXTRA_SKILL_DIRS) or [])

    def state_of(d: str) -> str:
        if d.startswith('~') or d.startswith('/'):
            return '' if Path(d).expanduser().is_dir() else '(does not exist yet)'
        return '(relative to the project root)'

    def build(s: Editing) -> list[Item]:
        items = [Item('info', 'Mount skill collections that live outside '
                              '~/.kimi-code/skills.'),
                 Item('info', '`~` is expanded; a relative path resolves against '
                              'the project root.'),
                 Item('sep')]
        for d in dirs:
            items.append(Item('action', d,
                              (lambda p: lambda x: state_of(p))(d),
                              key=f'drop:{d}', help='enter removes it'))
        if not dirs:
            items.append(Item('info', 'none configured'))
        items += [
            Item('sep'),
            Item('action', 'Add a directory', lambda x: '', key='add'),
            Item('action', 'Save', lambda x: 'keep this list', key='save'),
            Item('action', 'Back', lambda x: 'discard the changes', key='back'),
        ]
        return items

    def act(s: Editing, item: Item) -> bool:
        if item.key == 'back':
            return False
        if item.key == 'save':
            if dirs:
                s.doc.set('', K_EXTRA_SKILL_DIRS, lit(dirs))
            else:
                s.doc.remove('', K_EXTRA_SKILL_DIRS)
            return False
        if item.key == 'add':
            raw = ask('   path: ')
            if raw and raw not in dirs:
                dirs.append(raw)
        elif item.key.startswith('drop:'):
            d = item.key[5:]
            if d in dirs:
                dirs.remove(d)
        return True

    return m.Screen(build, activate=act, reload=lambda s: s.refresh(),
                    title='Extra skill directories')


def screen_loop(st: Editing) -> m.Screen:
    """Attempts per step, and the context held back for the answer.

    Both are numbers, so both still ask for a line of text. What changed is
    that the two settings are rows: you can look at one without being walked
    through the other, an answer that is not a number leaves the file alone
    instead of being carried into the next question, and ‹› hands a setting
    back to Kimi — the one thing the old prompt had no way of expressing.
    """
    message = ''

    def reset(s: Editing, item: Item, forward: bool) -> None:
        key = item.key[4:]
        nonlocal message
        s.doc.remove(S_LOOP, key)
        message = f'{key} back to Kimi\'s default'

    def build(s: Editing) -> list[Item]:
        rows = [Item('info', 'How many attempts a single step gets, and how much '
                             'of the'),
                Item('info', 'context window is held back for the answer.')]
        if message:
            rows.append(Item('info', message))
        rows.append(Item('sep'))
        for key in (K_ATTEMPTS, K_RESERVED):
            rows.append(Item('action', key,
                             (lambda k: lambda x: fmt_state(*shown(x.data, k, S_LOOP)))(key),
                             key=f'num:{key}', on_cycle=reset,
                             help='enter sets it, ‹› hands it back to Kimi'))
        rows += [Item('sep'), Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def act(s: Editing, item: Item) -> bool:
        nonlocal message
        message = ''
        if item.key == 'back':
            return False
        if item.key.startswith('num:'):
            key = item.key[4:]
            cur = shown(s.data, key, S_LOOP)[0]
            raw = ask(f'   {key} [{cur}] (enter keeps it): ')
            if raw.isdigit():
                s.doc.set(S_LOOP, key, lit(int(raw)))
                message = f'{key} = {raw}'
            elif raw:
                message = f'not written — {raw!r} is not a number'
        return True

    return m.Screen(build, activate=act, reload=lambda s: s.refresh(),
                    title='Loop control')


def subagent_rules(section: dict, subagent_flag_on: bool) -> list[str]:
    """Everything Kimi would refuse about a `[secondary_model]` section.

    These are its own rules, restated where they can still be acted on. Kimi
    enforces them in `assertValidSubagentModelConfig`, which throws
    `CONFIG_INVALID` — so a wrong section is not a setting that quietly does
    nothing.

    WHEN IT FIRES, EXACTLY
    Two call sites, both in the live engine: the constructor of
    `SessionSubagentModelsValidationService`, and
    `sessionLifecycleService.assertSubagentModelPoolPreFlight`, which awaits
    config, models and providers and then asserts. Both hang off creating a
    session — not off starting the binary. `kimi --version` does not read the
    file at all, which is worth knowing before concluding from a clean version
    check that the section is fine.

    WHY THIS IS NOT LEFT TO `kimi doctor`
    Everywhere else in this menu Kimi's own validator is the authority, and
    here it is not enough. `doctor config` accepts a pool keyed `primary` and
    accepts `force` combined with a pool — both were tried, with the
    secondary-model flag off *and* on, and doctor reported "All checked config
    files are valid" every time. The check simply is not on doctor's path. So
    the file passes validation and the session then refuses to come up, with
    the config doctor just called fine.
    """
    problems = []
    models = section.get(K_SM_MODELS) or {}
    default = section.get(K_SM_DEFAULT)
    forced = section.get(K_SM_FORCE) is True

    if 'primary' in models:
        problems.append('"primary" is reserved — it is how the main agent asks '
                        'for the primary model, so it cannot name a pool entry')
    if forced and models:
        problems.append('force cannot be combined with a pool: the pool exists to '
                        'offer a choice, and force removes it')
    if forced and default is None:
        problems.append('force needs default_model — there is nothing to force to')
    if models and default is None:
        problems.append('a pool needs default_model to say which entry is used '
                        'unless the main agent picks another')
    if models and default is not None and default not in models:
        problems.append(f'default_model "{default}" is not one of the pool entries '
                        f'({", ".join(sorted(models))})')
    return problems


def screen_subagent(st: Editing) -> m.Screen:
    """Which model a subagent runs on.

    This is tweakcc's "Subagent models" seen from Kimi's side, and it needs no
    patch at all: `[secondary_model]` is a registered section in the live
    engine. It is richer than tweakcc's per-agent-type list, too — a *pool* of
    named models the main agent may pick from, or one model forced on every
    subagent.

    Nothing here does anything until the `secondary-model` flag is on, which is
    why that state is the first thing the screen says. The flag lives in the
    launcher profile (`KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL`) or in Kimi's own
    `/experiments`; it is deliberately not written from here, because a config
    file that silently turns on an experiment is the kind of surprise this menu
    exists to avoid.
    """
    message = ''

    def flag_on(s: Editing) -> bool:
        exp = s.data.get('experimental') or {}
        return exp.get('secondary_model') is True or exp.get('secondaryModel') is True

    def reset(s: Editing, item: Item, forward: bool) -> None:
        nonlocal message
        key = item.key.split(':', 1)[1]
        s.doc.remove(S_SECONDARY, key)
        message = f'{key} back to Kimi\'s default'

    def build(s: Editing) -> list[Item]:
        section = s.data.get(S_SECONDARY) or {}
        models = section.get(K_SM_MODELS) or {}
        rows = [Item('info', 'Which model a newly spawned subagent runs on.')]
        if not flag_on(s):
            rows.append(Item('info', 'the secondary-model flag is off — none of this '
                                     'takes effect until it is on'))
        for problem in subagent_rules(section, flag_on(s)):
            rows.append(Item('info', f'Kimi would refuse this: {problem}'))
        if message:
            rows.append(Item('info', message))
        rows.append(Item('sep'))
        rows.append(Item('cycle', K_SM_FORCE,
                         lambda x: fmt_state(*shown(x.data, K_SM_FORCE, S_SECONDARY)),
                         key='force', choices=['on', 'off'],
                         help='On pins every subagent to default_model and removes '
                              'the choice. Cannot be combined with a pool.'))
        rows.append(Item('action', K_SM_DEFAULT,
                         lambda x: fmt_state(*shown(x.data, K_SM_DEFAULT, S_SECONDARY)),
                         key=f'txt:{K_SM_DEFAULT}', on_cycle=reset,
                         help='The model used unless the main agent picks another. '
                              'Must be one of the pool entries when a pool exists.'))
        rows.append(Item('info', f'pool: {len(models)} model(s)'
                                 + (f' — {", ".join(sorted(models))}' if models else '')))
        rows.append(Item('action', 'Add a pool model', lambda x: '', key='pool:add',
                         help='An alias from your model catalogue, plus a short '
                              'description the main agent sees.'))
        if models:
            rows.append(Item('action', 'Remove a pool model', lambda x: '',
                             key='pool:remove'))
        rows += [Item('sep'), Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def act(s: Editing, item: Item) -> bool:
        nonlocal message
        message = ''
        if item.key == 'back':
            return False
        section = dict(s.data.get(S_SECONDARY) or {})
        models = dict(section.get(K_SM_MODELS) or {})

        if item.key.startswith('txt:'):
            key = item.key[4:]
            cur = shown(s.data, key, S_SECONDARY)[0]
            raw = ask(f'   {key} [{cur}] (enter keeps it): ').strip()
            if not raw:
                return True
            section[key] = raw
        elif item.key == 'pool:add':
            alias = ask('   model alias: ').strip()
            if not alias:
                return True
            note = ask('   what it is good for: ').strip()
            models[alias] = note
            section[K_SM_MODELS] = models
        elif item.key == 'pool:remove':
            alias = ask(f'   which of {", ".join(sorted(models))}: ').strip()
            if alias not in models:
                message = f'not removed — "{alias}" is not in the pool'
                return True
            models.pop(alias)
            section[K_SM_MODELS] = models

        # Kimi's rules are checked before the write, not after: an invalid
        # section stops Kimi from starting at all, and finding that out at the
        # next launch is the worst possible moment.
        problems = subagent_rules(section, flag_on(s))
        if problems:
            message = 'not written — ' + problems[0]
            return True

        if item.key.startswith('txt:'):
            s.doc.set(S_SECONDARY, item.key[4:], lit(section[item.key[4:]]))
            message = f'{item.key[4:]} = {section[item.key[4:]]}'
        elif models:
            s.doc.set(S_SECONDARY, K_SM_MODELS, lit(models))
            message = f'pool has {len(models)} model(s)'
        else:
            s.doc.remove(S_SECONDARY, K_SM_MODELS)
            message = 'pool emptied'
        return True

    def cyc(s: Editing, item: Item, forward: bool) -> None:
        nonlocal message
        s.refresh()
        if item.key != 'force':
            return
        section = dict(s.data.get(S_SECONDARY) or {})
        value, explicit = shown(s.data, K_SM_FORCE, S_SECONDARY)
        section[K_SM_FORCE] = not (value is True) if explicit else True
        problems = subagent_rules(section, flag_on(s))
        if problems:
            message = 'not written — ' + problems[0]
            return
        s.doc.set(S_SECONDARY, K_SM_FORCE, lit(section[K_SM_FORCE]))
        message = ''

    return m.Screen(build, activate=act, cycle=cyc, reload=lambda s: s.refresh(),
                    title='Subagent model')


def toolsets_path() -> Path:
    """Where the named tool sets live.

    Deliberately not in `config.toml`. That file is Kimi's, its schema is
    strict, and `kimi doctor` rejects a key it does not know — a preset stored
    there would fail validation the moment anyone ran it. This is tweakkimi's
    own file, in tweakkimi's own format, next to the other one.
    """
    return HERE.parent / 'toolsets.conf'


def read_toolsets(path: Path | None = None) -> dict:
    """`name = ToolA,ToolB` per line. Comments and blanks are skipped."""
    path = path or toolsets_path()
    out = {}
    try:
        text = path.read_text()
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, _, tools = line.partition('=')
        out[name.strip()] = [t.strip() for t in tools.split(',') if t.strip()]
    return out


def write_toolsets(sets: dict, path: Path | None = None) -> None:
    path = path or toolsets_path()
    lines = ['# Named tool sets for tweakkimi. Applying one writes its list to',
             '# `[tools] disabled` in config.toml; nothing else here is read by Kimi.',
             '# One `name = Tool, Tool` per line.', '']
    for name in sorted(sets):
        lines.append(f'{name} = {", ".join(sets[name])}')
    path.write_text('\n'.join(lines) + '\n')


def screen_toolsets(st: Editing, path: Path | None = None) -> m.Screen:
    """Named sets of disabled tools, applied in one keystroke.

    tweakcc builds this out of an eleven-step splice into the binary. Here it
    is a file and one config key, because Kimi already evaluates `[tools]
    disabled` against the catalogue the model is handed — the feature exists,
    only the switching between several of them does not.
    """
    path = path or toolsets_path()
    message = ''

    def build(s: Editing) -> list[Item]:
        sets = read_toolsets(path)
        current = sorted((s.data.get(S_TOOLS) or {}).get('disabled') or [])
        rows = [Item('info', 'A set is a list of tools to disable. Applying one '
                             'replaces the current list.'),
                Item('info', f'now disabled: {", ".join(current) if current else "none"}')]
        if message:
            rows.append(Item('info', message))
        rows.append(Item('sep'))
        for name in sorted(sets):
            same = sorted(sets[name]) == current
            rows.append(Item('action', name,
                             (lambda tools, is_now: lambda x:
                              f'{len(tools)} tool(s)' + ('   ← in use' if is_now else ''))(
                                 sets[name], same),
                             key=f'use:{name}',
                             help='enter applies it, ‹› deletes it',
                             on_cycle=drop))
        if not sets:
            rows.append(Item('info', 'none saved yet'))
        rows += [Item('sep'),
                 Item('action', 'Save what is disabled now', lambda x: '', key='save',
                      help='Names the current list so you can come back to it.'),
                 Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def drop(s: Editing, item: Item, forward: bool) -> None:
        nonlocal message
        sets = read_toolsets(path)
        name = item.key[4:]
        if sets.pop(name, None) is not None:
            write_toolsets(sets, path)
            message = f'deleted "{name}" — config.toml is unchanged'

    def act(s: Editing, item: Item) -> bool:
        nonlocal message
        message = ''
        if item.key == 'back':
            return False
        if item.key == 'save':
            current = sorted((s.data.get(S_TOOLS) or {}).get('disabled') or [])
            if not current:
                message = 'nothing to save — no tool is disabled right now'
                return True
            name = ask('   name for this set: ').strip()
            if not name:
                return True
            if '=' in name or ',' in name:
                message = 'not saved — a name cannot contain "=" or ","'
                return True
            sets = read_toolsets(path)
            sets[name] = current
            write_toolsets(sets, path)
            message = f'saved "{name}" with {len(current)} tool(s)'
        elif item.key.startswith('use:'):
            name = item.key[4:]
            tools = read_toolsets(path).get(name, [])
            if tools:
                s.doc.set(S_TOOLS, 'disabled', lit(sorted(tools)))
            else:
                s.doc.remove(S_TOOLS, 'disabled')
            message = f'applied "{name}" — write the file to keep it'
        return True

    return m.Screen(build, activate=act, reload=lambda s: s.refresh(),
                    title='Tool sets')


def screen_thinking(st: Editing) -> m.Screen:
    """How hard the model thinks, and whether its thinking is carried forward.

    This is the live lever, and finding that out took a detour worth recording.
    `KIMI_MODEL_THINKING_EFFORT` looks like the obvious switch and appears in
    the old engine's `resolveKimiEnvThinkingEffort`, which nothing in
    `agent-core-v2` calls. It works anyway, but by another route: the `thinking`
    config section registers that variable as the environment binding for
    `forced_effort`, and `agent-core-v2`'s `resolveThinkingEffortForModel` reads
    the section. So the file below and that variable are the same setting seen
    from two sides — which is why both are offered rather than one.

    `forced_effort` bypasses the model's own support list where `effort` does
    not; Kimi still clamps a level the model cannot do, so neither can ask for
    something the provider would reject.
    """
    message = ''

    def reset(s: Editing, item: Item, forward: bool) -> None:
        nonlocal message
        key = item.key.split(':', 1)[1]
        s.doc.remove(S_THINKING, key)
        message = f'{key} back to Kimi\'s default'

    def step_effort(s: Editing, item: Item, forward: bool) -> None:
        nonlocal message
        s.refresh()
        key = item.key[4:]
        value, explicit = shown(s.data, key, S_THINKING)
        here = EFFORTS.index(value) if explicit and value in EFFORTS else -1
        s.doc.set(S_THINKING, key, lit(EFFORTS[(here + (1 if forward else -1)) % len(EFFORTS)]))
        message = ''

    def build(s: Editing) -> list[Item]:
        rows = [Item('info', 'Reasoning effort. `effort` is the ordinary level;'),
                Item('info', '`forced_effort` overrides it and ignores the '
                             'model\'s support list.')]
        if message:
            rows.append(Item('info', message))
        rows.append(Item('sep'))
        rows.append(Item('cycle', 'enabled',
                         lambda x: fmt_state(*shown(x.data, K_THINK_ENABLED, S_THINKING)),
                         key='bool:' + K_THINK_ENABLED, choices=['on', 'off'],
                         help='Off stops the model thinking at all.'))
        for key in (K_THINK_EFFORT, K_THINK_FORCED):
            rows.append(Item('action', key,
                             (lambda k: lambda x: fmt_state(*shown(x.data, k, S_THINKING)))(key),
                             key=f'eff:{key}', on_cycle=step_effort,
                             help='‹› picks a level, enter hands it back to Kimi'))
        rows.append(Item('action', K_THINK_KEEP,
                         lambda x: fmt_state(*shown(x.data, K_THINK_KEEP, S_THINKING)),
                         key=f'txt:{K_THINK_KEEP}', on_cycle=reset,
                         help='Whether earlier thinking is re-sent. `all` keeps it, '
                              '`off` drops it. Keeping it costs tokens.'))
        rows += [Item('sep'), Item('action', 'Back', lambda x: '', key='back')]
        return rows

    def act(s: Editing, item: Item) -> bool:
        nonlocal message
        message = ''
        if item.key == 'back':
            return False
        if item.key.startswith('eff:'):
            # Enter is the way back to Kimi's own choice, because a level you
            # want is one ‹› away and a level you no longer want has nowhere
            # else to go.
            key = item.key[4:]
            s.doc.remove(S_THINKING, key)
            message = f'{key} back to Kimi\'s default'
        elif item.key.startswith('txt:'):
            key = item.key[4:]
            cur = shown(s.data, key, S_THINKING)[0]
            raw = ask(f'   {key} [{cur}] (enter keeps it): ')
            if raw:
                s.doc.set(S_THINKING, key, lit(raw))
                message = f'{key} = {raw}'
        return True

    def cyc(s: Editing, item: Item, forward: bool) -> None:
        nonlocal message
        # Read the document, not the view it was parsed from. The loop
        # refreshes after every action, so in the running menu the two agree —
        # but a second arrow press within one action would otherwise step from
        # the value before the first, and walk in place.
        s.refresh()
        if item.key.startswith('bool:'):
            key = item.key[5:]
            value, explicit = shown(s.data, key, S_THINKING)
            s.doc.set(S_THINKING, key, lit(not (value is True) if explicit else False))
            message = ''

    return m.Screen(build, activate=act, cycle=cyc, reload=lambda s: s.refresh(),
                    title='Reasoning')


def header(st: Editing) -> list[str]:
    return ['', 'tweakkimi — Kimi configuration', str(st.path)]


def screen_main(st: Editing) -> m.Screen:
    """The top level. Its row keys are the values `--item` accepts.

    Keeping them as the digits the old menu printed is what makes `--item 5`
    still open the permission screen: the main menu of tweakkimi passes those
    digits, and nothing else has to know they came from a numbered list.
    """

    def build(s: Editing) -> list[Item]:
        disabled = (s.data.get(S_TOOLS) or {}).get('disabled') or []
        extra = s.data.get(K_EXTRA_SKILL_DIRS) or []
        loop = s.data.get(S_LOOP) or {}
        return [
            Item('submenu', 'Disable builtin tools',
                 lambda x: f'{len(disabled)} disabled', key='1',
                 help='Every tool description ships in every request.'),
            Item('submenu', 'Builtin product skills',
                 lambda x: fmt_state(*shown(x.data, K_BUILTIN_SKILLS)), key='2',
                 help='Kimi\'s own product skills, on or off.'),
            Item('submenu', 'Merge skill directories',
                 lambda x: fmt_state(*shown(x.data, K_MERGE_SKILLS))
                 + '   [no effect in 0.36.0]', key='3'),
            Item('submenu', 'Extra skill directories',
                 lambda x: f'{len(extra)} configured' if extra else 'none',
                 key='4', help='Mount skill collections from elsewhere.'),
            Item('submenu', 'Permission mode',
                 lambda x: fmt_state(*shown(x.data, K_PERMISSION)), key='5',
                 help='What Kimi does before it runs a tool call.'),
            Item('submenu', 'Loop control',
                 lambda x: (f'{loop.get(K_ATTEMPTS, KIMI_DEFAULTS[K_ATTEMPTS])} '
                            f'attempts, '
                            f'{loop.get(K_RESERVED, KIMI_DEFAULTS[K_RESERVED])} '
                            f'reserved'), key='6'),
            Item('submenu', 'Reasoning',
                 lambda x: (lambda t: ', '.join(f'{k}={v}' for k, v in t.items())
                            if t else 'Kimi\'s own')(x.data.get(S_THINKING) or {}),
                 key='7',
                 help='How hard the model thinks, and whether thinking is re-sent.'),
            Item('submenu', 'Tool sets',
                 lambda x: (lambda n: f'{n} saved' if n else 'none saved')(
                     len(read_toolsets())),
                 key='8',
                 help='Named lists of disabled tools, applied in one keystroke.'),
            Item('submenu', 'Subagent model',
                 lambda x: (lambda sec: 'forced' if sec.get(K_SM_FORCE) is True
                            else (f"pool of {len(sec.get(K_SM_MODELS) or {})}"
                                  if sec.get(K_SM_MODELS) else
                                  (sec.get(K_SM_DEFAULT) or 'same as the main agent')))(
                     x.data.get(S_SECONDARY) or {}),
                 key='9',
                 help='Which model a subagent runs on. Needs the secondary-model flag.'),
            # Environment-only settings (fullscreen, transcript window) live in
            # the launcher profile; they cannot live in config.toml.
            Item('sep'),
            Item('action', 'Write changes',
                 lambda x: f'to {x.path.name}', key='w',
                 help='Shows the diff first, and keeps a backup.'),
            Item('action', 'Quit without writing', lambda x: '', key='q'),
        ]

    return m.Screen(build, header=header, activate=open_item,
                    reload=lambda s: s.refresh(), help_line=m.HELP_ROOT)


def open_item(st: Editing, item) -> bool:
    """Open one top-level entry. Returns False when the menu should close.

    Takes either an `Item` or the bare key behind it, because `--item` arrives
    as a string long before there is a row to hand over.
    """
    key = item.key if isinstance(item, Item) else item
    if key == 'q':
        print('nothing written.')
        return False
    if key == 'w':
        st.rc = 0 if commit(st.path, st.doc.text(), st.dry_run) else 1
        return False
    if key == '1':
        try:
            rows = tool_rows()
        except FileNotFoundError as e:
            pause(f'   no extracted bundle at {e}.',
                  '   Run: ./kimi-patch.sh --extract')
            return True
        sub(screen_tools(st, rows), st)
    elif key == '2':
        sub(screen_bool(st, K_BUILTIN_SKILLS, 'Builtin product skills', [
            'Kimi ships product skills (update-config, check-kimi-code-docs).',
            'Turning them off removed two of three listed skills in testing.',
        ]), st)
    elif key == '3':
        sub(screen_bool(st, K_MERGE_SKILLS, 'Merge all skill directories', [
            'Whether every brand directory is searched for skills and agent',
            'profiles, or only the first one that exists.',
            'In 0.36.0 this changes nothing: each category lists exactly one',
            'directory ("skills", "agents"), and with a single entry both',
            'branches of pushBrandGroup do the same thing. There is no',
            'context saving here either way. Kept in the menu so the setting',
            'is visible rather than mysterious.',
        ]), st)
    elif key == '4':
        sub(screen_extra_dirs(st), st)
    elif key == '5':
        sub(screen_permission(st), st)
    elif key == '6':
        sub(screen_loop(st), st)
    elif key == '7':
        sub(screen_thinking(st), st)
    elif key == '8':
        sub(screen_toolsets(st), st)
    elif key == '9':
        sub(screen_subagent(st), st)
    st.refresh()
    return True


def interactive(path: Path, dry_run: bool, first: str = '') -> int:
    original = path.read_text() if path.exists() else ''
    st = Editing(path, TomlLines(original), dry_run)

    # The deprecated spelling is renamed on sight — Kimi warns about it on
    # every start and ignores the value.
    if st.doc.rename(S_LOOP, K_ATTEMPTS_OLD, K_ATTEMPTS):
        print(f'note: renamed {K_ATTEMPTS_OLD} to {K_ATTEMPTS} (deprecated spelling)')
        st.refresh()

    # `--item N` jumps straight into one entry, so the top-level menu can offer
    # "Tools" and "Permissions" as separate doors without duplicating anything
    # behind them. Afterwards the normal loop takes over, which is what makes
    # the write prompt still reachable.
    if first and open_item(st, first) is False:
        return st.rc
    m.loop(screen_main(st), st)
    return st.rc


# --------------------------------------------------------------------------
# Selfcheck
# --------------------------------------------------------------------------

SAMPLE = '''# leading comment, must survive
default_model = "kimi-code/k3"

[loop_control]
max_retries_per_step = 3   # trailing comment
reserved_context_size = 50000

[services.moonshot_search]
base_url = "https://example.invalid/search"   # foreign, do not touch
api_key = ""

[models."kimi-code/k3"]
capabilities = [ "thinking", "tool_use" ]
'''


def _selfcheck():
    checks = []

    def ok(name, cond, detail=''):
        checks.append((name, cond, detail))

    # 1. rename the deprecated key, keeping value and inline comment
    d = TomlLines(SAMPLE)
    assert d.rename(S_LOOP, K_ATTEMPTS_OLD, K_ATTEMPTS)
    t = d.text()
    ok('deprecated key renamed', 'max_attempts_per_step = 3' in t)
    ok('inline comment kept on rename', '# trailing comment' in t)
    ok('old key gone', K_ATTEMPTS_OLD not in t)

    # 2. comments and foreign sections survive any edit
    d.set('', K_PERMISSION, lit('yolo'))
    d.set('', K_MERGE_SKILLS, lit(False))
    t = d.text()
    ok('leading comment survives', t.startswith('# leading comment'))
    ok('foreign section untouched', '# foreign, do not touch' in t
       and 'https://example.invalid/search' in t)

    # 3. a root key lands before the first section header, or it would be
    #    parsed as part of that section — the subtle way to corrupt a file
    parsed = tomllib.loads(t)
    ok('root key is root-level', parsed.get(K_PERMISSION) == 'yolo',
       f'got {parsed.get(K_PERMISSION)!r}')
    ok('second root key is root-level', parsed.get(K_MERGE_SKILLS) is False)
    ok('loop_control intact', parsed['loop_control'][K_ATTEMPTS] == 3)

    # 4. replacing an existing value must not duplicate the key
    d.set('', K_PERMISSION, lit('manual'))
    t = d.text()
    ok('value replaced, not duplicated', t.count(K_PERMISSION) == 1)
    ok('replacement took effect', tomllib.loads(t)[K_PERMISSION] == 'manual')

    # 5. missing key added to an existing section
    d.set(S_LOOP, K_RESERVED, lit(120000))
    ok('existing section key updated',
       tomllib.loads(d.text())['loop_control'][K_RESERVED] == 120000)

    # 6. a whole new section
    d.set(S_TOOLS, 'disabled', lit(['CronCreate', 'CronList']))
    parsed = tomllib.loads(d.text())
    ok('new section created', parsed['tools']['disabled'] == ['CronCreate', 'CronList'])

    # 7. removal
    d.remove('', K_MERGE_SKILLS)
    ok('key removed', K_MERGE_SKILLS not in tomllib.loads(d.text()))

    # 7b. extra skill dirs: a root-level string array, added then emptied
    d.set('', K_EXTRA_SKILL_DIRS, lit(['~/skills', '../shared/skills']))
    parsed = tomllib.loads(d.text())
    ok('extra skill dirs written as root array',
       parsed.get(K_EXTRA_SKILL_DIRS) == ['~/skills', '../shared/skills'])
    ok('tilde path stored verbatim for Kimi to expand',
       '~/skills' in parsed.get(K_EXTRA_SKILL_DIRS, []))
    d.remove('', K_EXTRA_SKILL_DIRS)
    ok('extra skill dirs removed again',
       K_EXTRA_SKILL_DIRS not in tomllib.loads(d.text()))

    # 8. a multi-line array is one value, not three lines of structure
    multi = TomlLines('[tools]\ndisabled = [\n  "A",\n  "B",\n]\nother = 1\n')
    multi.set(S_TOOLS, 'disabled', lit(['C']))
    parsed = tomllib.loads(multi.text())
    ok('multi-line array replaced whole', parsed['tools']['disabled'] == ['C'])
    ok('sibling key survived multi-line replace', parsed['tools']['other'] == 1)

    # 9. a bracket inside a string is not a section header
    tricky = TomlLines('a = "[not_a_section]"\n\n[real]\nb = 1\n')
    tricky.set('real', 'c', lit(2))
    parsed = tomllib.loads(tricky.text())
    ok('string bracket ignored', parsed['a'] == '[not_a_section]'
       and parsed['real'] == {'b': 1, 'c': 2})

    # 10. a '#' inside a string is not a comment
    hashy = TomlLines('url = "https://x.invalid/#frag"\n')
    hashy.set('', 'other', lit(1))
    ok('hash in string preserved',
       tomllib.loads(hashy.text())['url'] == 'https://x.invalid/#frag')

    # 11. round-trip with no edits changes nothing at all
    ok('no-op round trip is byte identical', TomlLines(SAMPLE).text() == SAMPLE)

    # 12. the real config, if present, round-trips untouched
    if CONFIG.exists():
        real = CONFIG.read_text()
        ok('real config round-trips', TomlLines(real).text() == real)

    # ----------------------------------------------------------------------
    # 13. the screens
    #
    # Every screen used to end in `input()` and a digit; they are Screens now,
    # so the same navigation checks apply to all of them, in the same shape
    # main-menu.py uses. Below that, one check per screen for what it actually
    # writes — navigation being right is no comfort if the file ends up wrong.
    # ----------------------------------------------------------------------

    @contextlib.contextmanager
    def quiet():
        """Screens talk to the user; the self-check only wants the verdict."""
        with contextlib.redirect_stdout(io.StringIO()):
            yield

    @contextlib.contextmanager
    def answering(*texts: str):
        """Stand in for the prompts that still read a line of text.

        Substituting the module's `ask` is what lets the path and number rows
        be driven with no terminal at all, the same way `FakeKeys` stands in
        for the keyboard everywhere else.

        Several answers are consumed in order, because one row may ask twice —
        a pool entry wants an alias and then a description. The last answer
        repeats once the list runs out, so the common single-answer case reads
        exactly as it did before.
        """
        global ask
        queue = list(texts) or ['']

        def scripted(prompt):
            return queue.pop(0) if len(queue) > 1 else queue[0]

        real, ask = ask, scripted
        try:
            yield
        finally:
            ask = real

    CATALOGUE = [('Alpha', 900), ('Beta', 120), ('Gamma', 30)]

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / 'config.toml'
        path.write_text(SAMPLE)

        def editing(text=SAMPLE, dry_run=False):
            return Editing(path, TomlLines(text), dry_run)

        st = editing()
        screens = [
            ('main', screen_main(st), 'tweakkimi — Kimi configuration'),
            ('tools', screen_tools(st, CATALOGUE), 'Disable builtin tools'),
            ('skills', screen_bool(st, K_BUILTIN_SKILLS, 'Builtin product skills',
                                   ['what the skills are']), 'Builtin product skills'),
            ('permission', screen_permission(st), 'Permission mode'),
            ('extra dirs', screen_extra_dirs(st), 'Extra skill directories'),
            ('loop', screen_loop(st), 'Loop control'),
        ]
        for name, screen, marker in screens:
            rows = screen.build(st)
            ok(f'{name}: builds rows', len(rows) > 0)
            ok(f'{name}: has a selectable row', any(r.selectable for r in rows))

            # Navigation must never come to rest on a fact or a rule.
            facts = {i for i, r in enumerate(rows) if not r.selectable}
            pos = m.first_selectable(rows)
            landed = set()
            for _ in range(len(rows) * 2):
                pos, _, _ = m.handle(screen, st, rows, pos, 'down')
                landed.add(pos)
            ok(f'{name}: navigation skips facts and rules',
               not landed & facts, sorted(landed & facts))
            ok(f'{name}: every selectable row is reachable',
               landed == set(range(len(rows))) - facts,
               sorted(set(range(len(rows))) - facts - landed))

            # The way out closes the screen, and so does escape.
            leave = next(i for i, r in enumerate(rows) if r.key in ('back', 'q'))
            with quiet():
                _, keep, _ = m.handle(screen, st, rows, leave, 'enter')
            ok(f'{name}: the closing row closes the screen', keep is False)
            ok(f'{name}: esc leaves',
               m.handle(screen, st, rows, m.first_selectable(rows), 'esc')[1] is False)

            # The mouse mapping is built by the same pass that draws, so it can
            # be checked against the drawn lines rather than a second model.
            row_map: dict[int, int] = {}
            lines = m.render(screen, st, rows, m.first_selectable(rows), row_map)
            ok(f'{name}: {marker!r} drawn', any(marker in l for l in lines))
            ok(f'{name}: every selectable row is mapped',
               len(row_map) == len([r for r in rows if r.selectable]), len(row_map))
            astray = [lines[n] for n, ri in row_map.items()
                      if rows[ri].label not in lines[n]]
            ok(f'{name}: every mapped line holds its row', not astray, astray[:1])

        # -- tools: toggling and saving ------------------------------------
        st = editing()
        tools = screen_tools(st, CATALOGUE)
        rows = tools.build(st)
        beta = next(i for i, r in enumerate(rows) if r.key == 'tool:Beta')
        with quiet():
            m.handle(tools, st, rows, beta, 'enter')
        rows = tools.build(st)
        ok('a toggled tool is ticked',
           any(r.key == 'tool:Beta' and r.value(st).startswith('[x]') for r in rows))
        ok('the summary follows the selection',
           any(r.kind == 'info' and 'selected: 1, saving about 120' in r.label
               for r in rows))
        save = next(i for i, r in enumerate(rows) if r.key == 'save')
        with quiet():
            _, keep, _ = m.handle(tools, st, rows, save, 'enter')
        ok('saving closes the tool screen', keep is False)
        ok('saving writes exactly the toggled name',
           tomllib.loads(st.doc.text())[S_TOOLS]['disabled'] == ['Beta'],
           tomllib.loads(st.doc.text()).get(S_TOOLS))

        # Back discards, where Save would have written.
        st = editing()
        tools = screen_tools(st, CATALOGUE)
        rows = tools.build(st)
        with quiet():
            m.handle(tools, st, rows, beta, 'enter')
            m.handle(tools, st, rows,
                     next(i for i, r in enumerate(rows) if r.key == 'back'), 'enter')
        ok('back writes nothing', S_TOOLS not in tomllib.loads(st.doc.text()))

        # All and none reach every offered tool and nothing beyond it.
        st = editing()
        tools = screen_tools(st, CATALOGUE)
        rows = tools.build(st)
        with quiet():
            m.handle(tools, st, rows,
                     next(i for i, r in enumerate(rows) if r.key == 'all'), 'enter')
            m.handle(tools, st, rows, save, 'enter')
        ok('all disables the whole catalogue',
           tomllib.loads(st.doc.text())[S_TOOLS]['disabled'] == ['Alpha', 'Beta', 'Gamma'])

        # A name disabled in the file that this build no longer offers is
        # reported and survives the save, rather than vanishing silently.
        st = editing(SAMPLE + '\n[tools]\ndisabled = ["Ghost"]\n')
        tools = screen_tools(st, CATALOGUE)
        rows = tools.build(st)
        ok('an unknown disabled name is reported',
           any(r.kind == 'info' and 'Ghost' in r.label for r in rows))
        with quiet():
            m.handle(tools, st, rows,
                     next(i for i, r in enumerate(rows) if r.key == 'save'), 'enter')
        ok('an unknown disabled name survives a save',
           tomllib.loads(st.doc.text())[S_TOOLS]['disabled'] == ['Ghost'])

        # -- choice screens: current, recommended, set and unset -----------
        st = editing(f'{K_PERMISSION} = "yolo"\n')
        perm = screen_permission(st)
        rows = perm.build(st)
        ok('the current option is marked',
           [r.label for r in rows
            if r.key.startswith('set:') and 'current' in r.note(st)] == ['yolo'])
        ok('the recommended option is marked',
           [r.label for r in rows
            if r.key.startswith('set:') and 'recommended' in r.note(st)] == ['yolo'])
        unset = next(i for i, r in enumerate(rows) if r.key == 'unset')
        with quiet():
            _, keep, _ = m.handle(perm, st, rows, unset, 'enter')
        ok('unset closes the screen', keep is False)
        ok('unset removes the key again',
           K_PERMISSION not in tomllib.loads(st.doc.text()))

        st = editing()
        perm = screen_permission(st)
        rows = perm.build(st)
        with quiet():
            m.handle(perm, st, rows,
                     next(i for i, r in enumerate(rows) if r.key == 'set:auto'), 'enter')
        ok('picking an option writes it',
           tomllib.loads(st.doc.text())[K_PERMISSION] == 'auto')

        st = editing()
        skills = screen_bool(st, K_BUILTIN_SKILLS, 'Builtin product skills', ['body'])
        rows = skills.build(st)
        with quiet():
            m.handle(skills, st, rows,
                     next(i for i, r in enumerate(rows) if r.key == 'set:off'), 'enter')
        ok('a boolean is written as a boolean',
           tomllib.loads(st.doc.text())[K_BUILTIN_SKILLS] is False)

        # -- extra skill directories ---------------------------------------
        st = editing()
        dirs = screen_extra_dirs(st)
        rows = dirs.build(st)
        with answering('~/skills'), quiet():
            m.handle(dirs, st, rows,
                     next(i for i, r in enumerate(rows) if r.key == 'add'), 'enter')
        rows = dirs.build(st)
        ok('an added directory becomes a row',
           any(r.key == 'drop:~/skills' for r in rows))
        rel = editing('extra_skill_dirs = ["shared/skills"]\n')
        ok('a relative path says so',
           next(r for r in screen_extra_dirs(rel).build(rel)
                if r.key.startswith('drop:')).value(rel)
           == '(relative to the project root)')
        with quiet():
            m.handle(dirs, st, rows,
                     next(i for i, r in enumerate(rows) if r.key == 'save'), 'enter')
        ok('saving writes the array',
           tomllib.loads(st.doc.text())[K_EXTRA_SKILL_DIRS] == ['~/skills'])

        st = editing('extra_skill_dirs = ["~/skills"]\n')
        dirs = screen_extra_dirs(st)
        rows = dirs.build(st)
        with quiet():
            m.handle(dirs, st, rows,
                     next(i for i, r in enumerate(rows) if r.key == 'drop:~/skills'),
                     'enter')
        rows = dirs.build(st)
        ok('removing empties the list',
           not any(r.key.startswith('drop:') for r in rows))
        with quiet():
            m.handle(dirs, st, rows,
                     next(i for i, r in enumerate(rows) if r.key == 'save'), 'enter')
        ok('an empty list removes the key',
           K_EXTRA_SKILL_DIRS not in tomllib.loads(st.doc.text()))

        # -- loop control: only a number is written ------------------------
        st = editing()
        lp = screen_loop(st)
        rows = lp.build(st)
        attempts = next(i for i, r in enumerate(rows) if r.key == f'num:{K_ATTEMPTS}')
        before = st.doc.text()
        with answering('not a number'), quiet():
            m.handle(lp, st, rows, attempts, 'enter')
        ok('a non-number writes nothing', st.doc.text() == before)
        with answering(''), quiet():
            m.handle(lp, st, rows, attempts, 'enter')
        ok('an empty answer writes nothing', st.doc.text() == before)
        with answering('7'), quiet():
            m.handle(lp, st, rows, attempts, 'enter')
        ok('a number is written',
           tomllib.loads(st.doc.text())[S_LOOP][K_ATTEMPTS] == 7)

        # A screen that announces what it just did grows a row, so both the
        # row and its position have to be looked up again every time.
        def press(screen, state, key, stroke):
            rows = screen.build(state)
            idx = next(i for i, r in enumerate(rows) if r.key == key)
            return m.handle(screen, state, rows, idx, stroke)

        def row_of(screen, state, key):
            return next(r for r in screen.build(state) if r.key == key)

        # `reload` is what the loop runs after an action; the row's value has
        # to follow the edited lines, not the view they were parsed from.
        ok('the row shows what the file now says',
           row_of(lp, lp.reload(st), f'num:{K_ATTEMPTS}').value(st) == '7',
           row_of(lp, st, f'num:{K_ATTEMPTS}').value(st))

        # ‹› is the only way to say "no opinion" about a number, so it has to
        # remove the key rather than write a default back into the file.
        _, _, reloaded = press(lp, st, f'num:{K_ATTEMPTS}', 'left')
        ok('‹› asks for a reload', reloaded)
        ok('‹› hands the setting back to Kimi',
           K_ATTEMPTS not in (tomllib.loads(st.doc.text()).get(S_LOOP) or {}),
           tomllib.loads(st.doc.text()).get(S_LOOP))
        ok('the reset is announced',
           any(r.kind == 'info' and 'back to Kimi' in r.label
               for r in lp.build(lp.reload(st))))
        ok('the row falls back to the default it is given',
           row_of(lp, lp.reload(st), f'num:{K_ATTEMPTS}').value(st)
           == fmt_state(KIMI_DEFAULTS[K_ATTEMPTS], False))

        # Back carries no `on_cycle`, so the arrows must not reach it.
        before = st.doc.text()
        _, keep, _ = press(lp, st, 'back', 'right')
        ok('‹› on a plain row does nothing', keep and st.doc.text() == before)

        # -- reasoning -----------------------------------------------------
        st = editing()
        th = screen_thinking(st)
        rows = th.build(st)
        ok('reasoning builds rows', len(rows) > 0)
        dead = [i for i, r in enumerate(rows) if not r.selectable]
        pos = m.first_selectable(rows)
        for _ in range(len(rows) * 2):
            pos, _, _ = m.handle(th, st, rows, pos, 'down')
            ok('reasoning: never lands on an unselectable row', pos not in dead, pos)
        ok('reasoning: back closes', press(th, st, 'back', 'enter')[1] is False)
        ok('reasoning: esc closes', m.handle(th, st, rows, 0, 'esc')[1] is False)

        # ‹› walks the levels and writes each one; the file spelling is what
        # Kimi reads, so it is what is asserted.
        press(th, st, f'eff:{K_THINK_EFFORT}', 'right')
        first = tomllib.loads(st.doc.text())[S_THINKING][K_THINK_EFFORT]
        ok('an effort level is written', first in EFFORTS, first)
        press(th, st, f'eff:{K_THINK_EFFORT}', 'right')
        second = tomllib.loads(st.doc.text())[S_THINKING][K_THINK_EFFORT]
        ok('‹› advances to the next level',
           EFFORTS.index(second) == (EFFORTS.index(first) + 1) % len(EFFORTS),
           (first, second))

        # Enter is the way back to Kimi's own choice, because a level you want
        # is one arrow away and a level you no longer want has nowhere to go.
        press(th, st, f'eff:{K_THINK_EFFORT}', 'enter')
        ok('enter hands the level back to Kimi',
           K_THINK_EFFORT not in (tomllib.loads(st.doc.text()).get(S_THINKING) or {}),
           tomllib.loads(st.doc.text()).get(S_THINKING))

        # forced_effort is a separate key, not the same one under another name.
        press(th, st, f'eff:{K_THINK_FORCED}', 'right')
        section = tomllib.loads(st.doc.text())[S_THINKING]
        ok('forced_effort is its own key',
           K_THINK_FORCED in section and K_THINK_EFFORT not in section, section)

        # `keep` takes a word no list can hold, so it asks — and a refusal to
        # answer must leave the file alone.
        before = st.doc.text()
        with answering(''), quiet():
            press(th, st, f'txt:{K_THINK_KEEP}', 'enter')
        ok('an empty answer writes nothing', st.doc.text() == before)
        with answering('all'), quiet():
            press(th, st, f'txt:{K_THINK_KEEP}', 'enter')
        ok('keep is written',
           tomllib.loads(st.doc.text())[S_THINKING][K_THINK_KEEP] == 'all')
        press(th, st, f'txt:{K_THINK_KEEP}', 'left')
        ok('‹› hands keep back to Kimi',
           K_THINK_KEEP not in tomllib.loads(st.doc.text())[S_THINKING])

        # -- tool sets -------------------------------------------------------
        # The presets are tweakkimi's own file; the only thing that reaches
        # config.toml is the list a set writes into `[tools] disabled`.
        sets_path = Path(td) / 'toolsets.conf'
        st = editing('[tools]\ndisabled = ["CronCreate", "CronList"]\n')
        ts = screen_toolsets(st, sets_path)

        ok('no sets to begin with', read_toolsets(sets_path) == {})
        with answering('cron'), quiet():
            press(ts, st, 'save', 'enter')
        ok('the current list is saved under a name',
           read_toolsets(sets_path) == {'cron': ['CronCreate', 'CronList']},
           read_toolsets(sets_path))

        # A name that would break the file's own format is refused rather than
        # written and misread on the next start.
        with answering('a,b'), quiet():
            press(ts, st, 'save', 'enter')
        ok('a comma in a name is refused', list(read_toolsets(sets_path)) == ['cron'])

        # Applying a set replaces the list; it does not merge with it.
        st = editing('[tools]\ndisabled = ["Goal"]\n')
        ts = screen_toolsets(st, sets_path)
        with quiet():
            press(ts, st, 'use:cron', 'enter')
        ok('applying a set replaces the disabled list',
           tomllib.loads(st.doc.text())[S_TOOLS]['disabled'] == ['CronCreate', 'CronList'],
           tomllib.loads(st.doc.text())[S_TOOLS])

        # ‹› deletes the set and must leave config.toml alone.
        before = st.doc.text()
        press(ts, st, 'use:cron', 'right')
        ok('‹› deletes the set', read_toolsets(sets_path) == {})
        ok('deleting a set does not touch config.toml', st.doc.text() == before)

        ok('tool sets: back closes', press(ts, st, 'back', 'enter')[1] is False)

        # -- subagent model --------------------------------------------------
        # The four rules are Kimi's own, and getting one wrong does not make a
        # setting inert — it makes Kimi refuse to start. So they are checked
        # here as a unit, before any screen is involved.
        ok('a plain default_model is fine',
           subagent_rules({K_SM_DEFAULT: 'fast'}, True) == [])
        ok('"primary" is refused as a pool key',
           any('reserved' in p for p in
               subagent_rules({K_SM_MODELS: {'primary': ''}, K_SM_DEFAULT: 'primary'}, True)))
        ok('force plus a pool is refused',
           any('force cannot be combined' in p for p in
               subagent_rules({K_SM_FORCE: True, K_SM_DEFAULT: 'a',
                               K_SM_MODELS: {'a': ''}}, True)))
        ok('force without default_model is refused',
           any('force needs default_model' in p for p in
               subagent_rules({K_SM_FORCE: True}, True)))
        ok('a pool without default_model is refused',
           any('needs default_model' in p for p in
               subagent_rules({K_SM_MODELS: {'a': ''}}, True)))
        ok('default_model outside the pool is refused',
           any('is not one of the pool entries' in p for p in
               subagent_rules({K_SM_MODELS: {'a': ''}, K_SM_DEFAULT: 'b'}, True)))
        ok('a valid pool passes',
           subagent_rules({K_SM_MODELS: {'a': 'cheap'}, K_SM_DEFAULT: 'a'}, True) == [])

        # The rules are checked here rather than left to Kimi's validator
        # because its validator does not catch them: the check behind them is
        # gated on the secondary-model flag, and doctor runs without it. This
        # asserts that gap rather than trusting the note about it.
        with tempfile.TemporaryDirectory() as vd:
            probe = Path(vd) / 'config.toml'
            probe.write_text('[secondary_model]\nforce = true\n'
                             'default_model = "a"\nmodels = { a = "x" }\n')
            accepted, _ = validate(probe)
            ok('kimi doctor does not catch force-plus-pool', accepted)
            # …and not because the flag was off, which was the first guess.
            import os as _os
            env = dict(_os.environ, KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL='1')
            if KIMI_BIN.exists():
                r = subprocess.run([str(KIMI_BIN), 'doctor', 'config', str(probe)],
                                   capture_output=True, text=True, timeout=120, env=env)
                out = ((r.stdout or '') + (r.stderr or ''))
                ok('nor does it with the flag on',
                   not any(l.lstrip().startswith('ERROR') for l in out.splitlines()),
                   out[:200])
        ok('but this menu does',
           subagent_rules({K_SM_FORCE: True, K_SM_DEFAULT: 'a',
                           K_SM_MODELS: {'a': 'x'}}, True) != [])

        # A dict has to reach the file as an inline table. Writing the Python
        # repr in quotes is valid TOML, passes doctor, and is rejected by the
        # schema at startup — which is what this did before the pool needed it.
        ok('a dict becomes an inline table',
           lit({'a': 'cheap', 'b': 'thorough'}) == '{ a = "cheap", b = "thorough" }',
           lit({'a': 'cheap', 'b': 'thorough'}))

        st = editing()
        sa = screen_subagent(st)
        rows = sa.build(st)
        ok('subagent builds rows', len(rows) > 0)
        dead = [i for i, r in enumerate(rows) if not r.selectable]
        pos = m.first_selectable(rows)
        for _ in range(len(rows) * 2):
            pos, _, _ = m.handle(sa, st, rows, pos, 'down')
            ok('subagent: never lands on an unselectable row', pos not in dead, pos)
        ok('subagent: back closes', press(sa, st, 'back', 'enter')[1] is False)

        # The screen says so when the flag that makes any of this matter is off.
        ok('an inactive flag is stated',
           any(r.kind == 'info' and 'flag is off' in r.label for r in rows))

        # A refused combination must leave the file untouched and say why.
        st = editing('[secondary_model]\nmodels = { a = "cheap" }\ndefault_model = "a"\n')
        sa = screen_subagent(st)
        before = st.doc.text()
        press(sa, st, 'force', 'right')
        ok('force is refused while a pool exists', st.doc.text() == before)
        ok('and the reason is shown',
           any(r.kind == 'info' and 'not written' in r.label for r in sa.build(st)),
           [r.label for r in sa.build(st) if r.kind == 'info'])

        # Adding a pool entry writes the table.
        st = editing('[secondary_model]\ndefault_model = "a"\n')
        sa = screen_subagent(st)
        with answering('a', 'cheap and quick'), quiet():
            press(sa, st, 'pool:add', 'enter')
        ok('a pool entry is written',
           (tomllib.loads(st.doc.text())[S_SECONDARY].get(K_SM_MODELS) or {}) == {'a': 'cheap and quick'},
           tomllib.loads(st.doc.text())[S_SECONDARY])

        # An entry Kimi reserves is refused at the point it is typed.
        before = st.doc.text()
        with answering('primary', 'nope'), quiet():
            press(sa, st, 'pool:add', 'enter')
        ok('a reserved pool key is refused', st.doc.text() == before)

        # -- the top level -------------------------------------------------
        st = editing()
        keys = [r.key for r in screen_main(st).build(st) if r.selectable]
        digits = [k for k in keys if k.isdigit()]
        # Numbered without gaps, in order. Checked as a shape rather than as a
        # fixed list, because the list is the thing that grows: a new screen
        # should extend the sequence, not fail a test that hardcoded it.
        ok('--item still reaches every entry',
           digits == [str(n) for n in range(1, len(digits) + 1)], keys)
        ok('every numbered entry opens a screen', len(digits) >= 7, digits)
        with quiet():
            ok('quit closes the menu', open_item(st, 'q') is False)

        st = editing(dry_run=True)
        st.doc.set('', K_PERMISSION, lit('yolo'))
        with quiet():
            ok('write closes the menu', open_item(st, 'w') is False)
        ok('a dry run leaves the file alone', path.read_text() == SAMPLE)
        ok('a dry run reports success', st.rc == 0)

    bad = [c for c in checks if not c[1]]
    for name, cond, detail in checks:
        print(f'  {"ok  " if cond else "FAIL"} {name}' + (f'  {detail}' if detail and not cond else ''))
    if bad:
        print(f'\nconfig-menu selfcheck: {len(bad)} FAILED')
        return 1
    print(f'\nconfig-menu selfcheck: ok ({len(checks)} checks)')
    return 0


def main() -> int:
    args = sys.argv[1:]
    if '--selfcheck' in args:
        return _selfcheck()
    path = CONFIG
    first = ''
    for i, a in enumerate(args):
        if a == '--config' and i + 1 < len(args):
            path = Path(args[i + 1])
        if a == '--item' and i + 1 < len(args):
            first = args[i + 1].lower()
    if not path.exists():
        print(f'no config at {path}', file=sys.stderr)
        return 1
    return interactive(path, '--dry-run' in args, first)


if __name__ == '__main__':
    sys.exit(main())

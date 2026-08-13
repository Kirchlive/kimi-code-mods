#!/usr/bin/env python3
"""Interactive menu for the Kimi settings that are worth changing but hard to find.

This writes `~/.kimi-code/config.toml`. It never touches the binary — everything
here is configuration Kimi already supports and simply does not document.

    python3 lib/config-menu.py             # interactive
    python3 lib/config-menu.py --dry-run   # show the diff, write nothing
    python3 lib/config-menu.py --selfcheck # prove the TOML editing is lossless

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

import difflib
import importlib.util
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
    """A TOML literal for the value types this menu writes."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return '[' + ', '.join('"' + str(v).replace('"', '\\"') + '"' for v in value) + ']'
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
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 'q'


def fmt_state(value, explicit: bool) -> str:
    if isinstance(value, bool):
        text = 'on' if value else 'off'
    else:
        text = str(value)
    return text if explicit else f'{text}  (Kimi default, not set)'


def menu_tools(doc: TomlLines, data: dict):
    try:
        rows = tool_rows()
    except FileNotFoundError as e:
        print(f'\nno extracted bundle at {e}. Run: ./kimi-patch.sh --extract\n')
        return
    current = set((data.get(S_TOOLS) or {}).get('disabled') or [])
    known = {n for n, _ in rows}
    # Names disabled in the file that are no longer builtin tools: keep them,
    # but say so rather than dropping them silently.
    stale = sorted(current - known)

    while True:
        print('\n  Disable builtin tools')
        print('  Each description ships in every request, so an unused tool is a')
        print('  fixed per-turn tax. Load-bearing tools are not offered.\n')
        for i, (name, tok) in enumerate(rows, 1):
            mark = 'x' if name in current else ' '
            print(f'   {i:>2}  [{mark}] {name:<22}{tok:>6} tokens')
        if stale:
            print(f'\n   also disabled, unknown to this build: {", ".join(stale)}')
        saved = sum(t for n, t in rows if n in current)
        print(f'\n   selected: {len(current)}   saving about {saved} tokens per turn')
        print('   number toggles · a=all · n=none · s=save · q=back')
        choice = ask('   > ').lower()

        if choice in ('q', ''):
            return
        if choice == 'a':
            current |= known
            continue
        if choice == 'n':
            current -= known
            continue
        if choice == 's':
            doc.set(S_TOOLS, 'disabled', lit(sorted(current | set(stale))))
            return
        if choice.isdigit() and 1 <= int(choice) <= len(rows):
            name = rows[int(choice) - 1][0]
            current.symmetric_difference_update({name})
            continue
        print('   ?')


def menu_choice(title: str, body: list[str], options: list[str],
                current, helps: dict | None = None, recommended=None):
    """Pick one of `options`, or return None to leave it to Kimi."""
    while True:
        print(f'\n  {title}')
        for line in body:
            print(f'  {line}')
        print()
        for i, opt in enumerate(options, 1):
            mark = '*' if opt == current else ' '
            hint = f'  — {helps[opt]}' if helps and opt in helps else ''
            star = '  [recommended]' if recommended is not None and opt == recommended else ''
            print(f'   {i}  {mark} {opt}{hint}{star}')
        print('   u  unset (leave it to Kimi)')
        print('   q  back')
        choice = ask('   > ').lower()
        if choice in ('q', ''):
            return ('keep', None)
        if choice == 'u':
            return ('unset', None)
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return ('set', options[int(choice) - 1])
        print('   ?')


def menu_bool(doc: TomlLines, key: str, title: str, body: list[str], data: dict):
    value, explicit = shown(data, key)
    rec = RECOMMENDED.get(key)
    action, picked = menu_choice(
        title, body, ['on', 'off'],
        ('on' if value else 'off') if explicit else None,
        recommended=None if rec is None else ('on' if rec else 'off'))
    if action == 'set':
        doc.set('', key, lit(picked == 'on'))
    elif action == 'unset':
        doc.remove('', key)


def menu_extra_dirs(doc: TomlLines, data: dict):
    """Additional directories to search for skills.

    The one setting in this group with a real effect: it mounts existing skill
    collections without copying them. Kimi expands `~` and resolves a relative
    path against the project root, so both forms are accepted here unchanged.
    """
    dirs = list(data.get(K_EXTRA_SKILL_DIRS) or [])
    while True:
        print('\n  Extra skill directories')
        print('  Mount skill collections that live outside ~/.kimi-code/skills.')
        print('  `~` is expanded; a relative path resolves against the project root.')
        print()
        if dirs:
            for i, d in enumerate(dirs, 1):
                probe = Path(d).expanduser()
                note = ''
                if d.startswith('~') or d.startswith('/'):
                    note = '' if probe.is_dir() else '   (does not exist yet)'
                else:
                    note = '   (relative to the project root)'
                print(f'   {i:>2}  {d}{note}')
        else:
            print('   none configured')
        print('\n   a=add · number removes · s=save · q=back')
        choice = ask('   > ').lower()

        if choice in ('q', ''):
            return
        if choice == 's':
            if dirs:
                doc.set('', K_EXTRA_SKILL_DIRS, lit(dirs))
            else:
                doc.remove('', K_EXTRA_SKILL_DIRS)
            return
        if choice == 'a':
            raw = ask('   path: ').strip()
            if raw and raw not in dirs:
                dirs.append(raw)
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(dirs):
            dirs.pop(int(choice) - 1)
            continue
        print('   ?')


def menu_loop(doc: TomlLines, data: dict):
    section = data.get(S_LOOP) or {}
    print('\n  Loop control')
    print('  How many attempts a single step gets, and how much of the context')
    print('  window is held back for the answer.\n')
    for key in (K_ATTEMPTS, K_RESERVED):
        cur = section.get(key, KIMI_DEFAULTS[key])
        raw = ask(f'   {key} [{cur}] (enter keeps, q aborts): ')
        if raw.lower() == 'q':
            return
        if raw == '':
            continue
        if not raw.isdigit():
            print('   not a number — skipped')
            continue
        doc.set(S_LOOP, key, lit(int(raw)))


def render(doc: TomlLines, path: Path):
    data = tomllib.loads(doc.text())
    disabled = (data.get(S_TOOLS) or {}).get('disabled') or []
    loop = data.get(S_LOOP) or {}

    b_skills, b_set = shown(data, K_BUILTIN_SKILLS)
    m_skills, m_set = shown(data, K_MERGE_SKILLS)
    perm, p_set = shown(data, K_PERMISSION)

    extra = data.get(K_EXTRA_SKILL_DIRS) or []

    print('\ntweakkimi — Kimi configuration')
    print(f'{path}\n')
    print(f'   1  Disable builtin tools        {len(disabled)} disabled')
    print(f'   2  Builtin product skills       {fmt_state(b_skills, b_set)}')
    print(f'   3  Merge all skill directories  {fmt_state(m_skills, m_set)}'
          '   [no effect in 0.36.0]')
    extra_state = f'{len(extra)} configured' if extra else 'none'
    print(f'   4  Extra skill directories      {extra_state}')
    print(f'   5  Permission mode              {fmt_state(perm, p_set)}')
    print(f'   6  Loop control                 '
          f'{loop.get(K_ATTEMPTS, KIMI_DEFAULTS[K_ATTEMPTS])} attempts, '
          f'{loop.get(K_RESERVED, KIMI_DEFAULTS[K_RESERVED])} reserved')
    # Environment-only settings (fullscreen, transcript window) arrive here
    # once the launcher exists; they cannot live in config.toml.
    print()
    print('   w  write changes      q  quit without writing')
    return data


def interactive(path: Path, dry_run: bool) -> int:
    original = path.read_text() if path.exists() else ''
    doc = TomlLines(original)

    # The deprecated spelling is renamed on sight — Kimi warns about it on
    # every start and ignores the value.
    if doc.rename(S_LOOP, K_ATTEMPTS_OLD, K_ATTEMPTS):
        print(f'note: renamed {K_ATTEMPTS_OLD} to {K_ATTEMPTS} (deprecated spelling)')

    while True:
        data = render(doc, path)
        choice = ask('\n > ').lower()
        if choice == 'q':
            print('nothing written.')
            return 0
        if choice == 'w':
            return 0 if commit(path, doc.text(), dry_run) else 1
        if choice == '1':
            menu_tools(doc, data)
        elif choice == '2':
            menu_bool(doc, K_BUILTIN_SKILLS, 'Builtin product skills', [
                'Kimi ships product skills (update-config, check-kimi-code-docs).',
                'Turning them off removed two of three listed skills in testing.',
            ], data)
        elif choice == '3':
            menu_bool(doc, K_MERGE_SKILLS, 'Merge all skill directories', [
                'Whether every brand directory is searched for skills and agent',
                'profiles, or only the first one that exists.',
                '',
                'In 0.36.0 this changes nothing: each category lists exactly one',
                'directory ("skills", "agents"), and with a single entry both',
                'branches of pushBrandGroup do the same thing. There is no',
                'context saving here either way. Kept in the menu so the setting',
                'is visible rather than mysterious.',
            ], data)
        elif choice == '4':
            menu_extra_dirs(doc, data)
        elif choice == '5':
            value, explicit = shown(data, K_PERMISSION)
            action, picked = menu_choice(
                'Permission mode', [
                    'What Kimi does before it runs a tool call.',
                    'yolo skips the prompt entirely — convenient, and it means',
                    'shell commands run without a confirmation step.',
                ], PERMISSION_MODES, value if explicit else None, PERMISSION_HELP,
                recommended=RECOMMENDED.get(K_PERMISSION))
            if action == 'set':
                doc.set('', K_PERMISSION, lit(picked))
            elif action == 'unset':
                doc.remove('', K_PERMISSION)
        elif choice == '6':
            menu_loop(doc, data)
        else:
            print(' ?')


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
    for i, a in enumerate(args):
        if a == '--config' and i + 1 < len(args):
            path = Path(args[i + 1])
    if not path.exists():
        print(f'no config at {path}', file=sys.stderr)
        return 1
    return interactive(path, '--dry-run' in args)


if __name__ == '__main__':
    sys.exit(main())

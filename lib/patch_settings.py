"""Settings that belong to a patch rather than to Kimi.

Kimi's own settings live in `config.toml`, the launcher's in
`env-profile.conf`. A patch has neither: it is JavaScript spliced into the
bundle, and anything it should know has to be decided while the patch runs.
`patch-settings.conf` is that channel — plain `key=value` lines, read by the
patch scripts at patch time and by the menu when it draws their state.

Deliberately dumb. No sections, no types, no quoting rules: a patch reading
this file with three lines of JavaScript must get the same answer as the menu
reading it with this module. Comments and unknown keys survive an edit, so a
patch may keep its own settings here without the menu understanding them.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / 'patch-settings.conf'

# The keys the menu knows about, with the value used when the file says
# nothing. Kept here so a patch and the menu cannot disagree about the default.
DEFAULTS = {
    'suggestion_height': 'default',   # default | half | full
    'wd_command': 'off',              # on | off
    'click_cursor': 'off',            # on | off
}

CHOICES = {
    'suggestion_height': ['default', 'half', 'full'],
    'wd_command': ['off', 'on'],
    'click_cursor': ['off', 'on'],
}

LINE_RE = re.compile(r'^\s*([A-Za-z_][\w.-]*)\s*=\s*(.*?)\s*$')


def load(path: Path | None = None) -> dict:
    """Every key in the file, with defaults filled in for what is missing."""
    path = path or SETTINGS
    values = dict(DEFAULTS)
    try:
        text = path.read_text()
    except OSError:
        return values
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        m = LINE_RE.match(line)
        if m:
            values[m.group(1)] = m.group(2)
    return values


def get(key: str, path: Path | None = None) -> str:
    return load(path).get(key, DEFAULTS.get(key, ''))


def set_value(key: str, value: str, path: Path | None = None) -> None:
    """Write one key, replacing it in place if it is already there.

    In place matters: a patch author may have left a comment above their
    setting, and rewriting the file from a dict would throw it away.
    """
    path = path or SETTINGS
    try:
        lines = path.read_text().split('\n')
        trailing_nl = lines and lines[-1] == ''
        if trailing_nl:
            lines.pop()
    except OSError:
        lines, trailing_nl = [], True

    for i, line in enumerate(lines):
        if line.lstrip().startswith('#'):
            continue
        m = LINE_RE.match(line)
        if m and m.group(1) == key:
            lines[i] = f'{key}={value}'
            break
    else:
        if not lines:
            lines = ['# tweakkimi patch settings — read by patches/*.js at patch time.',
                     '# One key=value per line. See lib/patch_settings.py.']
        lines.append(f'{key}={value}')

    path.write_text('\n'.join(lines) + ('\n' if trailing_nl else ''))


def cycle(key: str, forward: bool = True, path: Path | None = None) -> str:
    """Advance a setting to its next allowed value and store it."""
    options = CHOICES.get(key)
    if not options:
        return get(key, path)
    current = get(key, path)
    idx = options.index(current) if current in options else 0
    nxt = options[(idx + (1 if forward else -1)) % len(options)]
    set_value(key, nxt, path)
    return nxt


def _selfcheck() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'patch-settings.conf'

        assert load(p) == DEFAULTS, 'missing file must yield the defaults'

        set_value('suggestion_height', 'half', p)
        assert get('suggestion_height', p) == 'half'

        # Replacing a value must not duplicate the key.
        set_value('suggestion_height', 'full', p)
        assert p.read_text().count('suggestion_height') == 1
        assert get('suggestion_height', p) == 'full'

        # Comments and foreign keys survive an edit.
        p.write_text('# keep me\nother_thing=42\nsuggestion_height=half\n')
        set_value('wd_command', 'on', p)
        text = p.read_text()
        assert '# keep me' in text and 'other_thing=42' in text
        assert load(p)['other_thing'] == '42'
        assert load(p)['wd_command'] == 'on'
        assert load(p)['suggestion_height'] == 'half'

        # Cycling walks the list and wraps around.
        p.write_text('')
        assert cycle('suggestion_height', path=p) == 'half'
        assert cycle('suggestion_height', path=p) == 'full'
        assert cycle('suggestion_height', path=p) == 'default'
        assert cycle('suggestion_height', forward=False, path=p) == 'full'

        # An unknown key is returned unchanged rather than invented.
        assert cycle('nonexistent', path=p) == ''

    print('patch_settings selfcheck: ok')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(_selfcheck())

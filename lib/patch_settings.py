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
    'agents_md_names': 'off',         # off | claude | all
    'read_line_numbers': 'on',        # on | off
    'expanded_by_default': 'off',     # off | thinking | tools | both
    'read_limits': 'default',         # default | moderate | large
    'auto_accept_plan': 'off',        # on | off
    'effort_router': 'off',           # off | pin | free
    'spinner_style': 'default',       # default | a preset | custom
    'spinner_mirror': 'off',          # on runs the frames forwards then back
    'spinner_interval_ms': 'default',  # default, or 20..2000
    'spinner_frames': 'default',      # the frames `custom` uses, space separated
    # The second spinner. Kimi turns the moon while it waits on the model or on
    # a tool, and the braille set while it thinks, so the two are separate
    # things to look at and separate things to set. `follow` keeps them equal,
    # which is what the single setting used to do and therefore what an
    # existing patch-settings.conf still means.
    'working_style': 'follow',        # follow | default | a preset | custom
    'working_mirror': 'off',          # on runs the frames forwards then back
    'working_frames': 'default',      # the frames `custom` uses, space separated
    'thinking_verbs': 'off',          # on | off
    'thinking_verbs_list': 'default',  # the words, comma separated
    'thinking_verbs_format': '{}',    # {} is the word
    'user_message_marker': 'default',  # default, or the prefix itself
    'user_message_border': 'off',     # off | round | single | double | bold | topbottom
    'user_message_style': 'default',  # default | plain | italic | dim | underline | strikethrough
    'input_box_border': 'default',    # default | off | single | double | bold
}

CHOICES = {
    'suggestion_height': ['default', 'half', 'full'],
    'wd_command': ['off', 'on'],
    'click_cursor': ['off', 'on'],
    'agents_md_names': ['off', 'claude', 'all'],
    'read_line_numbers': ['on', 'off'],
    'expanded_by_default': ['off', 'thinking', 'tools', 'both'],
    'read_limits': ['default', 'moderate', 'large'],
    'auto_accept_plan': ['off', 'on'],
    'effort_router': ['off', 'pin', 'free'],
    'spinner_style': ['default', 'braille', 'dots', 'moon', 'blocks',
                      'wave', 'glow', 'colors', 'arc', 'star', 'custom'],
    'spinner_mirror': ['off', 'on'],
    # `default` leads, the way it does on every other style list — Kimi's own
    # answer first, then the ways to depart from it. `follow` is the value the
    # setting starts on, which the note beside the row says; being second in
    # the list does not make it less the default.
    'working_style': ['default', 'follow', 'braille', 'dots', 'moon', 'blocks',
                      'wave', 'glow', 'colors', 'arc', 'star', 'custom'],
    'working_mirror': ['off', 'on'],
    # A duration is a number, but only a handful of them are worth having: below
    # 40 ms the difference stops being visible and above 400 the spinner reads
    # as stuck. Offering the useful ones as a list is what lets the whole screen
    # be driven with the arrow keys.
    'spinner_interval_ms': ['default', '40', '60', '80', '100', '120', '160',
                            '200', '300', '400'],
    'thinking_verbs': ['off', 'on'],
    'user_message_border': ['off', 'round', 'single', 'double', 'bold', 'topbottom'],
    'user_message_style': ['default', 'plain', 'italic', 'dim', 'underline',
                           'strikethrough'],
    'input_box_border': ['default', 'off', 'single', 'double', 'bold'],
}

# Four settings take a value no list can hold: the message marker, your own
# spinner frames, your own verbs and the format they are drawn in. They are
# registered in DEFAULTS above but deliberately absent here, and the menu reads
# that absence as "open a field" rather than "cycle" — which is why every key
# belongs in DEFAULTS and only some in CHOICES. A key in neither is invisible
# to the menu, which is the one state that would be a mistake.
FREE_TEXT = sorted(set(DEFAULTS) - set(CHOICES))

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
            # Keep the spacing the line already had. Both forms parse the
            # same, so writing `key=value` over a file that reads `key = value`
            # changes nothing except how it looks — and this file is meant to
            # be read and edited by hand, where a line that suddenly loses its
            # spacing looks like something happened to it.
            spaced = re.match(r'^\s*[A-Za-z_][\w.-]*(\s+)=', line)
            lines[i] = f'{key} = {value}' if spaced else f'{key}={value}'
            break
    else:
        if not lines:
            lines = ['# kimi-code-mods patch settings — read by patches/*.js at patch time.',
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

        # A line's own spacing survives being written. Both forms parse the
        # same, so this is only about how the file reads — which matters,
        # because it is meant to be edited by hand and a line that silently
        # loses its spacing looks like something happened to it.
        p.write_text('spaced = one\ntight=two\n')
        set_value('spaced', 'ONE', p)
        set_value('tight', 'TWO', p)
        assert 'spaced = ONE' in p.read_text(), p.read_text()
        assert 'tight=TWO' in p.read_text(), p.read_text()
        assert load(p)['spaced'] == 'ONE' and load(p)['tight'] == 'TWO'

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

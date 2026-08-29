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
    # Whether releasing a mouse-drag selection copies it to the clipboard
    # (OSC 52). `off` keeps the highlight and leaves the clipboard alone —
    # see patches/89-copy-on-mark.js.
    'copy_on_mark': 'on',             # on | off
    'agents_md_names': 'off',         # off | claude | all
    'read_line_numbers': 'on',        # on | off
    'expanded_by_default': 'off',     # off | on
    'read_limits': '1000',            # 500 | 1000 | 2000 | 5000 — 1000 is Kimi's own
    'auto_accept_plan': 'off',        # on | off
    'effort_router': 'off',           # off | pin | free
    'spinner_style': 'kimi-code-mods',  # kimi-code-mods | default | a preset | custom
    'spinner_mirror': 'on',           # off runs the frames forwards only
    'spinner_interval_ms': 'default',  # default, or 20..2000
    'spinner_frames': 'default',      # the frames `custom` uses, space separated
    # The second spinner. Kimi turns the moon while it waits on the model or on
    # a tool, and the braille set while it thinks, so the two are separate
    # things to look at and separate things to set. `follow` keeps them equal,
    # which is what the single setting used to do and therefore what an
    # existing patch-settings.conf still means.
    'working_style': 'follow',        # follow | default | a preset | custom
    'working_mirror': 'on',           # off runs the frames forwards only
    'working_frames': 'default',      # the frames `custom` uses, space separated
    'thinking_verbs': 'off',          # on | off
    'thinking_verbs_list': 'default',  # the words, comma separated
    'thinking_verbs_format': '{}',    # {} is the word
    'user_message_marker': 'default',  # default, or the prefix itself
    'user_message_border': 'off',     # off | round | single | double | bold | topbottom
    'user_message_style': 'default',  # default | plain | italic | dim | underline | strikethrough
    'input_box_border': 'round',      # off | round | single | double | bold | topbottom
    'input_box_prompt': 'default',    # default | none — the "> " and its indent
    # The alternate screen buffer. Kimi reads KIMI_CODE_TUI_FULL_SCREEN for
    # this, which only reaches it when it is started through a launcher that
    # exports the variable. As a patch it holds however Kimi is started.
    'fullscreen': 'off',              # on | off
    'welcome_banner': 'on',           # on | off — the greeting and the horns
    'cron_drop_dir': 'off',           # on | off — adopt <sessionDir>/cron/*.json drops
    # A standing list of subagents under the composer. `all` also keeps the
    # ones that just finished, which is the half that overrides Kimi's own
    # pruning of foreground-only records — see patches/82-agent-dock.js.
    'agent_dock': 'off',              # off | running | all
    # How many agents the dock shows at once. Free text in the file, cycled
    # 1-10 in the menu — see patches/82-agent-dock.js.
    'agent_dock_rows': '5',           # 1-20
    # Whether a subagent runs detached from the turn. `always` forces it, so
    # the composer stays usable while agents work — see
    # patches/86-agent-background-default.js.
    'agent_background': 'default',    # default | always | immediate
    # A thinking block while it runs and what it leaves behind: `full` keeps
    # it fully expanded forever, `keep` folds it to Kimi's three lines at the
    # end — see patches/92-thinking-display.js.
    'thinking_display': 'compact',      # compact | full | keep
    # The @-file completion: Kimi's own plain list, or the wrapping list the
    # slash commands have at half or nearly full height — see
    # patches/90-at-file-suggestions.js and patches/20-suggestion-list-half-height.js.
    'at_file_suggestions': 'default',  # default | half | full
    # Where the context gauge sits: the footer's second line, or the row above
    # the composer — see patches/91-context-position.js.
    'context_position': 'bottom',     # bottom | top
    # A prompt sent mid-turn steers the running turn at the next step boundary
    # instead of queuing for a new one — see patches/95-steer-mid-turn.js.
    'steer_mid_turn': 'off',          # on | off
    # Colours for the text typed into the input box and the frame around your
    # own messages — the input box frame itself is themed (`border` /
    # `borderFocus` tokens), not patched. The menu cycles the named list; a
    # #rrggbb value works from the file — see patches/94-colors.js.
    'input_box_text_color': 'default',
    'user_message_border_color': 'default',
    # How the text typed into the input box is drawn — `default` is plain,
    # Kimi's own — see patches/94-colors.js.
    'input_box_style': 'default',     # default | plain | italic | dim | underline | strikethrough
    # The tool-call headers: `bash_one_liner` shows the command itself instead
    # of "Ran a command", `tool_call_used` keeps Kimi's Used/Using words —
    # see patches/88-bash-one-liner.js.
    'bash_one_liner': 'off',          # on | off
    'tool_call_used': 'on',           # on | off
    # The rotating hints in the status line — see patches/96-status-hints.js.
    'status_hints': 'on',             # on | off
}

CHOICES = {
    'suggestion_height': ['default', 'half', 'full'],
    'wd_command': ['off', 'on'],
    'click_cursor': ['off', 'on'],
    'copy_on_mark': ['on', 'off'],
    'agents_md_names': ['off', 'claude', 'all'],
    'read_line_numbers': ['on', 'off'],
    'expanded_by_default': ['off', 'on'],
    'read_limits': ['500', '1000', '2000', '5000'],
    'auto_accept_plan': ['off', 'on'],
    'effort_router': ['off', 'pin', 'free'],
    'spinner_style': ['kimi-code-mods', 'default', 'braille', 'dots', 'moon',
                      'blocks', 'wave', 'glow', 'arc', 'star', 'custom'],
    'spinner_mirror': ['off', 'on'],
    # `follow` leads because it is the value the setting starts on, with Kimi's
    # own moon (`default`) behind it.
    # No `moon` here: `default` already is Kimi's moon, and offering the same
    # frames twice under two names asks the reader to spot that they are the
    # same. The patch still accepts `working_style = moon` from a file written
    # by hand — it is the menu that has nothing to add by listing it. `colors`
    # is likewise still accepted; the menu names that set `kimi-code-mods`, the
    # way the thinking list does.
    'working_style': ['follow', 'default', 'kimi-code-mods', 'braille', 'dots',
                      'blocks', 'wave', 'glow', 'arc', 'star', 'custom'],
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
    'input_box_border': ['off', 'round', 'single', 'double', 'bold', 'topbottom'],
    'input_box_prompt': ['default', 'none'],
    'fullscreen': ['off', 'on'],
    'welcome_banner': ['off', 'on'],
    'cron_drop_dir': ['off', 'on'],
    'agent_dock': ['off', 'running', 'all'],
    'agent_dock_rows': ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'],
    'agent_background': ['default', 'always', 'immediate'],
    'at_file_suggestions': ['default', 'half', 'full'],
    'thinking_display': ['compact', 'full', 'keep'],
    'context_position': ['bottom', 'top'],
    'steer_mid_turn': ['on', 'off'],
    'input_box_style': ['default', 'plain', 'italic', 'dim', 'underline',
                        'strikethrough'],
    'bash_one_liner': ['off', 'on'],
    'tool_call_used': ['on', 'off'],
    'status_hints': ['on', 'off'],
}
COLOR_CHOICES = ['default', 'red', 'green', 'yellow', 'blue', 'magenta',
                 'cyan', 'white', 'gray']
CHOICES['input_box_text_color'] = COLOR_CHOICES
CHOICES['user_message_border_color'] = COLOR_CHOICES

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

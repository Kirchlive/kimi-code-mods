# kimi-code-mods — the README demo.
#
#   vhs assets/demo.tape        # writes assets/demo.gif
#
# Needs `brew install vhs`, which brings ttyd and ffmpeg. Re-render after a Kimi
# release rather than keeping an old recording: the menu's rows and the version
# in the header are both part of the picture.
#
# Every pause here waits for something to appear on screen rather than for a
# number of seconds. A fixed sleep is a guess about how fast the machine is,
# and when the guess is short the keystrokes land in the shell instead of the
# menu and draw themselves as ^[[B across the top of the film. Waiting on the
# screen also means this tape does not need re-timing on faster hardware.
#
# The demo steps a value forward and then back again, so it ends on the setting
# it started on and leaves patch-settings.conf untouched. Keep it that way —
# a tape that edits your settings as a side effect cannot be re-run safely.
#
# It does run Apply for real, which rewrites the installed binary. Because the
# settings are back where they started, the run reproduces the state you were
# already in. Apply begins from the frozen baseline, verifies the result, and
# rolls back on its own if the patched build does not start.
#
# Row numbers are counted from Themes, where the menu opens. Navigation skips
# the divider, so the divider costs no keystroke, and `esc` returns to the row
# you came from — both verified against the running menu, not assumed:
#
#   0 Themes                 5 Misc                  10 AGENTS.md Alt Names   15 Transcript Window
#   1 Thinking Verbs         6 Toolsets              11 Skill Setup           16 Patches
#   2 Thinking Style         7 Subagent Models       12 Hook Setup            17 Cost Report
#   3 Working Style          8 Complexity Router     13 Loop Control          18 View System Prompts
#   4 User Message Display   9 Tool Setup            14 Reasoning             19 Apply

Output assets/demo.gif

Set Shell "zsh"
Set FontSize 14
Set Width 1400
Set Height 900
Set Padding 24
Set TypingSpeed 60ms
Set LoopOffset 20%

# Start on a clean screen, without recording the shell noise that gets there.
# VHS runs a login-less shell, so ~/.local/bin — where the installer links the
# launcher — is not on PATH yet. Put it there off-camera, so the visible
# command stays the one the README tells people to type.
Hide
Type "export PATH=$HOME/.local/bin:$PATH" Enter
Type "clear" Enter
Sleep 500ms
Show

Type "kimi-code-mods"
Sleep 600ms
Enter

# The menu takes a few seconds to come up. Wait for the last row of the list,
# which means the whole thing is drawn and the terminal is in raw mode — not
# for a guessed number of seconds.
Wait+Screen@60s /View System Prompts/
Sleep 1.5s

# Thinking Style — the row that explains itself, with the preview running.
Down@350ms 2
Sleep 800ms
Enter
Wait+Screen@30s /Reverse-Mirror Run/
Sleep 1s
Right@700ms 3
Sleep 1.2s
Left@400ms 3
Sleep 600ms
Escape
Wait+Screen@30s /View System Prompts/
Sleep 800ms

# Transcript Window — the one lever that moves running cost. Its settings are
# launcher variables, so it opens the environment screen.
# 15 - 2 = 13 rows down from Thinking Style.
Down@350ms 13
Sleep 800ms
Enter
Wait+Screen@30s /Launcher Environment/
Sleep 1s
Right@700ms 2
Sleep 1.2s
Left@400ms 2
Sleep 600ms
Escape
Wait+Screen@30s /View System Prompts/
Sleep 1s

# Apply — 19 - 15 = 4 rows down from Transcript Window.
Down@250ms 4
Sleep 800ms
Enter

# A full run takes around a minute, which is longer than the GIF should be, so
# drop out of the recording while it works and come back when the summary is
# on screen. The menu holds that summary for five seconds before redrawing
# itself, and those eight lines are the claim the whole README rests on — they
# are what the film is for.
Hide
Wait+Screen@300s /Apply summary/
Show
Sleep 6s

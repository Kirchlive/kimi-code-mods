#!/usr/bin/env bash
# Draws the patched Kimi welcome box, for screenshotting into the README.
#
#   ./docs/banner.sh          # 84 columns, sized for a GitHub README
#   ./docs/banner.sh 120      # wider, if you are cropping it yourself
#
# This is a still life, not a live reading: the model and version shown are
# placeholders picked for the picture, and nothing here asks Kimi anything. It
# exists so the banner in the README can be reproduced exactly rather than
# depending on someone's terminal, working directory and installed version.
#
# WHY THE WIDTHS ARE WRITTEN DOWN
# The logo rows contain quadrant blocks and triangles that `${#string}` counts
# as one character each but which are not ASCII, and the shell has no notion of
# display width. Each row therefore carries the number of columns it occupies,
# measured once, so the padding is arithmetic rather than a guess. Change a
# line and its number changes with it.
set -euo pipefail

# Inner width, between the two verticals. The default is chosen for where this
# ends up: GitHub renders a README body about 90 monospace columns wide before
# a line is cut off, so 84 inside the frame leaves the box a little air on both
# sides rather than touching the edges.
#
# Screenshot it in a terminal about this wide too. A 130-column window around
# an 87-column box puts the empty half of the terminal into the picture, and
# the whole image then scales down to fit — which shrinks the text along with
# the background nobody wanted.
W=${1:-84}

# The project red, the one the menu and the banner share. Falls back to no
# colour when the output is not a terminal, so piping this to a file gives
# plain text rather than escape sequences.
if [ -t 1 ]; then
  R=$'\033[38;2;234;66;66m'; B=$'\033[1m'; N=$'\033[0m'
else
  R=''; B=''; N=''
fi

LOGO_TOP='◢       ◣'            # 9 columns
LOGO_MID='◥██▛█▛██◤'            # 9
LOGO_BOT=' ▐█████▌ '            # 9

rule() {                         # rule <left> <right>
  local line='' i
  for ((i = 0; i < W; i++)); do line+='─'; done
  printf ' %s%s%s%s%s\n' "$R" "$1" "$line" "$2" "$N"
}

row() {                          # row <visible-columns> <text…>
  local vis=$1; shift
  printf ' %s│%s%s%*s%s│%s\n' "$R" "$N" "$*" $((W - vis)) '' "$R" "$N"
}

label() {                        # label <name> <value> — 11-column label column
  printf '  %-11s%s' "$1" "$2"
}

echo
rule '╭' '╮'
row 0 ''
row 11 "  ${R}${LOGO_TOP}${N}"
row 39 "  ${R}${LOGO_MID}${N}  ${B}${R}Welcome to Kimi Code Mods!${N}"
row 45 "  ${R}${LOGO_BOT}${N}  Send /help for help information."
row 0 ''
row 19 "$(label 'Directory:' '/Users')"
row 13 "$(label 'Session:' '')"
row 15 "$(label 'Model:' 'KX')"
row 19 "$(label 'Version:' '1.00.0')"
row 0 ''
rule '╰' '╯'
echo

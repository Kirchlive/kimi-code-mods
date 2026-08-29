#!/usr/bin/env bash
# Draws the patched Kimi welcome box, for screenshotting into the README.
#
#   ./assets/banner.sh                # 84 columns, sized for a GitHub README
#   ./assets/banner.sh 120            # wider, if you are cropping it yourself
#   ./assets/banner.sh 84 1.40.0      # a different version in the picture
#   ./assets/banner.sh --png          # render assets/banner.png and stop
#   ./assets/banner.sh --png out.png 84 1.40.0
#
# This is a still life, not a live reading: the model and version shown are
# placeholders picked for the picture, and nothing here asks Kimi anything. It
# exists so the banner in the README can be reproduced exactly rather than
# depending on someone's terminal, working directory and installed version.
#
# It sits beside `banner.jpeg` because that file is what it produces.
#
# WHY THE PICTURE COMES FROM VHS
# `--png` needs `vhs` (brew install vhs, which brings ttyd and ffmpeg) — the
# same tool assets/demo.tape already uses for the README film. It runs this
# script inside a real terminal and photographs the result, so the picture is
# drawn by a terminal emulator rather than by a font renderer that would have
# to guess at the quadrant blocks. Nothing else here needs vhs; without the
# flag the script is plain text on stdout.
#
# WHY THE WIDTHS ARE WRITTEN DOWN
# The logo rows contain quadrant blocks and triangles that `${#string}` counts
# as one character each but which are not ASCII, and the shell has no notion of
# display width. Each row therefore carries the number of columns it occupies,
# measured once, so the padding is arithmetic rather than a guess. Change a
# line and its number changes with it. The version row is the exception: it is
# all ASCII, so it counts itself and any version string stays aligned.
set -euo pipefail

# `--png [file]` renders instead of printing. Parsed before the positional
# arguments so the width and the version keep their places after it.
PNG=''
if [ "${1:-}" = '--png' ]; then
  shift
  case ${1:-} in
    *.png) PNG=$1; shift ;;
    *) PNG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/banner.png" ;;
  esac
fi

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

# The release the picture claims to be. A tag rather than a reading: nothing
# here can ask the installed binary, and the banner is a still life. Keep it in
# step with the newest `v*` tag.
V=${2:-1.39.1}

# ------------------------------------------------------------------ picture
#
# The canvas is derived rather than typed in, because VHS has no "size to fit
# the content": it renders into whatever pixel box the tape names, and a box
# one column too narrow wraps the frame — the one failure mode that looks like
# a broken drawing instead of a bad size. So the cell is measured once and the
# rest is arithmetic. At font size 22 a cell is 14.0 px wide and 25.5 px tall,
# both read off a render of this very banner; the percentages below are those
# two numbers as a fraction of the font size, so changing `fs` alone stays
# correct. The box is `W + 3` columns — the leading space and the two
# verticals — and the drawing is 14 lines tall, blank line to blank line, plus
# the line the cursor rests on afterwards: leave that fifteenth line out and
# the terminal scrolls, which crops the top border away. One font-size of
# slack on the width absorbs the rounding.
render_png() {
  command -v vhs >/dev/null 2>&1 || {
    echo 'banner.sh: --png needs vhs — brew install vhs' >&2
    exit 1
  }
  local self pad=24 fs=22 lines=15 cols width height dir
  self=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")
  cols=$((W + 3))
  width=$((pad * 2 + cols * fs * 64 / 100 + fs))
  height=$((pad * 2 + lines * fs * 118 / 100))
  dir=$(mktemp -d)

  # `clear` first so the typed command line is not in the picture, `tput civis`
  # so the block cursor is not either, and a `sleep` at the end so the shell
  # prompt never comes back before the shutter. Hide/Show keeps the typing out
  # of the recording; VHS still wants a film, so it gets a throwaway one.
  cat > "$dir/banner.tape" <<TAPE
Output "$dir/banner.gif"
Set Shell "bash"
Set FontSize $fs
Set Width $width
Set Height $height
Set Padding $pad
Hide
Type "clear; bash '$self' $W '$V'; tput civis; sleep 30"
Enter
Sleep 3s
Show
Sleep 1s
Screenshot "$PNG"
TAPE

  vhs "$dir/banner.tape" >/dev/null
  rm -rf "$dir"
  echo "banner.sh: wrote $PNG (${width}x${height})"
}

if [ -n "$PNG" ]; then
  render_png
  exit 0
fi

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
row $((13 + ${#V})) "$(label 'Version:' "$V")"
row 0 ''
rule '╰' '╯'
echo

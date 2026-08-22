#!/usr/bin/env bash
# One-line installer for kimi-code-mods.
#
#   curl -fsSL https://raw.githubusercontent.com/Kirchlive/kimi-code-mods/main/install.sh | bash
#
# What it does, in order: check what is needed, fetch the repository into
# ~/.kimi-code-mods, and put a `kimi-code-mods` command on PATH. It writes
# nothing else and touches no Kimi installation — patching happens later, when
# you pick Apply in the menu, and never as a side effect of installing.
#
# WHY IT CHECKS THE PLATFORM
# The menu is Python and runs anywhere. The patcher does not: it reads the
# Mach-O header of Kimi's binary to find the payload and re-signs with
# `codesign` afterwards, both of which are macOS. On Linux or WSL you can
# install this and open the menu, but Apply will refuse — so the installer
# says that up front rather than leaving it to be discovered.
#
# Set KIMICODEMODS_REPO to install from a fork, or KIMICODEMODS_SRC to copy
# from a local checkout instead of downloading.
set -euo pipefail

REPO="${KIMICODEMODS_REPO:-Kirchlive/kimi-code-mods}"
BRANCH="${KIMICODEMODS_BRANCH:-main}"
DEST="${KIMICODEMODS_DEST:-$HOME/.kimi-code-mods}"
BINDIR="${KIMICODEMODS_BINDIR:-$HOME/.local/bin}"
SRC="${KIMICODEMODS_SRC:-}"

RED=''; DIM=''; OFF=''
if [ -t 1 ]; then RED=$'\033[38;2;234;66;66m'; DIM=$'\033[2m'; OFF=$'\033[0m'; fi

say()  { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$RED" "$OFF" "$*"; }
warn() { printf '%s!%s   %s\n' "$RED" "$OFF" "$*" >&2; }
die()  { printf '%sx%s   %s\n' "$RED" "$OFF" "$*" >&2; exit 1; }

# --- what we are on ---------------------------------------------------------
OS="$(uname -s 2>/dev/null || echo unknown)"
case "$OS" in
  Darwin) PATCHABLE=yes ;;
  Linux)
    PATCHABLE=no
    if grep -qi microsoft /proc/version 2>/dev/null; then WHERE='WSL'; else WHERE='Linux'; fi
    ;;
  *) die "unsupported system: $OS. macOS patches; Linux and WSL run the menu only." ;;
esac

# --- what we need -----------------------------------------------------------
for tool in python3 git; do
  command -v "$tool" >/dev/null || die "$tool is required but not on PATH."
done
command -v node >/dev/null || warn "node is not on PATH — the menu works, Apply needs it."
if [ "$PATCHABLE" = yes ]; then
  command -v codesign >/dev/null \
    || die "codesign not found. It ships with the Xcode command line tools: xcode-select --install"
fi

# --- fetch ------------------------------------------------------------------
if [ -n "$SRC" ]; then
  step "copying from $SRC"
  [ -d "$SRC" ] || die "KIMICODEMODS_SRC is not a directory: $SRC"
  mkdir -p "$DEST"
  # -a keeps modes, so kimi-patch.sh stays executable. The trailing dot copies
  # the contents rather than nesting the directory inside itself.
  cp -a "$SRC/." "$DEST/"
elif [ -d "$DEST/.git" ]; then
  step "updating $DEST"
  git -C "$DEST" pull --ff-only --quiet \
    || die "could not fast-forward $DEST — it has local changes. Move it aside and re-run."
else
  step "fetching $REPO into $DEST"
  [ -e "$DEST" ] && [ ! -d "$DEST/.git" ] \
    && die "$DEST exists and is not a git checkout. Move it aside and re-run."
  git clone --quiet --depth 1 --branch "$BRANCH" "https://github.com/$REPO.git" "$DEST"
fi

[ -f "$DEST/kimi-code-mods.sh" ] || die "$DEST does not look like kimi-code-mods."
chmod +x "$DEST/kimi-code-mods.sh" "$DEST/kimi-patch.sh" 2>/dev/null || true

# --- put it on PATH ---------------------------------------------------------
# A symlink rather than a copy: `git pull` in the checkout is then the whole of
# updating, and the command cannot drift from the code it points at.
step "linking $BINDIR/kimi-code-mods"
mkdir -p "$BINDIR"
ln -sf "$DEST/kimi-code-mods.sh" "$BINDIR/kimi-code-mods"

say ''
step "installed"
say "   ${DIM}menu${OFF}      kimi-code-mods"
say "   ${DIM}checkout${OFF}  $DEST"
case ":$PATH:" in
  *":$BINDIR:"*) ;;
  *) warn "$BINDIR is not on your PATH — add it, or run $DEST/kimi-code-mods.sh directly." ;;
esac
if [ "$PATCHABLE" = no ]; then
  say ''
  warn "on $WHERE the menu runs but Apply does not: patching reads a Mach-O"
  warn "binary and re-signs it with codesign, which are macOS only."
fi
say ''

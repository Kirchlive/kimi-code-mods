#!/usr/bin/env bash
# kimi-code-mods — the top-level menu.
#
# A thin door to lib/main-menu.py, which reads its state from the same files
# everything else here writes: config.toml, env-profile.conf, patches/,
# system-prompts/ and state.json. Nothing is cached, so the menu cannot drift
# from reality.
#
# For scripting, the individual commands remain the interface:
#   ./kimi-patch.sh --status | --cost | --tools | --config-menu | --env | --migrate
set -euo pipefail

# Resolved through symlinks, because the installer puts one on PATH: without
# this, `HERE` would be the directory the link sits in and `lib/` would be
# looked for next to the link rather than next to the code. Walked in a loop
# rather than with `realpath`, which is not on every macOS by default.
SELF="${BASH_SOURCE[0]}"
while [ -L "$SELF" ]; do
  LINK="$(readlink "$SELF")"
  case "$LINK" in
    /*) SELF="$LINK" ;;
    *)  SELF="$(dirname "$SELF")/$LINK" ;;
  esac
done
HERE="$(cd "$(dirname "$SELF")" && pwd)"
exec python3 "$HERE/lib/main-menu.py" "$@"

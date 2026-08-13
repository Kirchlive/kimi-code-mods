#!/usr/bin/env bash
# tweakkimi — the top-level menu.
#
# A thin door to lib/main-menu.py, which reads its state from the same files
# everything else here writes: config.toml, env-profile.conf, patches/,
# system-prompts/ and state.json. Nothing is cached, so the menu cannot drift
# from reality.
#
# For scripting, the individual commands remain the interface:
#   ./kimi-patch.sh --status | --cost | --tools | --config-menu | --env | --migrate
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/lib/main-menu.py" "$@"

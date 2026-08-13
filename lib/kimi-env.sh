#!/usr/bin/env bash
# Read and edit the launcher's environment profile.
#
# The profile is a plain file and editing it by hand is perfectly fine. This
# exists for the cases where that is tedious: seeing at a glance which settings
# deviate from Kimi's defaults, and flipping one without hunting for the right
# comment line. Edits preserve the file's comments and ordering — a commented
# default is uncommented in place rather than appended at the bottom.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${TWEAKKIMI_PROFILE:-$HERE/env-profile.conf}"
LAUNCHER="$HERE/bin/kimi"

# Kimi's own defaults, so `show` can mark what actually deviates. Read from the
# bundle's readEnvInt call sites; empty means "unset is the default".
default_for() {
  case "$1" in
    KIMI_CODE_TUI_MAX_TURNS) echo 15 ;;
    KIMI_CODE_TUI_EXPAND_TURNS) echo 3 ;;
    KIMI_CODE_TUI_HYSTERESIS) echo 5 ;;
    KIMI_CODE_TUI_KEEP_RECENT_STEPS) echo 30 ;;
    KIMI_CODE_TUI_KEEP_RECENT_ASSISTANT) echo 20 ;;
    KIMI_CODE_TUI_KEEP_RECENT_ASSISTANT_COMPLETED) echo 2 ;;
    *) echo "" ;;
  esac
}

known_vars() {
  # Single source of truth: the allow-list inside the launcher.
  sed -n '/^KNOWN_VARS="$/,/^"$/p' "$LAUNCHER" | sed '1d;$d' | grep -v '^$'
}

is_known() { known_vars | grep -qx "$1"; }

active_lines() {
  [ -f "$PROFILE" ] || return 0
  grep -vE '^[[:space:]]*(#|$)' "$PROFILE" || true
}

usage() {
  cat <<EOF
usage: $(basename "$0") <command>

  show              settings in effect, and how they differ from Kimi's defaults
  list              every variable the launcher accepts
  set NAME VALUE    set or change one setting
  unset NAME        comment a setting out again
  path              print the profile path

profile: $PROFILE
EOF
}

cmd_show() {
  echo "profile: $PROFILE"
  local any=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    any=1
    local name="${line%%=*}" value="${line#*=}" def
    def="$(default_for "$name")"
    if [ -n "$def" ] && [ "$def" = "$value" ]; then
      printf '  %-46s %-10s (same as default)\n' "$name" "$value"
    elif [ -n "$def" ]; then
      printf '  %-46s %-10s (default %s)\n' "$name" "$value" "$def"
    else
      printf '  %-46s %s\n' "$name" "$value"
    fi
  done < <(active_lines)
  [ "$any" = 1 ] || echo "  (nothing set — Kimi runs with its own defaults)"
}

cmd_list() {
  echo "accepted by the launcher (everything else aborts the launch):"
  local def
  while IFS= read -r v; do
    def="$(default_for "$v")"
    printf '  %-46s %s\n' "$v" "${def:+default $def}"
  done < <(known_vars)
}

cmd_set() {
  local name="${1:-}" value="${2:-}"
  [ -n "$name" ] && [ $# -ge 2 ] || { echo "usage: $(basename "$0") set NAME VALUE" >&2; exit 2; }
  is_known "$name" || {
    echo "error: '$name' is not read by Kimi 0.36.0 — setting it would do nothing." >&2
    echo "       Run '$(basename "$0") list' to see what is accepted." >&2
    exit 1
  }
  touch "$PROFILE"
  local tmp="$PROFILE.tmp.$$"
  if grep -qE "^[[:space:]]*#?[[:space:]]*${name}=" "$PROFILE"; then
    # Rewrite in place, keeping the line where the user expects to find it.
    awk -v n="$name" -v v="$value" '
      $0 ~ "^[[:space:]]*#?[[:space:]]*" n "=" && !done { print n "=" v; done=1; next }
      { print }
    ' "$PROFILE" > "$tmp"
  else
    cp "$PROFILE" "$tmp"
    printf '%s=%s\n' "$name" "$value" >> "$tmp"
  fi
  mv -f "$tmp" "$PROFILE"
  echo "$name=$value"
}

cmd_unset() {
  local name="${1:-}"
  [ -n "$name" ] || { echo "usage: $(basename "$0") unset NAME" >&2; exit 2; }
  [ -f "$PROFILE" ] || { echo "nothing to unset"; return; }
  local tmp="$PROFILE.tmp.$$"
  awk -v n="$name" '
    $0 ~ "^[[:space:]]*" n "=" { print "# " $0; next }
    { print }
  ' "$PROFILE" > "$tmp"
  mv -f "$tmp" "$PROFILE"
  echo "$name is back to Kimi's default"
}

case "${1:-}" in
  show) cmd_show ;;
  list) cmd_list ;;
  set) shift; cmd_set "$@" ;;
  unset) shift; cmd_unset "$@" ;;
  path) echo "$PROFILE" ;;
  -h|--help|'') usage ;;
  *) usage >&2; exit 2 ;;
esac

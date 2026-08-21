#!/usr/bin/env bash
# kimi-code-mods guard — notice when Kimi has replaced its own binary, and put the
# patches back.
#
# Kimi updates itself in place: it moves the running binary aside to kimi.bak
# and writes a fresh one. Everything kimi-code-mods did is gone at that moment, and
# nothing says so — the CLI still starts, it is just stock again. That happened
# within an hour of the first patch run, so it is the normal case, not an edge
# one. KIMI_CLI_NO_AUTO_UPDATE=1 avoids it by never updating at all, which is a
# poor trade for a tool that ships fixes weekly.
#
# Two things this deliberately does NOT do:
#
#   * It never repatches across a version change. A new release means a new
#     minified bundle, so every anchor has drifted and a fresh baseline is
#     needed. Patching blindly would produce a binary that is quietly less
#     patched than before — the worst outcome, because it looks like success.
#     That case is reported and left to a human.
#   * It never touches the binary while Kimi is running. Writing over a mapped
#     Mach-O image takes the running process down with it.
#
# Platform: macOS is the target (launchd + codesign). The check and repair
# paths are plain POSIX-ish bash and work on Linux; only the launchd agent and
# the desktop notification are macOS-specific. Windows is out of scope.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BIN="${KIMI_BIN:-$HOME/.kimi-code/bin/kimi}"
DATA="${KIMICODEMODS_DATA:-$ROOT}"
BASELINE_DIR="$DATA/baseline"
STATE="$DATA/state.json"
CACHE="$DATA/.work/guard-cache"
PATCHER="${KIMICODEMODS_PATCHER:-$ROOT/kimi-patch.sh}"

# Verdict codes. Deliberately above the range a shell command uses for its own
# failures, so a crashed guard is never mistaken for a diagnosis.
OK=0                # binary is our patch result — nothing to do
REPAIRABLE=10       # pristine, same version, baseline present — can repatch
VERSION_CHANGED=11  # new release — anchors drifted, needs a human
FOREIGN=12          # neither baseline nor our output — someone else edited it
UNCONFIGURED=13     # never patched this version, or no baseline yet
IN_FLUX=14          # unreadable right now, probably mid-update

VERDICT=''          # human-readable reason, set by classify()

usage() {
  cat <<EOF
usage: $(basename "$0") <check|repair|plist|help> [--quiet]

  check   report whether the binary is still patched and exit with the verdict
          code: $OK patched, $REPAIRABLE repairable, $VERSION_CHANGED version changed,
          $FOREIGN foreign, $UNCONFIGURED not set up, $IN_FLUX in flux
  repair  run the same check, then repatch when that is the right answer
  plist   print a launchd agent that runs 'repair' whenever Kimi rewrites its
          binary; see the README for the install command

env: KIMI_BIN         binary to watch (default \$HOME/.kimi-code/bin/kimi)
     KIMICODEMODS_DATA   state directory (default the kimi-code-mods checkout)
EOF
}

sha() { shasum -a 256 "$1" | cut -d' ' -f1; }

# Size and modification time, cheap enough to run on every shell prompt. macOS
# and GNU stat disagree on the flags, so try both.
file_id() {
  stat -f '%z %m' "$1" 2>/dev/null || stat -c '%s %Y' "$1" 2>/dev/null || true
}

state_get() {  # state_get <version> <field>
  [ -f "$STATE" ] || { echo ''; return; }
  python3 -c '
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
print(d.get(sys.argv[2],{}).get(sys.argv[3],""))' "$STATE" "$1" "$2" 2>/dev/null || echo ''
}

state_has_any_version() {
  [ -f "$STATE" ] || return 1
  python3 -c '
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
sys.exit(0 if d else 1)' "$STATE" 2>/dev/null
}

# Is a Kimi process using this binary right now? Anchored so the guard and the
# patcher, whose own command lines mention neither, cannot match themselves.
kimi_running() {
  [ "${KIMICODEMODS_GUARD_ASSUME_RUNNING:-0}" = 1 ] && return 0
  pgrep -f "^${BIN}( |$)" >/dev/null 2>&1
}

notify() {  # best effort; never a reason to fail
  [ "${KIMICODEMODS_GUARD_QUIET:-0}" = 1 ] && return 0
  command -v osascript >/dev/null 2>&1 || return 0
  osascript -e "display notification \"$1\" with title \"kimi-code-mods\"" >/dev/null 2>&1 || true
}

# --------------------------------------------------------------------- verdict
# State is read from content hashes, never from the code signature. A restored
# binary is pristine in content while still carrying whatever signature it was
# last given, and `codesign -dv` answers from a per-inode cache that lags a
# file replacement — so the signature is the one thing here that lies.
classify() {
  local ver sha_now patched baseline base_sha

  if [ ! -x "$BIN" ]; then
    VERDICT="no executable binary at $BIN"
    return $UNCONFIGURED
  fi

  # A half-written binary answers nothing useful. Treat that as "ask again"
  # rather than as a diagnosis, or the guard would record a bogus verdict for
  # the update it is supposed to be repairing.
  ver="$("$BIN" --version 2>/dev/null | head -1 | tr -d '[:space:]')" || ver=''
  if [ -z "$ver" ]; then
    VERDICT='binary reports no version — still being written?'
    return $IN_FLUX
  fi

  sha_now="$(sha "$BIN")"
  patched="$(state_get "$ver" patched_sha256)"
  baseline="$BASELINE_DIR/kimi-$ver"

  if [ -n "$patched" ] && [ "$sha_now" = "$patched" ]; then
    VERDICT="patched ($ver)"
    return $OK
  fi

  if [ ! -f "$baseline" ]; then
    if state_has_any_version; then
      VERDICT="Kimi is now $ver and there is no baseline for it"
      return $VERSION_CHANGED
    fi
    VERDICT="no baseline for $ver yet"
    return $UNCONFIGURED
  fi

  base_sha="$(sha "$baseline")"
  if [ "$sha_now" = "$base_sha" ]; then
    if [ -n "$patched" ]; then
      VERDICT="pristine $ver — the patches are gone"
      return $REPAIRABLE
    fi
    VERDICT="pristine $ver — never patched"
    return $UNCONFIGURED
  fi

  VERDICT="unrecognised $ver binary — neither the baseline nor our patch result"
  return $FOREIGN
}

# Hashing 180 MB on every shell prompt would be absurd, so the verdict is
# cached against the binary's size and mtime. Any rewrite changes both, which
# is exactly the event this guard exists for — so the cache can never hide an
# update, only skip the work when nothing happened.
cached_verdict() {
  local id code cached_id cached_code cached_text
  id="$(file_id "$BIN")"
  if [ -n "$id" ] && [ -f "$CACHE" ]; then
    IFS='|' read -r cached_id cached_code cached_text < "$CACHE" || true
    if [ "$id" = "${cached_id:-}" ] && [ -n "${cached_code:-}" ]; then
      VERDICT="${cached_text:-}"
      return "$cached_code"
    fi
  fi

  # `code=0; cmd || code=$?` rather than toggling errexit: a nested set -e
  # would re-enable it for the caller too, and a non-zero verdict returned into
  # an errexit context kills the script before it can act on the diagnosis.
  code=0
  classify || code=$?
  mkdir -p "$(dirname "$CACHE")"
  printf '%s|%s|%s\n' "$id" "$code" "$VERDICT" > "$CACHE"
  return "$code"
}

# An installer writing 180 MB takes a moment, and launchd fires on the first
# byte. Wait for the file to hold still before judging it.
settle() {
  local interval="${KIMICODEMODS_GUARD_SETTLE:-2}" prev='' cur i
  [ "$interval" = 0 ] && return 0
  for i in 1 2 3 4 5; do
    cur="$(file_id "$BIN")"
    [ -n "$cur" ] && [ "$cur" = "$prev" ] && return 0
    prev="$cur"
    sleep "$interval"
  done
  return 0
}

# ---------------------------------------------------------------------- actions
do_check() {
  local code=0
  cached_verdict || code=$?
  [ "${QUIET:-0}" = 1 ] || echo "$VERDICT"
  return "$code"
}

do_repair() {
  local code=0
  settle
  rm -f "$CACHE"            # the file just changed; do not trust a stale verdict
  cached_verdict || code=$?

  case "$code" in
    "$OK")
      [ "${QUIET:-0}" = 1 ] || echo "$VERDICT — nothing to do"
      return 0 ;;
    "$REPAIRABLE")
      if kimi_running; then
        echo "guard: $VERDICT, but Kimi is running — not replacing a mapped binary." >&2
        echo "       Quit Kimi and run: $PATCHER" >&2
        notify "Patches lost. Quit Kimi and re-run kimi-patch.sh."
        return 1
      fi
      echo "guard: $VERDICT — repatching."
      if "$PATCHER"; then
        rm -f "$CACHE"      # the patcher changed the file again
        notify "Kimi was updated; patches reapplied."
        return 0
      fi
      echo "guard: repatching failed — Kimi is running unpatched." >&2
      notify "Repatching failed. See the guard log."
      return 1 ;;
    "$VERSION_CHANGED")
      cat >&2 <<EOF
guard: $VERDICT.

A new release means a new minified bundle: prompt overrides will report drift
and free-form patches may no longer find their anchors. Repatching now would
produce a binary that is quietly less patched than before, so nothing was
touched. Review it by hand:

  $PATCHER --status
  $PATCHER --extract-prompts     # writes system-prompts.<version>.new/
  $PATCHER
EOF
      notify "Kimi updated to a new version. Patches need review."
      return 1 ;;
    "$FOREIGN")
      echo "guard: $VERDICT — leaving it alone." >&2
      return 1 ;;
    "$IN_FLUX")
      echo "guard: $VERDICT — will judge it on the next change." >&2
      rm -f "$CACHE"
      return 0 ;;
    *)
      [ "${QUIET:-0}" = 1 ] || echo "guard: $VERDICT — nothing to do"
      return 0 ;;
  esac
}

do_plist() {
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.kimi-code-mods.guard</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$HERE/kimi-guard.sh</string>
    <string>repair</string>
  </array>
  <key>WatchPaths</key>
  <array>
    <string>$BIN</string>
  </array>
  <!-- Our own repatch rewrites the watched file and fires this again; the
       second run sees a patched binary and exits without doing anything, so
       the loop terminates on its own. The throttle keeps it cheap anyway. -->
  <key>ThrottleInterval</key>
  <integer>120</integer>
  <key>StandardOutPath</key>
  <string>$DATA/.work/guard.log</string>
  <key>StandardErrorPath</key>
  <string>$DATA/.work/guard.log</string>
</dict>
</plist>
EOF
}

# ------------------------------------------------------------------------- main
CMD="${1:-help}"
shift || true
QUIET=0
for arg in "$@"; do
  case "$arg" in
    --quiet) QUIET=1 ;;
    *) usage >&2; exit 2 ;;
  esac
done

case "$CMD" in
  check)  do_check ;;
  repair) do_repair ;;
  plist)  do_plist ;;
  help|-h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac

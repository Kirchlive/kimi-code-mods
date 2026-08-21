#!/usr/bin/env bash
# Tests for the launcher wrapper. Sandboxed: a stub stands in for the Kimi
# binary, so nothing touches ~/.kimi-code and no 180 MB is copied.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER="$HERE/bin/kimi"
ENVCMD="$HERE/lib/kimi-env.sh"
PASS=0; FAIL=0
SB="$(mktemp -d)"
trap 'rm -rf "$SB"' EXIT

ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1${2:+  — $2}"; }
check() { if [ "$1" = 0 ]; then ok "$2"; else bad "$2" "${3:-}"; fi; }

# macOS ships no coreutils `timeout`, and the loop tests are exactly the ones
# that must not hang the suite. Run the command in the background, poll, and
# kill the whole process group if it overstays.
with_timeout() {  # with_timeout <seconds> <command…>
  local secs="$1"; shift
  local out rc pid waited=0
  out="$(mktemp)"
  ( "$@" >"$out" 2>&1 ) &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$((secs * 10))" ]; then
      kill -9 -"$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      cat "$out"; rm -f "$out"
      return 124
    fi
    sleep 0.1
    waited=$((waited + 1))
  done
  wait "$pid"; rc=$?
  cat "$out"; rm -f "$out"
  return "$rc"
}

# A stub that reports the environment it was given, plus its arguments.
cat > "$SB/stub" <<'STUB'
#!/bin/sh
echo "ARGS:$*"
env | grep '^KIMI' | sort | sed 's/^/ENV:/'
[ "$1" = "--fail" ] && exit 42
exit 0
STUB
chmod +x "$SB/stub"

run() {  # run <profile> [args…]
  KIMICODEMODS_PROFILE="$1" KIMICODEMODS_REAL_BIN="$SB/stub" \
    KIMICODEMODS_LAUNCHED= "$LAUNCHER" "${@:2}" 2>&1
}

echo 'launcher:'

: > "$SB/empty.conf"
out="$(run "$SB/empty.conf")"
# The launcher's own KIMICODEMODS_* markers travel with every run and are
# not exports from the profile, so they are excluded rather than counted.
# Before the rename they fell outside a plain `^ENV:KIMI` match by accident;
# now they have to be named.
[ "$(grep '^ENV:KIMI' <<<"$out" | grep -vc '^ENV:KIMICODEMODS_')" -eq 0 ]
check $? 'an empty profile exports nothing' \
  "$(grep '^ENV:' <<<"$out" | grep -v '^ENV:KIMICODEMODS_' | head -2 | tr '\n' ' ')"

cat > "$SB/full.conf" <<'EOF'
# a comment
KIMI_CODE_TUI_FULL_SCREEN=1

  KIMI_CODE_TUI_MAX_TURNS = 4    # trailing comment
KIMI_CODE_NO_AUTO_UPDATE="yes"
EOF
out="$(run "$SB/full.conf")"
grep -q '^ENV:KIMI_CODE_TUI_FULL_SCREEN=1$' <<<"$out"
check $? 'a plain value arrives' "$(grep FULL_SCREEN <<<"$out")"
grep -q '^ENV:KIMI_CODE_TUI_MAX_TURNS=4$' <<<"$out"
check $? 'whitespace and trailing comments are stripped' "$(grep MAX_TURNS <<<"$out")"
grep -q '^ENV:KIMI_CODE_NO_AUTO_UPDATE=yes$' <<<"$out"
check $? 'surrounding quotes are removed' "$(grep AUTO_UPDATE <<<"$out")"

out="$(run "$SB/full.conf" -p 'hello world' --output-format text)"
grep -q '^ARGS:-p hello world --output-format text$' <<<"$out"
check $? 'arguments are passed through verbatim' "$(grep '^ARGS' <<<"$out")"

run "$SB/full.conf" --fail >/dev/null 2>&1
[ $? -eq 42 ]
check $? 'the exit code is the real binary'"'"'s'

printf 'x\n' | run "$SB/full.conf" >/dev/null 2>&1
check $? 'a pipe on stdin does not break the launch'

# Unknown names must abort rather than be quietly ignored: the whole point is
# not to promise an effect Kimi does not implement.
echo 'KIMI_CODE_AGENT_SWARM_MAX_CONCURRENCY=4' > "$SB/dead.conf"
out="$(run "$SB/dead.conf")"; rc=$?
[ $rc -ne 0 ] && grep -q 'would do nothing' <<<"$out"
check $? 'a variable Kimi never reads aborts the launch' "rc=$rc"

echo 'this is not an assignment' > "$SB/junk.conf"
out="$(run "$SB/junk.conf")"; rc=$?
[ $rc -ne 0 ] && grep -q 'expected NAME=value' <<<"$out"
check $? 'a malformed line aborts with the line number' "rc=$rc"

echo
echo 'self-invocation:'

# Pointing the launcher at itself must fail fast, not fork-bomb.
out="$(KIMICODEMODS_PROFILE="$SB/empty.conf" KIMICODEMODS_REAL_BIN="$LAUNCHER" \
       KIMICODEMODS_LAUNCHED= with_timeout 10 "$LAUNCHER")"; rc=$?
[ $rc -ne 0 ] && [ $rc -ne 124 ] && grep -q 'loop forever' <<<"$out"
check $? 'a target resolving to the launcher is refused' "rc=$rc out=${out:0:60}"

# The realistic version: the wrapper sits earlier in PATH than the real binary.
mkdir -p "$SB/pathdir"
ln -sf "$LAUNCHER" "$SB/pathdir/kimi"
out="$(cd "$SB" && PATH="$SB/pathdir:$PATH" KIMICODEMODS_PROFILE="$SB/empty.conf" \
       KIMICODEMODS_REAL_BIN="$SB/stub" KIMICODEMODS_LAUNCHED= with_timeout 10 kimi)"; rc=$?
[ $rc -eq 0 ] && grep -q '^ARGS:' <<<"$out"
check $? 'shadowing the real binary in PATH still resolves correctly' "rc=$rc"

# A symlinked launcher must still find the profile next to the real script.
out="$(KIMICODEMODS_REAL_BIN="$SB/stub" KIMICODEMODS_LAUNCHED= with_timeout 10 "$SB/pathdir/kimi")"
[ $? -eq 0 ]
check $? 'invoking through a symlink works'

echo
echo 'env command:'

cp "$SB/empty.conf" "$SB/edit.conf"
KIMICODEMODS_PROFILE="$SB/edit.conf" "$ENVCMD" set KIMI_CODE_TUI_MAX_TURNS 6 >/dev/null 2>&1
grep -qx 'KIMI_CODE_TUI_MAX_TURNS=6' "$SB/edit.conf"
check $? 'set writes the value'

KIMICODEMODS_PROFILE="$SB/edit.conf" "$ENVCMD" set KIMI_CODE_TUI_MAX_TURNS 9 >/dev/null 2>&1
[ "$(grep -c '^KIMI_CODE_TUI_MAX_TURNS=' "$SB/edit.conf")" -eq 1 ] \
  && grep -qx 'KIMI_CODE_TUI_MAX_TURNS=9' "$SB/edit.conf"
check $? 'setting twice rewrites rather than duplicates'

KIMICODEMODS_PROFILE="$SB/edit.conf" "$ENVCMD" unset KIMI_CODE_TUI_MAX_TURNS >/dev/null 2>&1
! grep -qE '^KIMI_CODE_TUI_MAX_TURNS=' "$SB/edit.conf"
check $? 'unset comments the line out'

KIMICODEMODS_PROFILE="$SB/edit.conf" "$ENVCMD" set KIMI_NOT_REAL 1 >/dev/null 2>&1
[ $? -ne 0 ]
check $? 'set refuses a name Kimi does not read'

# A commented default should be uncommented in place, not appended.
printf '# KIMI_CODE_TUI_HYSTERESIS=5\n' > "$SB/tidy.conf"
KIMICODEMODS_PROFILE="$SB/tidy.conf" "$ENVCMD" set KIMI_CODE_TUI_HYSTERESIS 1 >/dev/null 2>&1
[ "$(wc -l < "$SB/tidy.conf" | tr -d ' ')" -eq 1 ] && grep -qx 'KIMI_CODE_TUI_HYSTERESIS=1' "$SB/tidy.conf"
check $? 'a commented default is replaced in place'

out="$(KIMICODEMODS_PROFILE="$SB/tidy.conf" "$ENVCMD" show 2>&1)"
grep -q 'default 5' <<<"$out"
check $? 'show marks how a value differs from the default'

echo
if [ "$FAIL" -eq 0 ]; then echo "$PASS passed, 0 failed."; else echo "$PASS passed, $FAIL FAILED."; exit 1; fi

#!/usr/bin/env bash
# Behaviour tests for the auto-repatch guard.
#
# Everything runs against a sandbox: TWEAKKIMI_DATA redirects the state
# directory, KIMI_BIN points at a shell stub that answers --version, and
# TWEAKKIMI_PATCHER replaces the real patcher with a marker script. No 180 MB
# copies, no signing, no touching the installed Kimi.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="$HERE/kimi-guard.sh"
PASS=0; FAIL=0
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

ok()   { PASS=$((PASS+1)); echo "  ok   $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL $1${2:+  — $2}"; }
check(){ if [ "$1" = 0 ]; then ok "$2"; else bad "$2" "${3:-}"; fi; }

stub() {  # stub <path> <version> [salt]
  printf '#!/bin/sh\n# %s\n[ "$1" = --version ] && echo %s\nexit 0\n' \
    "${3:-plain}" "$2" > "$1"
  chmod +x "$1"
}

sha_of() { shasum -a 256 "$1" | cut -d' ' -f1; }

# Build a sandbox in a named state. Returns the data dir on stdout.
scenario() {  # scenario <name> <state>
  local d="$SANDBOX/$1" state="$2"
  mkdir -p "$d/baseline" "$d/.work"
  case "$state" in
    patched)
      stub "$d/kimi" 0.36.0 patched
      stub "$d/baseline/kimi-0.36.0" 0.36.0 pristine
      printf '{"0.36.0":{"baseline_sha256":"%s","patched_sha256":"%s"}}' \
        "$(sha_of "$d/baseline/kimi-0.36.0")" "$(sha_of "$d/kimi")" > "$d/state.json" ;;
    reverted)
      # What an auto-update leaves behind: the binary is byte-identical to the
      # baseline again, while state.json still remembers a patch result.
      stub "$d/kimi" 0.36.0 pristine
      cp "$d/kimi" "$d/baseline/kimi-0.36.0"
      printf '{"0.36.0":{"baseline_sha256":"%s","patched_sha256":"%s"}}' \
        "$(sha_of "$d/kimi")" "0000000000000000000000000000000000000000000000000000000000000000" \
        > "$d/state.json" ;;
    upgraded)
      stub "$d/kimi" 0.37.0 pristine
      stub "$d/baseline/kimi-0.36.0" 0.36.0 pristine
      printf '{"0.36.0":{"baseline_sha256":"%s","patched_sha256":"%s"}}' \
        "$(sha_of "$d/baseline/kimi-0.36.0")" "deadbeef" > "$d/state.json" ;;
    foreign)
      stub "$d/kimi" 0.36.0 someone-else
      stub "$d/baseline/kimi-0.36.0" 0.36.0 pristine
      printf '{"0.36.0":{"baseline_sha256":"%s","patched_sha256":"%s"}}' \
        "$(sha_of "$d/baseline/kimi-0.36.0")" "deadbeef" > "$d/state.json" ;;
    fresh)
      stub "$d/kimi" 0.36.0 pristine ;;
  esac
  echo "$d"
}

# A patcher that only records that it was called.
fake_patcher() {  # fake_patcher <dir> <exitcode>
  local p="$1/fake-patcher.sh"
  printf '#!/bin/sh\ntouch "%s/PATCHER-RAN"\nexit %s\n' "$1" "$2" > "$p"
  chmod +x "$p"
  echo "$p"
}

run_guard() {  # run_guard <datadir> <cmd> [extra env assignments handled by caller]
  local d="$1" cmd="$2"; shift 2
  TWEAKKIMI_DATA="$d" KIMI_BIN="$d/kimi" TWEAKKIMI_GUARD_SETTLE=0 \
    TWEAKKIMI_GUARD_QUIET=1 TWEAKKIMI_PATCHER="$d/fake-patcher.sh" \
    "$@" bash "$GUARD" "$cmd" 2>&1
}

code_of() {  # code_of <datadir> <cmd> [env…]
  run_guard "$@" >/dev/null 2>&1
  echo $?
}

echo 'guard verdicts:'

D="$(scenario patched patched)"; fake_patcher "$D" 0 >/dev/null
[ "$(code_of "$D" check)" = 0 ]
check $? 'a patched binary reports OK (0)'

D="$(scenario reverted reverted)"; fake_patcher "$D" 0 >/dev/null
[ "$(code_of "$D" check)" = 10 ]
check $? 'an auto-update revert reports repairable (10)' "got $(code_of "$D" check)"

D="$(scenario upgraded upgraded)"; fake_patcher "$D" 0 >/dev/null
[ "$(code_of "$D" check)" = 11 ]
check $? 'a version change reports version-changed (11)' "got $(code_of "$D" check)"

D="$(scenario foreign foreign)"; fake_patcher "$D" 0 >/dev/null
[ "$(code_of "$D" check)" = 12 ]
check $? 'a third-party edit reports foreign (12)' "got $(code_of "$D" check)"

D="$(scenario fresh fresh)"; fake_patcher "$D" 0 >/dev/null
[ "$(code_of "$D" check)" = 13 ]
check $? 'an unconfigured install reports not-set-up (13)' "got $(code_of "$D" check)"

echo
echo 'guard repair:'

D="$(scenario r1 reverted)"; fake_patcher "$D" 0 >/dev/null
run_guard "$D" repair >/dev/null 2>&1
[ -f "$D/PATCHER-RAN" ]
check $? 'repair reruns the patcher after a revert'

D="$(scenario r2 upgraded)"; fake_patcher "$D" 0 >/dev/null
out="$(run_guard "$D" repair)"
[ ! -f "$D/PATCHER-RAN" ]
check $? 'repair refuses to patch across a version change'
grep -q 'less patched than before' <<<"$out"
check $? 'and says why, rather than failing silently'

D="$(scenario r3 patched)"; fake_patcher "$D" 0 >/dev/null
run_guard "$D" repair >/dev/null 2>&1
[ ! -f "$D/PATCHER-RAN" ]
check $? 'repair does nothing when the binary is already ours'

D="$(scenario r4 reverted)"; fake_patcher "$D" 0 >/dev/null
run_guard "$D" repair env TWEAKKIMI_GUARD_ASSUME_RUNNING=1 >/dev/null 2>&1
[ ! -f "$D/PATCHER-RAN" ]
check $? 'repair will not replace a binary while Kimi is running'

D="$(scenario r5 reverted)"; fake_patcher "$D" 1 >/dev/null
run_guard "$D" repair >/dev/null 2>&1
[ $? -ne 0 ]
check $? 'a failing patcher makes repair exit non-zero'

echo
echo 'guard plumbing:'

D="$(scenario c1 patched)"; fake_patcher "$D" 0 >/dev/null
run_guard "$D" check >/dev/null 2>&1
[ -f "$D/.work/guard-cache" ]
check $? 'the verdict is cached against size and mtime'

# The cache must never mask a rewrite: change the binary and the verdict has to
# change with it, without anyone clearing the cache by hand.
stub "$D/kimi" 0.36.0 rewritten-by-an-update
cp "$D/kimi" "$D/baseline/kimi-0.36.0"
[ "$(code_of "$D" check)" = 10 ]
check $? 'rewriting the binary invalidates the cached verdict' "got $(code_of "$D" check)"

! grep -nE 'codesign[^|]*\|[^|]*grep' "$GUARD" >/dev/null
check $? 'codesign output is not piped into grep (SIGPIPE trap)'

out="$(TWEAKKIMI_DATA="$SANDBOX/c1" KIMI_BIN="$SANDBOX/c1/kimi" bash "$GUARD" plist)"
grep -q '<key>WatchPaths</key>' <<<"$out" && grep -q 'kimi-guard.sh' <<<"$out"
check $? 'plist names the watched path and the guard'

bash -n "$GUARD"
check $? 'guard parses'

echo
if [ "$FAIL" -eq 0 ]; then
  echo "$PASS passed, 0 failed."
else
  echo "$PASS passed, $FAIL FAILED."
  exit 1
fi

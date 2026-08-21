#!/usr/bin/env bash
# The guard's whole reason for existing, exercised once end to end.
#
#   bash lib/test_guard_cycle.sh
#
# `test_guard.sh` covers the guard's decisions with stubs and takes seconds.
# This does the thing those decisions are about: patch a binary, let Kimi
# replace it the way an auto-update does, and check that the guard notices and
# puts the patches back. It needs a real Mach-O and two full patch runs, so it
# costs a couple of minutes and lives behind `./test.sh --full`.
#
# Everything happens in a sandbox: `KIMICODEMODS_DATA` and `KIMI_BIN` point at a
# temporary directory with its own copy of the baseline, so the installed Kimi
# is never touched. That is the same mechanism the rest of the suite uses, and
# the reason this can be run on a working machine without a second thought.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PASS=0; FAIL=0

ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1${2:+  — $2}"; }
chk() { if [ "$1" = 0 ]; then ok "$2"; else bad "$2" "${3:-}"; fi; }

BASELINE="$(ls "$ROOT"/baseline/kimi-* 2>/dev/null | head -1)"
if [ -z "$BASELINE" ] || [ ! -f "$BASELINE" ]; then
  echo "  skip — no frozen baseline in $ROOT/baseline"
  exit 0
fi

D="$(mktemp -d)"
trap 'rm -rf "$D"' EXIT
mkdir -p "$D/baseline" "$D/.work"
cp -R "$ROOT/patches" "$D/patches"
cp -R "$ROOT/system-prompts" "$D/system-prompts"
cp "$BASELINE" "$D/baseline/$(basename "$BASELINE")"
cp "$BASELINE" "$D/kimi"

# Two switches with markers that are easy to find afterwards, and that no
# pristine binary carries: the extended filename list, and the read tool with
# its line numbers removed.
printf 'agents_md_names = all\nread_line_numbers = off\n' > "$D/patch-settings.conf"

guard() { KIMICODEMODS_DATA="$D" KIMI_BIN="$D/kimi" bash "$HERE/kimi-guard.sh" "$@"; }
patch() { KIMICODEMODS_DATA="$D" KIMI_BIN="$D/kimi" "$ROOT/kimi-patch.sh" "$@"; }
has()   { LC_ALL=C grep -a -q -F -- "$1" "$D/kimi"; }

MARK_NAMES='"CLAUDE.md", "claude.md", "GEMINI.md"'
MARK_READ='line: renderedContent,'

echo 'guard cycle (real binary, sandboxed):'

patch >/dev/null 2>&1
chk $? 'the sandbox binary patches'
has "$MARK_NAMES" && has "$MARK_READ"
chk $? 'both markers are in the patched binary'
guard check >/dev/null 2>&1
chk $? 'the guard calls it patched'

# What Kimi does when it updates itself: the running binary is moved aside and
# a fresh one is written in its place. Same version, none of our edits.
mv "$D/kimi" "$D/kimi.bak"
cp "$BASELINE" "$D/kimi"
has "$MARK_READ"
[ $? -ne 0 ]
chk $? 'the replacement binary carries none of our edits'

out="$(guard check 2>&1)"; rc=$?
[ "$rc" = 10 ]
chk $? 'the guard reports the patches are gone' "rc=$rc: $out"
grep -q 'patches are gone' <<<"$out"
chk $? 'and says so in words' "$out"

guard repair >/dev/null 2>&1
chk $? 'repair runs'
has "$MARK_NAMES" && has "$MARK_READ"
chk $? 'both markers are back'
"$D/kimi" --version 2>/dev/null | grep -q .
chk $? 'the repaired binary still starts'
guard check >/dev/null 2>&1
chk $? 'the guard calls it patched again'

# The one case the guard must refuse. A new release means a new minified
# bundle, so the anchors have moved; repatching would produce a binary that is
# quietly less patched than before, which looks like success.
printf '#!/bin/sh\n[ "$1" = --version ] && echo 99.0.0\nexit 0\n' > "$D/kimi"
chmod +x "$D/kimi"
before="$(shasum -a 256 "$D/kimi" | cut -d' ' -f1)"

out="$(guard check 2>&1)"; rc=$?
[ "$rc" = 11 ]
chk $? 'a version change is its own verdict' "rc=$rc: $out"

# Matched on a phrase that sits on one line. The sentence this is really
# about — "so nothing was touched" — is wrapped across a line break in the
# guard's message, and grepping for it whole finds nothing while the guard is
# behaving perfectly. That is how this check first failed.
out="$(guard repair 2>&1)"
grep -q 'Repatching now would' <<<"$out"
chk $? 'repair refuses across a version change' "$out"
[ "$(shasum -a 256 "$D/kimi" | cut -d' ' -f1)" = "$before" ]
chk $? 'and leaves the binary exactly as it found it'

echo
if [ "$FAIL" -eq 0 ]; then
  echo "$PASS passed, 0 failed."
else
  echo "$PASS passed, $FAIL FAILED."
  exit 1
fi

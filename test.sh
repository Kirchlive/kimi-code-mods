#!/usr/bin/env bash
# Functional tests for kimi-code-mods.
#
#   ./test.sh          fast checks only — a few seconds, no 180 MB copies
#   ./test.sh --full   also exercises the real binary: Mach-O resize, signing,
#                      and one complete patch cycle
#
# Every case corresponds to a failure that actually occurred while building
# this, which is the only selection rule worth having.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REAL_BIN="${KIMI_BIN:-$HOME/.kimi-code/bin/kimi}"
PASS=0; FAIL=0
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

# What the suite must not touch. A self-check that writes a real settings file
# instead of its sandbox copy is invisible — it passes, and the change only
# shows up later as a setting nobody remembers making. Snapshotted before
# anything runs, so a file the user edited on purpose is not mistaken for one
# a test wrote.
WATCHED='patch-settings.conf toolsets.conf env-profile.conf'

# Kimi's own files are outside the repository, so git cannot speak for them —
# and they are the ones where a stray write matters most: a permission mode or
# a theme changed by a test is a change to how the tool behaves, made by
# nobody. Hashed instead, which needs no git and no assumptions about what
# they contain.
KIMI_FILES="$HOME/.kimi-code/config.toml $HOME/.kimi-code/tui.toml"
snapshot() {
  (cd "$HERE" && git status --porcelain -- $WATCHED 2>/dev/null)
  for f in $KIMI_FILES; do
    [ -f "$f" ] && shasum -a 256 "$f" 2>/dev/null
  done
  true
}
BEFORE="$(snapshot)"

ok()   { PASS=$((PASS+1)); echo "  ok   $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL $1${2:+  — $2}"; }
check(){ if [ "$1" = 0 ]; then ok "$2"; else bad "$2" "${3:-}"; fi; }

# A stand-in for the Kimi binary: enough for anything that only asks its
# version. Tests needing a real Mach-O are gated behind --full.
make_stub() {
  local p="$1"
  printf '#!/bin/sh\n[ "$1" = --version ] && echo 0.36.0\nexit 0\n' > "$p"
  chmod +x "$p"
}

sandbox_run() {  # sandbox_run <datadir> <binary> [args…]
  local data="$1" bin="$2"; shift 2
  KIMICODEMODS_DATA="$data" KIMI_BIN="$bin" "$HERE/kimi-patch.sh" "$@" 2>&1
}

echo 'unit checks:'
python3 "$HERE/lib/jsstr.py"  >/dev/null 2>&1; check $? 'jsstr codec selfcheck'
python3 "$HERE/lib/oscruft.py" >/dev/null 2>&1; check $? 'oscruft pattern selfcheck'

echo
python3 "$HERE/lib/test_overrides.py" | sed 's/^/  /' | grep -v '^  ok' || true
python3 "$HERE/lib/test_overrides.py" >/dev/null 2>&1
check $? 'prompt override behaviour suite'

echo
echo 'signature detection:'
# The SIGPIPE bug: `codesign … | grep -q` under pipefail returned false at
# random, because grep exits at the first match and codesign dies of SIGPIPE.
# Cheap to check statically; the behavioural version runs under --full, since
# each --status hashes 180 MB twice.
! grep -nE 'codesign[^|]*\|[^|]*grep' "$HERE/kimi-patch.sh" >/dev/null
check $? 'codesign output is not piped into grep (SIGPIPE trap)'

echo
echo 'baseline preflight:'
D="$SANDBOX/fresh"; mkdir -p "$D"; make_stub "$SANDBOX/stub-kimi"
out="$(sandbox_run "$D" "$SANDBOX/stub-kimi" --status)"
grep -q 'no baseline for this version yet' <<<"$out"
check $? 'fresh sandbox reports no baseline' "$(tail -1 <<<"$out")"

# A binary whose hash is already recorded as one of ours must never become the
# baseline, whatever codesign says about it.
D="$SANDBOX/adopt"; mkdir -p "$D"
printf '{"0.36.0":{"patched_sha256":"%s"}}' \
  "$(shasum -a 256 "$SANDBOX/stub-kimi" | cut -d' ' -f1)" > "$D/state.json"
out="$(sandbox_run "$D" "$SANDBOX/stub-kimi")"
grep -q 'looks like one of ours' <<<"$out"
check $? 'refuses to adopt a known patch result as baseline' "$(head -1 <<<"$out")"

echo
echo 'operating-system files:'
D="$SANDBOX/cruft"; mkdir -p "$D/patches" "$D/system-prompts"
make_stub "$D/kimi"
: > "$D/patches/._sidecar.js";      : > "$D/patches/Thumbs.db"
: > "$D/system-prompts/.DS_Store";  : > "$D/system-prompts/._sidecar.md"
: > "$D/patches/real.js"
cp "$D/kimi" "$D/baseline-src" 2>/dev/null || true
mkdir -p "$D/baseline"; cp "$D/kimi" "$D/baseline/kimi-0.36.0"
out="$(sandbox_run "$D" "$D/kimi" 2>&1)"
[ ! -e "$D/patches/._sidecar.js" ] && [ ! -e "$D/patches/Thumbs.db" ] \
  && [ ! -e "$D/system-prompts/.DS_Store" ] && [ ! -e "$D/system-prompts/._sidecar.md" ]
check $? 'os files removed from every input directory'
[ -f "$D/patches/real.js" ]
check $? 'real input files are left alone'

echo
echo 'patch runner:'
# Keep the bundle out of the patch directory: anything ending in .js there is
# loaded as a patch, so in.js/out.js would be executed as code.
D="$SANDBOX/runner"; P="$D/patches"; mkdir -p "$P"
echo 'hello world' > "$D/in.js"
printf 'return js;\n' > "$P/noop.js"
printf 'throw new Error("already patched");\n' > "$P/skip.js"
node "$HERE/lib/run-patches.mjs" "$D/in.js" "$D/out.js" "$P" >/dev/null 2>&1
check $? "'already patched' is a no-op, not a failure"
grep -q 'hello world' "$D/out.js" 2>/dev/null
check $? 'a no-op run still writes the bundle through'
printf 'throw new Error("anchor not found");\n' > "$P/boom.js"
node "$HERE/lib/run-patches.mjs" "$D/in.js" "$D/out.js" "$P" >/dev/null 2>&1
[ $? -ne 0 ]; check $? 'a real patch failure exits non-zero'

# Both stages are piped through `tee` so the summary at the end can count what
# happened. That is only safe while `pipefail` is set: without it the status of
# the pipeline is tee's, which never fails, and a failed patch would sail past
# the guard and get installed.
grep -q 'set -euo pipefail' "$HERE/kimi-patch.sh"
check $? 'kimi-patch.sh still sets pipefail'
bash -c 'set -euo pipefail; if ! (exit 3) | tee /dev/null >/dev/null; then exit 0; fi; exit 1'
check $? 'a failing stage still fails the run when tee-d'
rm "$P/boom.js"; printf 'return 42;\n' > "$P/wrong.js"
node "$HERE/lib/run-patches.mjs" "$D/in.js" "$D/out.js" "$P" >/dev/null 2>&1
[ $? -ne 0 ]; check $? 'a patch returning a non-string is rejected'
rm "$P/wrong.js"; : > "$P/._sidecar.js"
node "$HERE/lib/run-patches.mjs" "$D/in.js" "$D/out.js" "$P" >/dev/null 2>&1
check $? 'an AppleDouble sidecar in patches/ is not executed'

node "$HERE/lib/test_patches.mjs" >/dev/null 2>&1
check $? 'patch runner contract (settings channel, no-op, failures)'

node "$HERE/lib/test_agent_dock.mjs" >/dev/null 2>&1
check $? 'agent dock (anchors, rows, pruning, caps)'

echo
echo 'auto-repatch guard:'
bash "$HERE/lib/test_guard.sh" >/dev/null 2>&1
check $? 'guard suite (16 cases, sandboxed)'

echo
echo 'launcher:'
bash "$HERE/lib/test_launcher.sh" >/dev/null 2>&1
check $? 'launcher suite (18 cases, sandboxed)'

echo
echo 'companion tools:'
python3 "$HERE/lib/config-menu.py" --selfcheck >/dev/null 2>&1
check $? 'config-menu selfcheck'
python3 "$HERE/lib/keyreader.py" >/dev/null 2>&1
check $? 'keyreader selfcheck (arrow-key decoding)'
python3 "$HERE/lib/menu.py" >/dev/null 2>&1
check $? 'menu selfcheck (screens, navigation, mouse mapping)'
# The only test that types into a real terminal. Everything else scripts the
# keyboard with FakeKeys, which never touches select — the exact path that hid
# arrow keys reading as Escape.
python3 "$HERE/lib/test_menu_pty.py" >/dev/null 2>&1
check $? 'arrow keys through a real pseudo-terminal'
python3 "$HERE/lib/patch_settings.py" >/dev/null 2>&1
check $? 'patch_settings selfcheck'
python3 "$HERE/lib/theme-menu.py" --selfcheck >/dev/null 2>&1
check $? 'theme editor selfcheck (schema, merging, screens)'
python3 "$HERE/lib/main-menu.py" --selfcheck >/dev/null 2>&1
check $? 'main-menu selfcheck (state, navigation, cycling)'
# The menu must not spin when there is no terminal: it prints once and exits.
python3 "$HERE/lib/main-menu.py" </dev/null >/dev/null 2>&1
check $? 'menu falls back cleanly without a TTY'
python3 "$HERE/lib/prompt-cost.py" --selfcheck >/dev/null 2>&1
check $? 'prompt-cost selfcheck'
python3 "$HERE/lib/migrate-prompts.py" --selfcheck >/dev/null 2>&1
check $? 'migrate-prompts selfcheck'

if [ "${1:-}" = --full ]; then
  echo
  echo 'full checks (real binary):'
  if [ ! -x "$REAL_BIN" ]; then
    echo '  skip — no Kimi binary installed'
  else
    python3 "$HERE/lib/sea.py" selfcheck "$REAL_BIN" >/dev/null 2>&1
    check $? 'Mach-O identity, shrink and grow round-trip'

    # The behavioural half of the SIGPIPE check: the verdict must not vary.
    seen="$(for _ in $(seq 12); do
              KIMICODEMODS_DATA="$HERE" "$HERE/kimi-patch.sh" --status | awk '/^signature/{print $3}'
            done | sort -u | wc -l | tr -d ' ')"
    [ "$seen" = 1 ]
    check $? 'signature verdict is stable across 12 runs' "got $seen distinct answers"

    # Full prompt round-trip: extracting every prompt and writing it straight
    # back must reproduce the bundle byte for byte.
    W="$SANDBOX/full"; mkdir -p "$W"
    python3 "$HERE/lib/sea.py" extract "$REAL_BIN" "$W/b.js" "$W/m.json" >/dev/null 2>&1
    python3 "$HERE/lib/extract-prompts.py" "$W/b.js" "$W/prompts" >/dev/null 2>&1
    python3 "$HERE/lib/apply-prompt-overrides.py" "$W/b.js" "$W/prompts" "$W/rt.js" >/dev/null 2>&1
    cmp -s "$W/b.js" "$W/rt.js"
    check $? 'all prompts extract and re-apply losslessly'

    # Every patch against the real bundle, each one switched *on*. This is the
    # only check that catches an anchor the release moved, which is the one
    # way a patch fails in practice.
    if [ -f "$HERE/.work/bundle.js" ]; then
      node "$HERE/lib/test_patches.mjs" --bundle >/dev/null 2>&1
      check $? 'every patch finds its anchors in the extracted bundle'
    else
      echo '  skip — no .work/bundle.js; run ./kimi-patch.sh --extract'
    fi

    # The guard's whole reason for existing: patch, let Kimi replace the
    # binary the way an auto-update does, and check that it notices and puts
    # the patches back. Two full patch runs, so it lives here rather than in
    # the fast suite.
    bash "$HERE/lib/test_guard_cycle.sh" >/dev/null 2>&1
    check $? 'guard survives a simulated auto-update (patch, replace, repair)'
  fi
fi

echo
echo 'the suite leaves the real settings alone:'
# Covers the repository's own settings files and Kimi's.
AFTER="$(snapshot)"
[ "$AFTER" = "$BEFORE" ]
check $? 'no check wrote to a settings file outside its sandbox' \
      "$(printf '%s' "$AFTER" | head -3)"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "$PASS passed, 0 failed."
else
  echo "$PASS passed, $FAIL FAILED."
  exit 1
fi

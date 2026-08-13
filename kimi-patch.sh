#!/usr/bin/env bash
# tweakkimi — apply local patches to the Kimi Code binary.
#
# Kimi ships as a Node SEA: the whole bundle is plain UTF-8 JavaScript inside a
# NODE_SEA segment. Patching means extract → transform → repack → re-sign.
#
# The preflights below exist because three failure modes here are silent:
#
#   1. macOS SIGKILLs an edited binary (exit 137, no message) until it is
#      re-signed. A run that stops before `codesign` leaves a dead `kimi`.
#   2. Kimi auto-updates and overwrites the binary in place, so a patched
#      install silently reverts — and the anchors of every patch may have moved.
#   3. Freezing an already-patched binary as the pristine baseline would bake
#      the patches in permanently. Genuine Kimi builds are Developer-ID signed;
#      a patched one is ad-hoc. That difference is the guard.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${KIMI_BIN:-$HOME/.kimi-code/bin/kimi}"
# Code lives at $HERE; state lives at $DATA. They are the same directory in
# normal use — splitting them lets the test suite run against a sandbox
# instead of your real baselines and overrides.
DATA="${TWEAKKIMI_DATA:-$HERE}"
BASELINE_DIR="$DATA/baseline"
PATCH_DIR="$DATA/patches"
PROMPT_DIR="$DATA/system-prompts"
STATE="$DATA/state.json"
WORK="$DATA/.work"
SEA="python3 $HERE/lib/sea.py"

usage() {
  cat <<EOF
usage: $(basename "$0") [--restore] [--status] [--extract] [--extract-prompts] [--help]

  (no flags)         patch the Kimi binary from its pristine baseline
  --restore          put the pristine baseline back and re-sign
  --status           show binary, baseline, patch and override state
  --extract          dump the JavaScript bundle so you can search it for anchors
  --extract-prompts  (re-)extract the prompt files into system-prompts/
  --cost             what each prompt weighs, and what your edits have saved
  --tools            what each builtin tool description costs (see [tools] config)
  --migrate NEW      carry your overrides onto a freshly extracted tree

Editing any file under system-prompts/ replaces that prompt in the binary on
the next run. Free-form JavaScript patches go in patches/*.js.

env: KIMI_BIN   path to the binary (default $HOME/.kimi-code/bin/kimi)
EOF
}

state_get() {  # state_get <version> <field>
  [ -f "$STATE" ] || { echo ""; return; }
  python3 -c '
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
print(d.get(sys.argv[2],{}).get(sys.argv[3],""))' "$STATE" "$1" "$2"
}

state_set() {  # state_set <version> <field> <value>
  python3 -c '
import json,sys,pathlib
p=pathlib.Path(sys.argv[1])
try: d=json.loads(p.read_text())
except Exception: d={}
d.setdefault(sys.argv[2],{})[sys.argv[3]]=sys.argv[4]
p.write_text(json.dumps(d,indent=2,sort_keys=True))' "$STATE" "$1" "$2" "$3"
}

sha() { shasum -a 256 "$1" | cut -d' ' -f1; }

# Replace the binary atomically, via a fresh inode.
#
# Plain `cp` over the target keeps the inode, and macOS caches code-signature
# validity per inode: the kernel can still hold the verdict for whatever used
# to occupy it and SIGKILL the new contents (exit -9, no message). Writing a
# neighbouring file and renaming it sidesteps the cache and is atomic besides,
# so an interrupted install can never leave a half-written binary in place.
install_binary() {  # install_binary <src> <dest>
  local tmp="$2.tweakkimi.$$"
  cp "$1" "$tmp"
  chmod 755 "$tmp"
  mv -f "$tmp" "$2"
}

# Operating-system files are never input. The patterns live in
# lib/os-cruft.txt so the shell, the JavaScript patch runner and the Python
# override applier all work from one list; see that file for why it matters.
CRUFT_LIST="$HERE/lib/os-cruft.txt"
OS_CRUFT=()
while IFS= read -r line; do
  line="${line%%#*}"; line="$(printf '%s' "$line" | tr -d '[:space:]')"
  [ -n "$line" ] && OS_CRUFT+=("$line")
done < "$CRUFT_LIST"

# Delete them from every directory this script reads. Scoped to our own
# directories by construction — callers pass only paths under $HERE.
clean_os_cruft() {  # clean_os_cruft <dir> [label]
  local dir="$1" label="${2:-$(basename "$1")}" args=() n
  [ -d "$dir" ] || return 0
  for pat in "${OS_CRUFT[@]}"; do
    args+=(-iname "$pat" -o)
  done
  unset 'args[${#args[@]}-1]'                     # drop the trailing -o
  n=$(find "$dir" \( "${args[@]}" \) 2>/dev/null | wc -l | tr -d ' ')
  [ "$n" -eq 0 ] && return 0
  find "$dir" \( "${args[@]}" \) -exec rm -rf {} + 2>/dev/null || true
  echo "removed $n operating-system file(s) from $label/"
}

# Every directory patch.sh takes input from, in one place.
clean_all_inputs() {
  clean_os_cruft "$PATCH_DIR" patches
  clean_os_cruft "$PROMPT_DIR" system-prompts
}

# Genuine builds carry a real signature; anything we produced is ad-hoc.
#
# Deliberately no pipe into grep: `grep -q` exits at the first match, codesign
# gets SIGPIPE, and under `set -o pipefail` the whole predicate returns false —
# intermittently, depending on whether codesign had already finished writing.
# That made a patched binary report "Developer ID" about half the time.
is_adhoc() {
  local out
  out="$(codesign -dv "$1" 2>&1 || true)"
  case "$out" in *'flags=0x2(adhoc)'*) return 0 ;; *) return 1 ;; esac
}

# ---------------------------------------------------------------- preflight 1
[ -x "$BIN" ] || { echo "ERROR: no executable Kimi binary at $BIN" >&2; exit 1; }
command -v codesign >/dev/null || { echo "ERROR: codesign not found — cannot re-sign after patching." >&2; exit 1; }
command -v node >/dev/null || { echo "ERROR: node not found — needed to run the patch scripts." >&2; exit 1; }

VERSION="$("$BIN" --version 2>/dev/null | head -1 | tr -d '[:space:]')"
[ -n "$VERSION" ] || { echo "ERROR: '$BIN --version' produced nothing — is the binary intact?" >&2; exit 1; }
BASELINE="$BASELINE_DIR/kimi-$VERSION"
CURRENT_SHA="$(sha "$BIN")"

case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  --status)
    # State comes from the hash, not the signature: a restored binary is
    # pristine in content while still carrying whatever signature it was last
    # given, so reading the signature alone would mislabel it.
    if [ -f "$BASELINE" ] && [ "$CURRENT_SHA" = "$(sha "$BASELINE")" ]; then
      st='pristine (baseline, unpatched)'
    elif [ "$CURRENT_SHA" = "$(state_get "$VERSION" patched_sha256)" ]; then
      st='patched by tweakkimi'
    elif [ ! -f "$BASELINE" ]; then
      st='no baseline for this version yet'
    else
      st='UNKNOWN — neither the baseline nor our patch result'
    fi
    echo "binary    : $BIN"
    echo "version   : $VERSION"
    echo "state     : $st"
    echo "sha256    : ${CURRENT_SHA:0:16}…"
    echo "signature : $(is_adhoc "$BIN" && echo 'ad-hoc' || echo 'Developer ID')"
    if [ -f "$BASELINE" ]; then
      echo "baseline  : $BASELINE ($(sha "$BASELINE" | cut -c1-16)…)"
    else
      echo "baseline  : none for $VERSION yet"
    fi
    echo "patches   : $(ls "$PATCH_DIR"/*.js 2>/dev/null | wc -l | tr -d ' ') in $PATCH_DIR"
    # An override counts as edited when its text no longer hashes to the
    # fingerprint the extractor recorded — no need to open the binary for that.
    python3 -c '
import hashlib, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from oscruft import usable_files
d = Path(sys.argv[1])
if not d.is_dir():
    print("prompts   : none extracted yet (--extract-prompts)"); raise SystemExit
total = edited = 0
for p in usable_files(d):
    raw = p.read_text(errors="replace")
    if not raw.startswith("<!--"): continue
    end = raw.find("\n-->\n")
    head = dict(l.split(":", 1) for l in raw[5:end].splitlines() if ":" in l)
    want = head.get("originSha256", "").strip()
    body = raw[end+5:].rstrip("\n") + "\n" * int(head.get("trailingNewlines", "0").strip() or 0)
    total += 1
    if hashlib.sha256(body.encode()).hexdigest()[:16] != want: edited += 1
print(f"prompts   : {total} extracted, {edited} edited (applied on the next run)")' "$PROMPT_DIR" "$HERE/lib"
    exit 0 ;;
  --cost)
    python3 "$HERE/lib/prompt-cost.py" "$PROMPT_DIR" "${@:2}"
    exit $? ;;
  --tools)
    [ -f "$WORK/bundle.js" ] || { mkdir -p "$WORK"
      src="$BIN"; [ -f "$BASELINE" ] && src="$BASELINE"
      $SEA extract "$src" "$WORK/bundle.js" "$WORK/meta.json" >/dev/null; }
    python3 "$HERE/lib/list-tools.py" "${@:2}"
    exit $? ;;
  --migrate)
    NEW="${2:-}"
    [ -d "$NEW" ] || { echo "usage: $(basename "$0") --migrate <freshly-extracted-tree>" >&2; exit 2; }
    # The ancestor for a genuine three-way merge lives in the old baseline
    # binary, which is kept per version and never deleted.
    OLD_BASE="$(ls "$BASELINE_DIR"/kimi-* 2>/dev/null | grep -v "kimi-$VERSION\$" | tail -1 || true)"
    MERGED="$DATA/system-prompts.$VERSION.merged"
    set +e
    python3 "$HERE/lib/migrate-prompts.py" "$PROMPT_DIR" "$NEW" "$MERGED" \
      ${OLD_BASE:+--base "$OLD_BASE"}
    rc=$?
    set -e
    echo
    if [ "$rc" -eq 0 ]; then
      echo "merged cleanly into $MERGED"
      echo "review it, then: mv $PROMPT_DIR $PROMPT_DIR.old && mv $MERGED $PROMPT_DIR"
    else
      echo "conflicts remain — resolve the .md.conflict files in $MERGED first."
      echo "They cannot reach the binary: the applier only reads *.md."
    fi
    exit "$rc" ;;
  --extract-prompts)
    mkdir -p "$WORK"
    src="$BIN"; [ -f "$BASELINE" ] && src="$BASELINE"
    $SEA extract "$src" "$WORK/bundle.js" "$WORK/meta.json"
    # Do this before the emptiness test below: a lone .DS_Store would
    # otherwise divert a first-time extraction into a .new directory.
    clean_os_cruft "$PROMPT_DIR" system-prompts
    dest="$PROMPT_DIR"
    # Never overwrite edited overrides: extract beside them and let the user
    # merge. Losing hand-written prompt edits to a routine re-extract would be
    # the worst kind of silent damage.
    if [ -d "$PROMPT_DIR" ] && [ -n "$(ls -A "$PROMPT_DIR" 2>/dev/null)" ]; then
      dest="$HERE/system-prompts.$VERSION.new"
      echo "note: $PROMPT_DIR already exists — extracting to $(basename "$dest") instead."
      echo "      Diff the two and carry your edits over; delete the .new tree when done."
    fi
    python3 "$HERE/lib/extract-prompts.py" "$WORK/bundle.js" "$dest"
    exit 0 ;;
  --extract)
    mkdir -p "$WORK"
    # Prefer the baseline: anchors must be written against pristine code, not
    # against a bundle that already carries our own edits.
    src="$BIN"; [ -f "$BASELINE" ] && src="$BASELINE"
    $SEA extract "$src" "$WORK/bundle.js" "$WORK/meta.json"
    echo "bundle at $WORK/bundle.js — grep it for anchors, then write a patches/*.js"
    exit 0 ;;
  --restore)
    [ -f "$BASELINE" ] || { echo "ERROR: no baseline for $VERSION — nothing to restore." >&2; exit 1; }
    # The baseline is a byte-for-byte copy including its original Developer-ID
    # signature, so copying it back is enough. Re-signing here would trade a
    # valid signature for an ad-hoc one and gain nothing.
    install_binary "$BASELINE" "$BIN"
    $SEA verify "$BIN" "$VERSION"
    echo "restored the pristine $VERSION binary, original signature and all."
    exit 0 ;;
  '') ;;
  *) usage >&2; exit 2 ;;
esac

# ---------------------------------------------------------------- preflight 2
# Establish the baseline. Never freeze an ad-hoc-signed binary: that is one of
# ours and would bake existing patches into the "pristine" copy forever.
mkdir -p "$BASELINE_DIR" "$PATCH_DIR" "$WORK"
if [ ! -f "$BASELINE" ]; then
  # Two independent tests, because neither is sufficient alone. The signature
  # is the general one, but `codesign -dv` reads a per-inode cache that can
  # briefly report the previous signature after the file is replaced. The hash
  # check does not depend on that: if this binary is one we produced for any
  # version, it is not a baseline candidate whatever codesign currently says.
  KNOWN_PATCHED="$(python3 -c '
import json, sys
try: d = json.load(open(sys.argv[1]))
except Exception: raise SystemExit
print("\n".join(v.get("patched_sha256","") for v in d.values() if v.get("patched_sha256")))' "$STATE" 2>/dev/null || true)"
  if printf '%s' "$KNOWN_PATCHED" | grep -qx "$CURRENT_SHA" 2>/dev/null || is_adhoc "$BIN"; then
    cat >&2 <<EOF
ERROR: no baseline for $VERSION, and this binary looks like one of ours.

  $BIN

Either it is ad-hoc signed — a genuine Kimi build is Developer-ID signed — or
its hash matches a patch result recorded in state.json. Freezing it as the
baseline would make those edits permanent and unremovable. Reinstall first,
then re-run:

  curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash
EOF
    exit 1
  fi
  cp "$BIN" "$BASELINE"
  state_set "$VERSION" baseline_sha256 "$(sha "$BASELINE")"
  echo "baseline: froze the pristine $VERSION binary at $BASELINE"

  PREV="$(python3 -c '
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
v=[k for k in d if k!=sys.argv[2]]
print(sorted(v)[-1] if v else "")' "$STATE" "$VERSION" 2>/dev/null || true)"
  if [ -n "$PREV" ]; then
    echo
    echo "NOTE: Kimi moved from $PREV to $VERSION. Patch anchors are written against"
    echo "      a minified bundle and drift on every release — expect failures below."
    echo "      Auto-update can be turned off with KIMI_CLI_NO_AUTO_UPDATE=1."
    echo
  fi
fi

# The install must be either pristine or one of ours. Anything else is a third
# party edit and we refuse to overwrite it silently.
BASE_SHA="$(sha "$BASELINE")"
PATCHED_SHA="$(state_get "$VERSION" patched_sha256)"
if [ "$CURRENT_SHA" != "$BASE_SHA" ] && [ -n "$PATCHED_SHA" ] && [ "$CURRENT_SHA" != "$PATCHED_SHA" ]; then
  cat >&2 <<EOF
ERROR: the installed binary is neither the baseline nor our last patch result.

  installed : ${CURRENT_SHA:0:16}…
  baseline  : ${BASE_SHA:0:16}…
  our patch : ${PATCHED_SHA:0:16}…

Kimi may have updated in place without changing its version string, or
something else modified it. Re-run with --restore to go back to the baseline,
or delete $BASELINE to adopt the current binary as the new pristine copy.
EOF
  exit 1
fi

# ------------------------------------------------------------------- patching
echo "Kimi Code $VERSION — patching from the pristine baseline."
clean_all_inputs
$SEA extract "$BASELINE" "$WORK/bundle.js" "$WORK/meta.json"

# Prompt overrides first: they swap whole literals, so the free-form patches
# below see the text the model will actually get.
STAGE="$WORK/bundle.js"
if [ -d "$PROMPT_DIR" ]; then
  echo "prompt overrides from $(basename "$PROMPT_DIR")/:"
  if ! python3 "$HERE/lib/apply-prompt-overrides.py" "$STAGE" "$PROMPT_DIR" "$WORK/bundle.prompts.js"; then
    echo >&2
    echo "ERROR: a prompt override was rejected — the installed binary was not touched." >&2
    exit 1
  fi
  STAGE="$WORK/bundle.prompts.js"
fi

echo "applying $(ls "$PATCH_DIR"/*.js 2>/dev/null | wc -l | tr -d ' ') patch(es):"
if ! node "$HERE/lib/run-patches.mjs" "$STAGE" "$WORK/bundle.patched.js" "$PATCH_DIR"; then
  echo >&2
  echo "ERROR: a patch failed — the installed binary was not touched." >&2
  echo "       Unlike tweakcc, nothing is restored over the target before patching," >&2
  echo "       so your current Kimi keeps whatever state it had." >&2
  exit 1
fi

$SEA repack "$BASELINE" "$WORK/bundle.patched.js" "$WORK/kimi.new"
$SEA sign "$WORK/kimi.new"

# --------------------------------------------------------------- verification
# Verify before installing, so a broken build never reaches $BIN.
if ! $SEA verify "$WORK/kimi.new" "$VERSION"; then
  echo >&2
  echo "ERROR: the patched binary does not run — leaving $BIN untouched." >&2
  echo "       The rejected build is at $WORK/kimi.new for inspection." >&2
  exit 1
fi

# Record the hash before installing. The other order leaves an unrecognised
# binary behind if anything interrupts between the two, and the preflight then
# refuses to touch it until someone runs --restore by hand.
state_set "$VERSION" patched_sha256 "$(sha "$WORK/kimi.new")"
install_binary "$WORK/kimi.new" "$BIN"

if ! $SEA verify "$BIN" "$VERSION"; then
  echo "installed binary fails to run — rolling back to the baseline." >&2
  cp "$BASELINE" "$BIN"
  $SEA sign "$BIN"
  exit 1
fi

echo
echo "Kimi Code $VERSION patched and installed at $BIN"
echo "Baseline kept at $BASELINE — '$(basename "$0") --restore' puts it back."
echo "Kimi replaces this binary when it auto-updates; re-run then (KIMI_CLI_NO_AUTO_UPDATE=1 prevents it)."

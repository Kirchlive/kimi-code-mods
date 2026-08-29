# AGENTS.md

## What this is

`kimi-code-mods` patches the **Kimi Code** CLI binary (a Node.js SEA: plain
UTF-8 JavaScript bundle inside a Mach-O `NODE_SEA` segment). Flow is always
extract from a frozen pristine baseline, transform, repack, re-sign — so the
installed binary accumulates nothing and one command undoes everything.
Verified against Kimi 0.38.0; patching is macOS-only (Mach-O parsing +
`codesign`), the menu runs anywhere.

## Commands

| Command | Purpose |
|---|---|
| `./test.sh` | Fast suite (seconds), works on sandbox copies. Run after every change. |
| `./test.sh --full` | Adds real-binary checks (Mach-O resize, signing, round-trip). Required before touching `lib/sea.py` or the repack path. |
| `node lib/test_patches.mjs` | Patch-runner contract, no bundle needed. |
| `node lib/test_patches.mjs --bundle` | Every patch against the real extracted bundle; each patch is tested with its switch **on**. The suite that matters. |
| `./kimi-patch.sh --status` | Binary / baseline / patch / prompt-override state. |
| `./kimi-patch.sh --extract` | Dump the bundle to `.work/bundle.js` to search for anchors. |
| `./kimi-patch.sh --restore` | Put the pristine binary back. |
| `./kimi-code-mods.sh` | The interactive terminal menu. |

Almost every module in `lib/` has a built-in selfcheck (`python3 lib/<x>.py`
or `--selfcheck`); `test.sh` runs them all. Tests must never write real
settings files — `test.sh` snapshots `patch-settings.conf` and
`~/.kimi-code/{config,tui}.toml` and fails if they changed. Use
`KIMICODEMODS_DATA=<sandbox>` and `KIMI_BIN=<stub>` to redirect state (the
test suite does exactly this).

## Two ways to change Kimi

1. **Prompt overrides**: edit a file under `system-prompts/` and that prompt
   is replaced in the binary on the next run. Everyday path.
2. **Patches**: drop a numbered `.js` file into `patches/` for anything that
   is not a prompt (behaviour, defaults, UI). They run in filename order.
   Overrides run first, so patches see final prompt text.

## Patch contract (see docs/internals.md, follow it exactly)

- Patch receives the bundle as `js`, its switches as `settings`, returns the
  new bundle.
- Locate edits by an **anchor** string; refuse if missing or matched more
  than once. Never patch by offset.
- Throw `new Error('already patched')` for the no-op case — this is the only
  message treated as a skip. Anything else thrown fails the run and leaves
  the installed binary untouched. A **name guard** (`the name X is already
  taken`) must come *after* an own-marker check (`if (js.includes(<most
  specific string this patch writes>)) throw new Error('already patched')`) —
  otherwise the guard fires on the patch's own work when re-applied, and the
  patch runner's verify pass (`--verify`) misreads it as missing.
- The patch runner re-applies every patch to the installed bundle after
  installation (`run-patches.mjs --verify`); each must throw 'already
  patched'. One that applies cleanly there was never in the binary.
- A patch with mode-dependent splices is only covered by the bundle test for
  the modes listed in `ACTIVE` in `lib/test_patches.mjs` — register the
  strongest mode there, or its anchors sit on an untested path.
- **New setting?** Register its default in `lib/patch_settings.py`
  (`DEFAULTS`). The menu builds rows from that table, so an unregistered
  switch is invisible. Every registered switch must appear in exactly one
  menu group reachable from the root menu — both are checked.
- A patch owning a setting should also add a case to the patch runner's
  self-check (`lib/test_patches.mjs`).
- A patch that also exports a **table** for the menu (`PRESETS` in
  `patches/70-spinner-style.js`) is parsed out of the patch source by
  `patch_table()` in `lib/main-menu.py` — a regex, not a JS parser. It must
  tolerate a **quoted** key: `'kimi-code-mods'` is not a bare identifier, and
  a key it fails to match is skipped silently, which shows up as an empty row
  and a fallback value rather than as an error. Guard such a table with a
  selfcheck that compares the menu's parse against the patch's own entry.

### Minified-JS traps (all cost real time here)

- Identifiers contain `$`: regex anchors need `[\w$]+`, not `\w+`.
- `$` in a replacement string is a capture reference: always pass a function
  to `.replace()`.
- Function bodies span lines: don't search line-by-line; read whole file and
  use `indexOf`, or slice the `//#region` block first.
- `toolCall.args[...]` is **empty until the argument finished streaming**:
  during the deltas `args` comes from `parseStreamingArgs`, whose fallback
  regex needs the value's closing quote. Anything drawn live from it appears
  late by exactly the argument's token time. Read
  `extractPartialStringField(toolCall.streamingArguments, key)` instead — it
  walks an unterminated JSON string.
- **Two engine generations exist side by side** (`packages/agent-core-v2` is
  live, `agent-core` mostly dead except shared modules like the ripgrep
  locator). Minified twins differ by `$1`/`$2` suffixes; check the `//#region`
  before trusting an anchor — a patch on the dead generation applies cleanly
  and changes nothing.

## Binary-level gotchas

- Any edit makes macOS SIGKILL the binary (exit 137, silent) until re-signed
  ad-hoc: `codesign -f -s -`, run automatically after repack.
- Growing the payload shifts `__LINKEDIT`; `lib/sea.py` adjusts all load
  commands. Shrinking is padded back with newlines (also terminates a
  trailing line comment).
- Never pipe `codesign` output into `grep` under `pipefail` (SIGPIPE race,
  flaky verdict) — a static test guards this in `test.sh`.
- Replace the installed binary via `install_binary` (new inode + rename), not
  `cp`: macOS caches signature validity per inode.
- Baseline safety: genuine builds are Developer-ID signed, ours are ad-hoc; a
  known patch result (hash in `state.json`) must never be adopted as baseline.
- OS cruft (`.DS_Store`, `._*`, `Thumbs.db`, patterns in `lib/os-cruft.txt`)
  is stripped from `patches/` and `system-prompts/` before every run — never
  let such files become inputs.

## Layout

- `patches/NN-name.js` — numbered patches, filename fixes order.
- `system-prompts/` — 132 extracted prompts as Markdown with an
  `originSha256` header; mirror of the bundle's prompt tree (v2 and legacy
  agent-core paths preserved).
- `lib/` — Python menu framework (`menu.py` shared screen object),
  `patch_settings.py` (settings registry), `sea.py` (Mach-O surgery),
  `run-patches.mjs` (JS runner), test suites (`test_*.sh/py/mjs`).
- `baseline/` (gitignored) — pristine binaries per version. `.work/`
  (gitignored) — extraction/repack scratch. `state.json` (gitignored) —
  recorded baseline/patched hashes per version.
- `kimi-patch.sh` — the orchestrator: preflight, extract, override prompts,
  run patches, repack, sign, install.
- `docs/internals.md` — the authoritative deep-dive; read it before writing
  a patch.

## Conventions

- No build step, no dependencies beyond `python3`, `node`, `git`, and
  (macOS) `codesign`. Scripts run from anywhere (`BASH_SOURCE`-based paths).
- Code and state are split via `KIMICODEMODS_DATA`; tests rely on this.
- Comments in this repo explain *why*, often at length — failures that
  actually happened are the selection rule for both tests and comments.
  Match that style; don't strip it.
- `patch-settings.conf` is deliberately dumb `key=value` (no sections,
  quoting, types); a JS patch and the Python menu must read it identically.
- One change per PR; keep diffs to what the change needs.

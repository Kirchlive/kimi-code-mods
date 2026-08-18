# tweakkimi

Local patches for the Kimi Code binary — the same idea as tweakcc, adapted to a
different container.

```
./kimi-patch.sh                    # patch from the pristine baseline
./kimi-patch.sh --status           # binary, baseline, patches and overrides
./kimi-patch.sh --extract          # dump the JS bundle to search for anchors
./kimi-patch.sh --extract-prompts  # (re-)extract the prompt files
./kimi-patch.sh --restore          # put the pristine binary back
```

There are two ways to change Kimi. **Edit a file under `system-prompts/`** and
that prompt is replaced in the binary on the next run — this is the everyday
path. **Drop a `.js` file into `patches/`** for anything that is not a prompt:
behaviour, defaults, UI. Overrides run first, so the free-form patches see the
final prompt text.

## How Kimi is built

Kimi Code is a **Node.js Single Executable Application**, not a Bun standalone.
The Mach-O carries a `NODE_SEA` segment holding one section,
`__NODE_SEA_BLOB`, which contains the build path followed by the entire bundle
as **plain UTF-8 JavaScript** — no snapshot, no bytecode cache. On 0.36.0 that
is 22 MB of minified source inside a 57.6 MB segment.

That makes it easier to reach than Claude Code's Bun bundle, where the
entrypoint has to be resolved through a module directory by name. There is no
module directory here: one blob, one length prefix.

Two things are harder:

**The binary is signed for real.** Kimi ships Developer-ID signed with a
hardened runtime; Claude Code is only ad-hoc signed. Any edit makes macOS
`SIGKILL` the process — exit 137, no message, no hint that the signature is the
cause. `codesign -f -s -` fixes it and is run automatically after every repack.
Hardened runtime and notarisation are lost in the process, which is harmless
for a locally executed CLI.

**Growing the payload moves `__LINKEDIT`.** Every remaining load command points
into it — symbol table, string table, chained fixups, exports trie, function
starts, code signature. `lib/sea.py` shifts all of them by one uniform delta,
rounded up to a page. Shrinking needs none of that: the payload is padded back
to its original length with newlines, which JavaScript ignores and which also
terminates a trailing line comment.

## Writing a patch

Drop a `.js` file into `patches/`. They run in filename order, each receiving
the bundle as `js` and its own switches as `settings`, and returning the new
bundle — close to the shape tweakcc's `adhoc-patch --script` uses, so patches
move between the two setups with little work.

```js
const MODE = String(settings.get('my_switch', 'off')).toLowerCase();
if (MODE === 'off') throw new Error('already patched');
const ANCHOR = '…some minified fragment…';
if (js.includes(REPLACEMENT)) throw new Error('already patched');
const n = js.split(ANCHOR).length - 1;
if (n === 0) throw new Error('anchor not found — shape changed this release');
if (n !== 1) throw new Error(`anchor is not unique (${n}) — refusing to guess`);
return js.replace(ANCHOR, () => REPLACEMENT);
```

`already patched` is the one message treated as a no-op. Everything else
thrown fails the run and leaves the installed binary untouched.

`settings` comes from `patch-settings.conf`, read once by the runner. It used
to be read by each patch, in twenty lines that three of them had copied; a
fourth copy would have been the moment the four started to disagree about what
a missing file means. Register the default in `lib/patch_settings.py` — the
menu builds its rows from that table, so a switch is offered the moment it is
registered, and a switch that exists only in the patch is invisible.

To find anchors, run `--extract` and search `.work/bundle.js`. Useful entry
points on 0.36.0: `systemPrompt` (207 hits), `<system-reminder>` (17 hits),
`You are Kimi`.

Three traps, all of which cost real time here. Minified identifiers contain
`$`, so anchors need `[\w$]+` rather than `\w+`. A `$` in a replacement string
is a capture reference — always pass a function to `.replace()`. And searching
the bundle line by line finds nothing when a function body spans lines, which
most of them do: read the file and use `indexOf`, or slice the `//#region`
block first.

**Which generation.** Kimi ships two engines side by side and most things
exist twice. `packages/agent-core-v2` is live; `packages/agent-core` is not,
*except* for shared support modules — the ripgrep locator lives there and v2
calls it. Minified twins are told apart by their `$1`/`$2` suffixes, so an
anchor that includes the unsuffixed names lands on the live copy. Check the
`//#region` a candidate sits in before trusting it; a patch on the dead
generation looks applied and changes nothing.

## Testing a patch

```
node lib/test_patches.mjs            the runner's contract, no bundle needed
node lib/test_patches.mjs --bundle   every patch against the real bundle
./test.sh --full                     the above, plus the binary round-trip
```

The bundle suite is the one that matters. It applies each patch with its
switch turned **on** — not in whatever state `patch-settings.conf` happens to
be in, because a patch that is off by default would otherwise report itself as
a no-op and sail through with a broken anchor. For each it checks that the
anchors are found, that the bundle actually changed, and that applying it to
its own output throws `already patched` rather than patching twice.

Three patches get a second kind of check, because for them placement is not
the interesting half. The effort router, the verb rotation and the border
translation are lifted back out of the patched bundle and **run**: a router
that splices cleanly and then calls everything `medium` is worse than one that
fails loudly, and a swap table that misses a character leaves a frame half
round and half square. That check has already caught one bug in itself, which
is the sort of thing that argues for keeping it.

Then it applies the whole stack in filename order and runs `node --check` over
the result. That last one earns its place: a patch can splice in broken
JavaScript, pass every other check, and take the binary down at startup with
no message at all.

## The menu

```
./tweakkimi.sh                     everything, under one roof
python3 lib/theme-menu.py          just the colours
python3 lib/config-menu.py         just config.toml
```

Every screen is the same object — a header, a list of rows, a help line — and
`lib/menu.py` owns what they have in common: the arrow keys, home and end,
digit shortcuts, the wheel, and clicks. That was written once for the root
menu and every screen underneath it then fell back to `input()` and a number,
so the arrow keys stopped working exactly where you had just learned to use
them. Now they do not.

Rows come in five kinds. `cycle` steps through a list with ‹› and writes as it
goes; `action` runs on enter; `submenu` opens another screen; `info` states a
fact and is skipped by navigation; `sep` is a rule. A row may also do both —
carrying an `on_cycle` lets enter ask for a typed value while ‹› clears it,
which is how a colour or a duration gets a row at all.

**The root menu follows tweakcc's order**, so that anyone arriving from it
finds the same things in the same places: appearance first, then the model and
routing settings, then Kimi's own configuration, then the doors out. Two of
tweakcc's entries have nothing behind them here — Fable plan mode and Better
Claude in Chrome are Claude-only — and their places are taken by the two
things tweakcc has no equivalent for, tool and hook setup. Two more of its
entries have no Kimi counterpart at all and are simply absent: input pattern
highlighters, and the system-reminder overrides.

The patch switches are grouped the way tweakcc groups them (Thinking verbs,
Thinking style, User message display, the effort router, and Misc for the
rest) rather than piled onto one screen. Every registered switch has to appear
in exactly one group and every group has to be reachable from the root menu —
both are checked, because a switch that is registered and unreachable is
invisible in a way nothing else would report.

**The terminal cursor is hidden while a screen is up** and shown again before
anything reads a line, including on the way out. The selected row is already
marked; a second block blinking under the last line only competes with it.

**Nothing reads a line of text any more.** `input()` reads in cooked mode, so
an arrow key pressed out of habit arrived as the three bytes of its escape
sequence *inside the returned string* — and that string was written to
`config.toml`, where `\x1b` is not a legal character. The next parse threw out
of a menu that had already redrawn. Every typed value now goes through
`menu.field`, a bordered one-line field that reads decoded keys: an arrow is
navigation and cannot become text, backspace deletes, escape means "leave the
setting alone", which is a different answer from an empty field. Where the
program already holds the list — the twenty hook events, the models in a pool
— `menu.pick` offers it instead, so there is nothing to misspell and nothing
to validate afterwards.

**Backspace removes; ‹› only ever changes a value.** Deleting used to be ‹› on
a handful of screens, which meant stepping through a list of saved tool sets
to read it deleted one. One key, one meaning, and the destructive one is the
key that already means "remove" everywhere else.

**A colour is picked, not typed.** Six hex digits are a description of a
colour rather than the colour itself, and the difficult part is getting from
the one you can picture to those digits. `menu.color` draws three bars — hue,
saturation, lightness, each *in* the colours it selects — with ←→ to nudge,
shift+←→ for ten at a time, `a` to switch to RGB when a value has to match
something exact, `p` to lift a hex value out of the clipboard and `h` to type
one. Beside it runs the same mock transcript the theme editor shows, following
the bars as they move, with the line that token draws **bold and underlined**
and `◀` against it. Bold alone is a real difference but not a reliable one —
on a light palette or beside text that is already emphasised it takes a second
look; an underline is positional rather than a matter of weight, so the two
together answer the question at a glance. The theme editor does the same from
its list: move the cursor down the nineteen tokens and the preview follows, so
"which one is that" costs one keypress rather than trial and error. `border`
draws the frame around the whole preview rather than a line inside it, so
selecting it marks the frame.

Every colour in Kimi comes from the palette, so the screens whose look depends
on one — your own messages, the spinner, the composer frame — carry a
**Colours** row that opens those tokens rather than offering a second place to
set the same value. That needs a theme of your own that is also the one in
use; when there is not one, the screen says so and offers to make it. Which
theme is in use lives in `~/.kimi-code/tui.toml`, not `config.toml` — Kimi
splits its settings and says so in the file it writes — and the theme list
both shows it and can change it.

**Screens that configure something visual show it.** Themes, the spinner, the
rotating verb and your own message frame each draw a preview beside the rows —
tweakcc's second column, and the same reasoning: `glow` and `wave` are names
for something you recognise on sight and not otherwise. The preview is part of
the same rendered lines as the rows, so the mouse mapping still holds, and it
drops below the list on a window too narrow to hold both rather than wrapping.
The spinner presets and the built-in verbs are read out of the patches that
splice them in, so the menu cannot offer a preset the patch does not know.

Two things follow from how it is drawn. The mouse map is built by the same
pass that renders, so a click cannot land on the wrong row; and anything that
is not a row — header, separator, the help line — is inert rather than treated
as the nearest row, because guessing what a stray click meant is worse than
doing nothing.

Without a terminal, every screen prints once and returns instead of spinning
on EOF. That is what keeps `| less`, `--dry-run` and the test suite honest.

**One place where `kimi doctor` is not the authority.** Everywhere else the
config menu writes a file and lets Kimi's own validator decide whether it is
acceptable — that is the rule, and it is the right one. `[secondary_model]` is
the exception. Its cross-field rules (a pool may not be keyed `primary`,
`force` may not be combined with a pool, `default_model` must name a pool
entry) live in `assertValidSubagentModelConfig`, which hangs off creating a
session rather than off validating a file. Doctor reports "All checked config
files are valid" for every one of those, with the secondary-model flag off and
on alike — both were tried. So the subagent screen checks them itself, before
writing, and says which rule would have been broken.

**Colours.** `Themes` writes `~/.kimi-code/themes/<name>.json`, which Kimi
already loads — no patch involved. The editor exists because the loader fails
silently three ways: a colour that is not six-digit hex is dropped without a
word, an unknown token name is kept in the file and ignored, and a theme named
`dark`, `light` or `auto` never appears in `/theme` at all. All three are
refused here, where you can still see why.

## Operating-system files are never input

Anything matching `lib/os-cruft.txt` is deleted from every directory the
patcher reads — `patches/` and `system-prompts/` — and ignored even if it
somehow survives. The list covers macOS, Windows and Linux droppings, and it is
read by all three implementations (`kimi-patch.sh`, `lib/run-patches.mjs`,
`lib/oscruft.py`), so adding a pattern there takes effect everywhere at once.

Two of those patterns earn their place rather than being tidiness:

- **`._*`** — macOS AppleDouble sidecars. `._system.md` sits next to
  `system.md` and would be read as a prompt whose header is binary garbage;
  `._fix.js` in `patches/` would be handed to the patch runner as code.
- **`.DS_Store`** — makes an otherwise empty `system-prompts/` look occupied,
  which is enough to send a first-time `--extract-prompts` into a `.new` tree
  that nobody asked for.

`python3 lib/oscruft.py` self-checks the matching, including that real inputs
like `read.mustache.md` and `00-banner.js` are *not* caught.

## What the preflights protect against

**A dead binary.** The patched build is verified *before* it is installed, and
rolled back from the baseline if the installed copy still fails. Unlike
tweakcc's `--apply`, nothing is restored over the target up front, so a failing
patch leaves the current install exactly as it was.

**A poisoned baseline.** The baseline is stored per version
(`baseline/kimi-<version>`), so a stale copy can never overwrite a newer
release — the failure mode that makes tweakcc silently downgrade Claude Code.
Freezing a baseline is also refused when the installed binary is ad-hoc signed,
since that means it was already patched and the edits would become permanent.

**A silent auto-update.** Kimi replaces its own binary and backs the old one up
to `kimi.bak`. The patch is gone afterwards and the anchors have probably moved.
A new version gets a fresh baseline and a warning that drift is expected;
`KIMI_CLI_NO_AUTO_UPDATE=1` prevents the update.

## Extracted prompts

```
python3 lib/extract-prompts.py .work/bundle.js system-prompts
```

Kimi's prompts are markdown and YAML files imported with `?raw`, and the
bundler leaves the original path in a region comment:

```
//#region ../../packages/agent-core/src/profile/default/system.md?raw
var system_default$1;
var init_system$1 = __esmMin((() => { system_default$1 = `You are …`; }));
```

So they can be recovered as their real source files rather than guessed at by
shape. `system-prompts/` mirrors the upstream directory layout; each file keeps
a header with source path, module name and bundle offset. On 0.36.0 that is
**117 files, 292k characters**:

| | files | chars |
|---|---|---|
| skills | 18 | 114k |
| tool descriptions | 57 | 96k |
| agent profiles + system prompt | 10 | 50k |
| other agent-core prompts | 21 | 26k |
| inline constants | 11 | 6k |

Two things to know when reading them. Kimi ships **two engine generations side
by side** — `packages/agent-core` (48 files) and `packages/agent-core-v2`
(58) — so most prompts appear twice, and only the ones the running profile
loads are live. And placeholders come in two flavours: `{{ VAR }}` in the
mustache variant, `${VAR}` in the template variant. The filename records which.

A handful of prompts have no source file behind them and live in named
constants instead; those land in `system-prompts/inline/` — `PLAN_ROLE`,
`CODER_ROLE`, `TASK_AGENT_ROLE_PREFIX`, `SKILLS_SECTION_PROSE`,
`DEFAULT_SUMMARY_PROMPT`, `SIDE_QUESTION_SYSTEM_REMINDER` among them.

Coverage was checked the other way round too: every prose literal of 200+
characters in the bundle that is *not* covered by these files was reviewed, and
what remains is JSDoc and library code, not prompt text.

### Editing them

Change the markdown below the header comment and run `./kimi-patch.sh`. Leave
the header alone — it is how the file finds its way back into the binary.
`--status` reports how many overrides differ from the extracted original, which
it works out from the recorded fingerprint without opening the binary at all.

Prompts are located by **anchor**, never by the recorded offset: offsets shift
as soon as an earlier replacement changes length, and mean nothing after an
update. The anchor is the upstream source path from the region comment, or the
constant name for inline prompts — both are names from Kimi's own code rather
than bundler artefacts, so they survive a release far better than a position or
a minified identifier like `system_default$1`.

Three things are checked before anything is written:

**Drift.** The header records a fingerprint of the pristine prompt. When Kimi
ships a new wording, an override written against the old one is reported and
skipped rather than silently forced over the new text. Re-extract with
`--extract-prompts` (it writes to `system-prompts.<version>.new/` when your
tree already exists, so your edits are never overwritten), carry your change
across, run again.

**Interpolation.** Prompts carry `${VAR}` and `{{ VAR }}` holes the runtime
fills. An override that invents a new one is refused outright — it would break
the bundle at load. One that drops an existing hole is applied but reported,
because whatever that hole delivered is now missing from the prompt.

**Escaping.** Text goes back into a JavaScript literal, so backslashes and the
quote character are re-escaped while `${` is left intact. `lib/jsstr.py` owns
this in one place and has a self-check: `python3 lib/jsstr.py`. Escape handling
must be a single left-to-right pass — replacing sequences one after another
turns `\\r` in Kimi's own Edit tool description into a carriage return, which
is exactly the bug that showed up when the round-trip was first verified.

The round-trip is verified, not assumed: extracting all 117 prompts and writing
them straight back produces a bundle byte-identical to the original.

## What the prompts cost

```
./kimi-patch.sh --cost           # full report
./kimi-patch.sh --cost --top 30  # just the expensive ones
./kimi-patch.sh --cost --json    # machine-readable
```

Prompts are paid for on every turn they are included in, so the question worth
asking is not how long a file is but where cutting would help. The report
answers it three ways: the total split by engine generation and category, the
most expensive individual prompts, and what each override has saved against the
pristine text it replaced. The pristine length comes from the `chars` header
written at extraction time, so the numbers stay correct after patching.

Token figures are estimates at 3.7 characters per token — use them to compare
prompts against each other, not as a billing statement.

**Half of the 79k tokens is dead weight.** The binary carries both engine
generations; only the one the running profile loads is ever sent. On 0.36.0
that is **v2** (`packages/agent-core-v2`), established by patching a distinct
codeword into each generation's `system` prompt and asking Kimi which one it
sees. `packages/agent-core` is inert — do not spend effort trimming it.

## Trimming the tool catalogue

Builtin tool descriptions cost about **11,700 tokens per request** across 25
tools. `./kimi-patch.sh --tools` prints the per-tool table, read from the
bundle rather than a hardcoded list, so a rename shows up as a changed table
instead of a dead config entry.

This needs no patch. Kimi registers a global `[tools]` config section with
`enabled` and `disabled` arrays, evaluated for builtin tools and reaching the
array handed to the model — a disabled tool never enters it. Do not confuse it
with the `enabledTools`/`disabledTools` keys inside an MCP server entry, which
are MCP-only; that similarity is what makes this look unconfigurable at first.

```
./kimi-patch.sh --tools --toml Cron Goal    # paste-ready [tools] block
```

Cron, Goal and Swarm together are about 4,500 tokens per turn. Nine names are
protected and refused: `Bash Read Write Edit Grep Glob TaskList TaskOutput
TaskStop`. The three `Task*` tools jointly decide Bash's backgrounding, so
removing one changes Bash's behaviour silently. The `enabled` allowlist is the
stronger lever if you know the handful of tools you actually use.

Verified as far as it can be without a live session: `kimi doctor` accepts the
generated config and the code path was traced end to end. Watching a real
request go out with a shortened tool array is still outstanding.

## Surviving a Kimi update

Two separate problems, two tools.

**Your overrides go stale.** An override records a fingerprint of the prompt it
was written against; when Moonshot rewrites that prompt the applier skips the
override rather than force it. `./kimi-patch.sh --migrate <new-tree>` performs
a three-way merge instead. Most files need no merge: one you never edited is
provably pristine, and one upstream never touched is detectable by comparing
the two headers. Only a prompt that both sides rewrote needs a real ancestor —
and that text is still inside the old baseline binary, which is kept per
version and never deleted, so nothing has to have been snapshotted in advance.

Conflicts cannot reach the binary. They are written as `<name>.md.conflict`,
which the applier's `*.md` glob does not match, while the `.md` is left at the
new upstream text. Resolve the `.conflict` file and rename it over the `.md`.

**The binary itself is replaced.** Kimi updates in place and moves the old file
to `kimi.bak`; every patch is gone at that moment and nothing says so — the CLI
still starts, it is just stock again.

```
lib/kimi-guard.sh check    # is the binary still ours? (0.02s once warm)
lib/kimi-guard.sh repair   # put the patches back if it is not
lib/kimi-guard.sh plist    # a launchd agent that repairs on every rewrite
```

That cycle has been run end to end, in a sandbox on a copy of the baseline:
patch, replace the binary the way an update does, and watch the guard notice
and put the patches back. It reports `pristine — the patches are gone` with
exit 10, repairs, and both markers are in the binary afterwards. The refusal
is checked too: on a version change it exits 11, leaves the binary byte for
byte as it found it, and hands over to a human. `lib/test_guard_cycle.sh` runs
it again; `./test.sh --full` calls it.

Install the watcher once:

```
lib/kimi-guard.sh plist > ~/Library/LaunchAgents/com.tweakkimi.guard.plist
launchctl load ~/Library/LaunchAgents/com.tweakkimi.guard.plist
```

It fires exactly when Kimi rewrites the binary — the one moment you are not
waiting on anything. `check` caches its verdict against size and mtime, so it
only hashes 180 MB when the file actually changed; any rewrite invalidates the
cache, so it can never hide an update.

The guard refuses two things. It will not repatch **across a version change**,
because new anchors need a new baseline and patching blindly would leave you
quietly less patched than before. And it will not touch the binary **while Kimi
is running**, since overwriting a mapped Mach-O takes the process down with it.

macOS is the target; `check` and `repair` work on Linux, the launchd agent does
not. Windows is out of scope.

## Two things Kimi already does

Worth knowing before writing a patch for either.

**Fullscreen.** Kimi ships a complete alternate-screen renderer —
`TuiAltScreen extends TuiBase` with `mode = "fullscreen"`, viewport diffing,
scroll view and screen takeover. It is selected by an environment variable:

```
KIMI_CODE_TUI_FULL_SCREEN=1 kimi
```

Nothing to port. The TUI is a 192-module in-house layer on
`@earendil-works/pi-tui`, not Ink, so transplanting a renderer from another CLI
would mean bringing its whole state and layout stack along.

**Swarm.** `/swarm` exists as a slash command: bare to toggle the mode, with a
subcommand to set it, or with a task to start one directly. Behind it sit an
`AgentSwarm` tool, a `SwarmMode` with its own enter and exit prompt fragments,
two permission policies that stop `AgentSwarm` being combined or repeated in
one response, and `KIMI_CODE_AGENT_SWARM_MAX_CONCURRENCY`.

Per-subagent model choice — the part resembling a model cluster — sits behind
the `secondary-model` experimental flag. With it off, subagents inherit the
parent's model unconditionally. There are two flags in the binary,
`secondary-model` and `tool-select`, and a `/experimental-flags` command to set
them.

## What this does not have

No anchor catalogue. Most of tweakcc's value is the several thousand curated
prompt anchors that a fork re-audits after every release. Nothing equivalent
exists for Kimi, so every patch here is one you wrote and one you maintain.

## Tests

```
./test.sh          # ~7 seconds, no 180 MB copies
./test.sh --full   # adds the real binary: Mach-O resize, signing, full round-trip
```

The selection rule is simple: every case is a failure that actually happened
while building this. Among them —

- **`\r` is text, not a carriage return.** Decoding escapes by sequential
  replacement corrupted eight tool descriptions before anyone noticed.
- **`codesign … | grep -q` under `pipefail`.** grep exits at the first match,
  codesign dies of SIGPIPE, and the predicate returns false — about half the
  time. A patched binary intermittently reported "Developer ID".
- **`._sidecar.js` in `patches/`.** A macOS sidecar handed to the patch runner
  as source code.
- **Adopting a patched binary as the baseline**, which would make the edits
  permanent.
- **A drifted override being forced** over prompt text upstream has since
  rewritten.

The suite runs against a sandbox rather than your real state: `TWEAKKIMI_DATA`
redirects baselines, patches and overrides to a temporary directory, and a stub
stands in for the binary wherever a real Mach-O is not required. Your
`baseline/`, `patches/` and `system-prompts/` are never touched.

`--full` additionally runs `lib/sea.py selfcheck`, which round-trips the
payload through identity, shrink and grow, and verifies that extracting all 117
prompts and re-applying them reproduces the bundle byte for byte.

### Mouse

The menu takes clicks as well as keys. Clicking a row selects *and* opens it —
a row is a button, and making it select first would be a keyboard habit
imposed on a pointer. On a `‹›` row a click advances the value, exactly as the
arrow keys do. The header, the banner and the separators are inert: guessing
what a stray click meant is worse than doing nothing. The wheel moves the
selection.

Nothing about the keyboard changed. Where the mouse is unavailable — a
terminal that does not report, tmux without `set -g mouse on`, stdout
redirected — the menu simply stays keyboard-driven, with no warning and no
wait.

Tracking is switched on and off around each keystroke, inside the same
`try/finally` that saves and restores the terminal attributes. That is
deliberate on two counts: a terminal left in tracking mode writes escape
sequences into the shell on every pointer movement, which the user has no
obvious way to stop; and anything an entry runs — the TOML editor,
`kimi-patch.sh`, your `$EDITOR` — gets a clean terminal rather than a stream
of mouse reports in its stdin. `MOUSE-CLICK.md` has the background.

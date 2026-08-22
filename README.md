<div align="center">

<img src="https://i.imgur.com/b5tyef7.jpeg" alt="Welcome to Kimi Code Mods!" width="880">

**A terminal menu that patches your Kimi Code install — spinners, themes,
prompts, defaults — and can always put it back.**

[![macOS](https://img.shields.io/badge/macOS-supported-EA4242)](#requirements)
[![Kimi Code](https://img.shields.io/badge/Kimi%20Code-0.38.0-EA4242)](#version-compatibility)
[![tests](https://img.shields.io/badge/tests-29%20passing-EA4242)](#tests)
[![license](https://img.shields.io/badge/license-MIT-EA4242)](LICENSE)

[Install](#install) · [What it changes](#what-it-changes) ·
[Undo](#undo) · [How it works](#how-it-works) · [Internals](docs/internals.md)

</div>

---

Kimi Code ships as a single binary with its UI, prompts and defaults compiled
in. There is no settings file for most of it. `kimi-code-mods` opens that
binary, applies the changes you picked in a menu, and puts it back together —
starting from a pristine copy every time, so nothing accumulates and one
command undoes all of it.

```
❯ Working Style                     ●  ▏▎▍▌▋▊▉█
  Thinking Style                    ○  ⠋ ⠙ ⠹ ⠸ ⠼
  User Message Display              ▌ your text, framed
  Themes                            Kimi-Code-Mods   ← in use
  ─────────────────────────────────────────────────────────────
❯ Apply                             run kimi-patch.sh
  Restore Original Kimi Code        keeps your settings
```

## Install

**macOS, Linux, WSL**

```sh
curl -fsSL https://raw.githubusercontent.com/Kirchlive/kimi-code-mods/main/install.sh | bash
```

**Windows (PowerShell)**

```powershell
iwr -useb https://raw.githubusercontent.com/Kirchlive/kimi-code-mods/main/install.ps1 | iex
```

<details>
<summary><b>Inspect before you run it</b> — recommended, this tool rewrites a binary</summary>

Piping a script into a shell means running code you have not read, and this one
goes on to modify an application you use. Download it first if that matters to
you:

```sh
curl -fsSL -o install.sh https://raw.githubusercontent.com/Kirchlive/kimi-code-mods/main/install.sh
less install.sh
bash install.sh
```

The installer itself touches no Kimi installation. It checks prerequisites,
puts the repository in `~/.kimi-code-mods`, and links `kimi-code-mods` into
`~/.local/bin`. Patching happens later, when you choose **Apply** in the menu.

</details>

<details>
<summary><b>From a checkout</b></summary>

```sh
git clone https://github.com/Kirchlive/kimi-code-mods.git ~/.kimi-code-mods
~/.kimi-code-mods/kimi-code-mods.sh
```

</details>

Then open the menu:

```sh
kimi-code-mods
```

Arrow keys move, `enter` opens, `‹›` change a value, `esc` goes back, `q`
quits. Nothing is written to Kimi until you pick **Apply**.

### Requirements

| | |
|---|---|
| **macOS** | Everything. Patching reads the Mach-O header of Kimi's binary and re-signs with `codesign`. |
| **Linux / WSL** | The menu runs, **Apply does not** — the two steps above are macOS only. |
| **Windows** | Not natively. The PowerShell installer sets things up inside WSL, with the same limit. |

Also needed: `python3` (menu), `node` (patch runner), `git`, and on macOS the
Xcode command line tools for `codesign`.

## What it changes

Every switch below is off, or on Kimi's own value, until you change it. The
menu writes to `patch-settings.conf`; **Apply** is what reaches the binary.

**Look**

- **Themes** — full palette editor over Kimi's 19 colour tokens, with a live
  preview of a session. Ships two presets that cannot be deleted:
  `Kimi-Code-Mods` and `Default Kimi`.
- **Thinking style** — the spinner while Kimi thinks: nine presets, your own
  frames, speed, and a reverse-mirror run. The preview spins at the speed you
  set.
- **Working style** — the *other* spinner, the one turning while Kimi waits on
  the model or a tool. Kimi keeps two alphabets; this is the second, settable
  on its own.
- **Thinking verbs** — rotate a word beside the spinner instead of always
  saying "working". Your own list, your own format.
- **User message display** — a marker in front of what you typed, a frame
  around it, and the weight it is drawn in.
- **Welcome banner** — greet with *Welcome to Kimi Code Mods!* and put horns
  on the logo.
- **Fullscreen renderer** — the alternate screen buffer, patched into the
  binary so it holds however Kimi is started, not only through a launcher.

**Behaviour**

- **Toolsets, subagent models, tool setup** — which tools exist, which model
  each subagent uses.
- **Complexity effort router** — set reasoning effort per turn from the prompt.
- **AGENTS.md alternative names** — have Kimi read `CLAUDE.md` as well.
- **Skills, hooks, loop control, reasoning, transcript window** — Kimi's own
  `config.toml` keys, edited where you can see what they do.
- **Misc** — slash-command popup height, `/wd` for changing directory,
  click-to-position-cursor, read limits, line numbers, auto-accept plans.

**Prompts**

69 system prompts are extracted out of the binary into `system-prompts/`. Edit
one as plain Markdown and it replaces the original on the next run. A prompt
whose anchor moved in a Kimi release is reported and skipped, never guessed at.

**Cost report** — what every prompt weighs in tokens, so you can see what you
are paying for before you trim it.

## Undo

There are two, and neither depends on the other.

```sh
kimi-code-mods              # menu → Restore Original Kimi Code
~/.kimi-code-mods/kimi-patch.sh --restore
```

The first thing a patch run ever does is freeze an untouched copy of your Kimi
binary under `baseline/`. Every later run starts from that copy, not from the
patched one — so patches never stack, and restoring is a file copy rather than
an attempt to undo edits. Your settings survive a restore; only the binary goes
back.

To remove the tool itself:

```sh
rm ~/.local/bin/kimi-code-mods
rm -rf ~/.kimi-code-mods        # settings, baseline and patches live here
```

## How it works

Kimi Code is a Node single-executable application: a JavaScript bundle packed
into a Mach-O binary. A run is five steps, and stops at the first one that
fails without touching what is installed.

1. **Freeze** an untouched copy under `baseline/`, once per Kimi version.
2. **Extract** the ~23 MB bundle out of the baseline.
3. **Apply** your prompt overrides, then the patches in `patches/`. Each patch
   locates its anchor and refuses to act if the anchor is missing or ambiguous.
4. **Repack** the bundle and re-sign ad-hoc with `codesign`.
5. **Verify** the result runs and reports the expected version — and roll back
   to the baseline if it does not.

A run ends with a summary of what took, what had nothing to do, and what was
left behind:

```
 Apply summary

   patches   11 applied, 5 no-op, 0 failed
   prompts   0 applied, 61 unchanged, 8 anchor missing, 0 rejected
   binary    repacked, re-signed ad-hoc, verified 0.38.0

   result    OK — Kimi Code 0.38.0 is patched and installed
```

Writing your own patch, the anchor rules, and how prompt extraction works are
in [docs/internals.md](docs/internals.md).

### What this costs you

Re-signing is **ad-hoc**: the hardened runtime and Apple's notarisation are
gone from the patched binary. That is inherent to modifying a signed
application, not a shortcut taken here. If your setup requires a notarised
Kimi, restore the baseline.

### Surviving a Kimi update

Kimi replaces its own binary when it auto-updates, which removes every patch.
Your settings are untouched — run **Apply** again and they come back. To stop
Kimi updating itself:

```sh
export KIMI_CLI_NO_AUTO_UPDATE=1
```

The menu notices when the installed binary is no longer the one it patched and
says so in its header.

## Version compatibility

Verified against **Kimi Code 0.38.0**.

Patches anchor on text inside a minified bundle, and that text moves between
releases. When an anchor is gone the patch reports it and is skipped — the run
carries on with the rest, and nothing half-applied is installed. Prompt
overrides work the same way: 8 of 69 currently have no anchor in 0.38.0,
because Kimi moved that text, and are reported on every run.

## Tests

```sh
./test.sh
```

29 checks: the patch runner's contract, the auto-repatch guard, the launcher,
and the self-checks of every menu module (about 950 assertions in total),
including navigation driven through a real pseudo-terminal. The suite works on
copies and verifies at the end that it wrote to no real settings file.

## Prior art

[tweakcc](https://github.com/Piebald-AI/tweakcc) does this for Claude Code and
is where the idea came from — the marker, the bold-cyan selected row and the
preview-beside-the-list layout are all lifted from it. This is the same idea
pointed at a different binary, with a different container to open.

## License

MIT — see [LICENSE](LICENSE).

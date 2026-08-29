// Show Bash calls the way every other tool call is shown: one header line
// with the tool name and its key argument, instead of a "Ran a command"
// label with the command repeated on a `$ ` line underneath. And drop the
// "Used"/"Using" verb from every tool header while at it — the bullet and
// the chip already carry the state, so `● Used Edit (path) · +1` reads the
// same as `● Edit (path) · +1`, minus the word.
//
// `● Used Read (path) · 118 lines` is the shape every tool gets from
// `buildHeader()` in `src/tui/components/messages/tool-call.ts` — Bash is the
// single special-case branch in that function, and the only one whose header
// says nothing about what it ran. The command itself follows on its own
// preview lines, drawn by a `ShellExecutionComponent` child.
//
// WHY NOT extractKeyArgument
// It knows Bash and returns the command's first line, but it also runs every
// value through `truncateArgValue`, which head-cuts non-path strings at
// MAX_ARG_LENGTH (60) with a `...` suffix — `./test.sh 2>&1 | tail -2 && …`
// is exactly that cut. The header has the whole line width to spend, so the
// branch reads `args.command` directly: first line, `…`-suffixed only when
// more lines follow, never column-capped.
//
// The `$ ` preview block is suppressed unconditionally, not just collapsed:
// `expanded_by_default` (patches/74) turns `this.expanded` on from the start,
// which made a collapsed-only guard a no-op for anyone running it, and
// ctrl+o toggles every call at once, so "explicitly opened" cannot be told
// from "on by default" per card. The command is in the header either way;
// the output stays below it, expanded or not.
//
// The streaming preview is left alone on purpose while streaming: the `$ `
// block is the only place a running command's output shape is visible. Once
// the result lands, the collapsed view takes over.
//
// WHY THE HEADER ALSO READS THE PARTIAL STREAM
// While the call is still streaming, `toolCall.args` comes from
// `parseStreamingArgs`, whose fallback regex needs the *closing* quote of a
// value before it yields it — so `args.command` is undefined until the model
// has emitted the whole command. Reading it alone made the header sit on the
// bare `Bash` for as long as the argument took to arrive, which on a long
// one-liner is over a second. `extractPartialStringField` walks an
// unterminated JSON string and returns what has arrived so far, which is what
// Kimi's own `$ ` block always used — so the header now paints character by
// character from the first delta, and falls back to it only when the parsed
// argument is not there yet.
//
// ------------------------------------------------------------------ settings
//
// `bash_one_liner` — `on` rewrites the Bash branch (header + suppressed `$ `
//   preview). `off` keeps Kimi's "Ran a command" card.
// `tool_call_used` — `on` keeps Kimi's "Used"/"Using" verb on every tool
//   header. `off` drops it and the collapsed streaming preview body.
// Both default to Kimi's own behaviour; the pair `off`/`on` is the no-op.
// The defaults match lib/patch_settings.py.

const ON_OFF = ['on', 'off'];
const BASH = String(settings.get('bash_one_liner', 'off')).toLowerCase();
const USED = String(settings.get('tool_call_used', 'on')).toLowerCase();
if (!ON_OFF.includes(BASH)) {
  throw new Error(`bash_one_liner must be on or off - got "${BASH}"`);
}
if (!ON_OFF.includes(USED)) {
  throw new Error(`tool_call_used must be on or off - got "${USED}"`);
}

const wantBash = BASH === 'on';
const stripUsed = USED === 'off';
if (!wantBash && !stripUsed) {
  throw new Error('already patched');
}

const once = (anchor, what) => {
  const n = out.split(anchor).length - 1;
  if (n === 0) throw new Error(`${what} not found - the shape changed this release`);
  if (n !== 1) throw new Error(`${what} is not unique (${n}) - refusing to guess`);
};

let out = js;

if (wantBash) {
  // Own marker first — the verify pass re-applies to the installed bundle.
  if (out.includes('"Bash")}${argStr}${chipStr}')) {
    throw new Error('already patched');
  }

  // -------------------------------------------------------- 1. the header
  //
  // The Bash branch of buildHeader(). The `isTruncated` early-return stays:
  // a truncated call has no usable args, so it keeps its own warning shape.
  const HEADER_ANCHOR =
    '\t\t\tif (toolCall.name === "Bash") {\n' +
    '\t\t\t\tif (isTruncated) return `${bullet}${currentTheme.fg("error", "Truncated")} ${currentTheme.boldFg("primary", "Bash")}`;\n' +
    '\t\t\t\tconst label = isFinished ? "Ran a command" : "Running a command";\n' +
    '\t\t\t\tconst tone = isError ? "error" : "primary";\n' +
    '\t\t\t\tconst chipStr = isFinished && result !== void 0 ? this.buildHeaderChip(result) : "";\n' +
    '\t\t\t\treturn `${bullet}${currentTheme.boldFg(tone, label)}${chipStr}`;\n' +
    '\t\t\t}';

  const HEADER_REPLACEMENT =
    '\t\t\tif (toolCall.name === "Bash") {\n' +
    '\t\t\t\tif (isTruncated) return `${bullet}${currentTheme.fg("error", "Truncated")} ${currentTheme.boldFg("primary", "Bash")}`;\n' +
    '\t\t\t\tconst tone = isError ? "error" : "primary";\n' +
    '\t\t\t\tconst cmdStr = str(toolCall.args["command"])\n' +
    '\t\t\t\t\t|| extractPartialStringField(toolCall.streamingArguments ?? "", "command")\n' +
    '\t\t\t\t\t|| "";\n' +
    '\t\t\t\tconst firstLine = cmdStr.split("\\n")[0] ?? cmdStr;\n' +
    '\t\t\t\tconst argStr = firstLine ? currentTheme.dim(` ${cmdStr.includes("\\n") ? `${firstLine}…` : firstLine}`) : "";\n' +
    '\t\t\t\tconst chipStr = isFinished && result !== void 0 ? this.buildHeaderChip(result) : "";\n' +
    '\t\t\t\treturn `${bullet}${currentTheme.boldFg(tone, "Bash")}${argStr}${chipStr}`;\n' +
    '\t\t\t}';

  once(HEADER_ANCHOR, 'the Bash header branch');
  out = out.replace(HEADER_ANCHOR, () => HEADER_REPLACEMENT);

  // ----------------------------------------------------- 2. the $ preview
  const PREVIEW_ANCHOR =
    '\t\t\t} else if (name === "Bash") {\n' +
    '\t\t\t\tconst command = str(this.toolCall.args["command"]);\n' +
    '\t\t\t\tif (command.length === 0) return;';

  const PREVIEW_REPLACEMENT =
    '\t\t\t} else if (name === "Bash") {\n' +
    '\t\t\t\tconst command = str(this.toolCall.args["command"]);\n' +
    '\t\t\t\tif (command.length === 0) return;\n' +
    '\t\t\t\treturn;';

  once(PREVIEW_ANCHOR, 'the Bash call preview');
  out = out.replace(PREVIEW_ANCHOR, () => PREVIEW_REPLACEMENT);
}

if (stripUsed) {
  // Own marker first, same contract as above.
  if (out.includes('const verb = isTruncated ? "Truncated" : "";')) {
    throw new Error('already patched');
  }

  // ---------------------------------------------------- 3. no verb at all
  //
  // The generic path prefixes every header with "Used"/"Using" — `● Used Edit
  // (path) · +1`. The bullet already says it is a call and the chip says how
  // it ended, so the verb is a word the eye has to skip on every single line.
  // `Truncated` stays: it is the only state the header cannot otherwise
  // express.
  const VERB_ANCHOR =
    '\t\t\tconst verb = isFinished ? "Used" : isTruncated ? "Truncated" : "Using";\n';

  const VERB_REPLACEMENT =
    '\t\t\tconst verb = isTruncated ? "Truncated" : "";\n';

  once(VERB_ANCHOR, 'the tool call verb');
  out = out.replace(VERB_ANCHOR, () => VERB_REPLACEMENT);

  const VERB_USE_ANCHOR =
    '\t\t\treturn `${bullet}${verbStyled} ${toolLabel}${argStr}${chipStr}`;';

  const VERB_USE_REPLACEMENT =
    '\t\t\treturn verbStyled === ""\n' +
    '\t\t\t\t? `${bullet}${toolLabel}${argStr}${chipStr}`\n' +
    '\t\t\t\t: `${bullet}${verbStyled} ${toolLabel}${argStr}${chipStr}`;';

  once(VERB_USE_ANCHOR, 'the tool call header return');
  out = out.replace(VERB_USE_ANCHOR, () => VERB_USE_REPLACEMENT);

  // ------------------------------------------ 4. streaming, same treatment
  //
  // While a call is still streaming, `buildStreamingPreview` draws its own
  // body under the header — `Preparing changes…` for Edit, a `$ ` block for
  // Bash. With the verb gone the header already reads `● Edit (path)`, and
  // the body is one more line saying less. Collapsed, it goes; expanded
  // (ctrl+o) it stays, the way the finished call's preview stays.
  const STREAM_GUARD_ANCHOR =
    '\t\t\tif (name === "Write") {\n' +
    '\t\t\t\tconst content = extractPartialStringField(previewText, "content");';

  once(STREAM_GUARD_ANCHOR, 'the streaming preview');
  out = out.replace(STREAM_GUARD_ANCHOR, () =>
    '\t\t\tif (!this.expanded) return;\n' + STREAM_GUARD_ANCHOR);
}

return out;

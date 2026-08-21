// kimi-code-mods patch — give command output previews half the terminal height.
//
// Kimi caps every preview of command and tool output at a small fixed number of
// lines, chosen when the code was written rather than from the window you are
// actually looking at. On a tall terminal that wastes most of the screen:
//
//   PREVIEW_LINES      = 3    collapsed result preview (the main one)
//   RUNNING_TAIL_LINES = 5    live tail of a `!` shell command while it runs
//   MAX_PROGRESS_LINES = 24   live progress box of a running tool
//
// Each becomes `max(<today's value>, floor(rows / 2))`.
//
// WHY THE FLOOR IS THE OLD CONSTANT, NOT A NEW NUMBER
// The rewrite can then never be worse than stock: on a short terminal the old
// value wins, on a tall one you get half the screen. It also keeps the patched
// expression self-documenting — the original constant is still named in it.
//
// WHY THERE IS NO UPPER GUARD
// The Claude Code equivalent of this patch clamps to `rows - 3`, because there
// the suggestion popup is an absolutely positioned overlay: nothing in that
// render path clips, so a list taller than the space above the composer paints
// straight over the input box. Kimi's situation is different and I checked it
// rather than assuming — `overflow:"hidden"` does not occur anywhere in the
// bundle, but these previews are ordinary flow content inside the transcript,
// which the alt-screen renderer wraps in a ScrollView (`follow:"end"`,
// `overscroll:"chain"`). A tall card scrolls, it does not overpaint. And since
// half the height is by construction at most half the height, it can never
// approach the full window anyway, so `rows - 3` could never bind.
//
// WHY THE USE SITES AND NOT THE DEFINITIONS
// `PREVIEW_LINES = 3` is assigned once inside an esbuild `__esmMin` module
// initialiser, and `MAX_PROGRESS_LINES = 24` is a static class field. Rewriting
// either would freeze the height at whatever the window happened to be when the
// module loaded. Patched at the use sites, the expression is re-evaluated when
// the value is actually read, so it follows a window resize.
//
// Honest limitation: `TruncatedOutput` reads its budget in the constructor, so
// the two collapsed-preview sites adapt when a card is built — when the output
// arrives — not on every later repaint. The live sites (progress box, shell
// tail) are re-read per append and per render respectively.
//
// BOTH RENDERERS ARE COVERED BY ONE CHANGE
// Verified rather than assumed: `TuiAltScreen` and `TuiMainScreen` are
// referenced twelve times in the bundle, and not once inside
// `src/tui/components/messages/` or `tool-renderers/`. The message components
// are renderer-agnostic, so patching them reaches fullscreen and regular alike.
//
// Signature is fixed by the patch runner: (js) => string.

// pi-tui resolves the terminal height as
// `process.stdout.rows || Number(process.env["LINES"]) || 24`; the short form is
// enough here and needs no import at the use site.
const ROWS = '(process.stdout.rows||24)';
const half = (floorExpr) => `Math.max(${floorExpr},Math.floor(${ROWS}/2))`;

// Recognises our own output, so a second run is a no-op rather than a
// double-wrap. Checking the patched shape beats a marker comment: the shape is
// what actually has to be there.
const MARK = 'process.stdout.rows||24';

const edits = [
  {
    name: 'collapsed result preview (TruncatedOutput constructor)',
    // this.maxLines = options.maxLines ?? PREVIEW_LINES;
    find: /(this\.maxLines\s*=\s*([\w$]+)\.maxLines\s*\?\?\s*)(PREVIEW_LINES)/,
    build: (m) => m[1] + half(m[3]),
  },
  {
    name: 'shell result preview (addResultPreview call)',
    // ..., options.resultPreviewLines ?? PREVIEW_LINES, ...
    find: /(([\w$]+)\.resultPreviewLines\s*\?\?\s*)(PREVIEW_LINES)/,
    build: (m) => m[1] + half(m[3]),
  },
  {
    name: 'live tool output block (hard-coded override in tool-call.ts)',
    // this.addChild(new ShellExecutionComponent({ …, resultPreviewLines: 3, … }))
    //
    // This one is why the first version of this patch looked like it did
    // nothing on a running tool. `ShellExecutionComponent` falls back to
    // `PREVIEW_LINES` only when the option is absent — here it is passed
    // explicitly, so `??` never fires and the patched default is bypassed.
    // Anchored together with `tailOutput` so it cannot hit some other literal
    // three elsewhere in the file.
    find: /(resultPreviewLines:\s*)(\d+)(,\s*tailOutput:)/,
    build: (m) => m[1] + half(m[2]) + m[3],
  },
  {
    name: 'live progress box (appendProgress loop)',
    // while (this.progressLines.length > ToolCallComponent.MAX_PROGRESS_LINES)
    // Anchored on the `while` so the {@link ...} mention in the JSDoc above it
    // is left alone — that comment carries the same identifier.
    find: /(while\s*\(\s*this\.progressLines\.length\s*>\s*)([\w$]+\.MAX_PROGRESS_LINES)(\s*\))/,
    build: (m) => m[1] + half(m[2]) + m[3],
  },
  {
    name: 'live shell tail (running `!` command)',
    // const tail = lines.slice(-RUNNING_TAIL_LINES);
    // extra = Math.max(0, lines.length - RUNNING_TAIL_LINES);
    // Both readings must agree, otherwise the "+N lines" counter lies. One
    // local binding keeps them in step and evaluates the height once per frame.
    find: /(const\s+([\w$]+)\s*=\s*([\w$]+)\.slice\(-\s*RUNNING_TAIL_LINES\)\s*;\s*)([\w$]+)(\s*=\s*Math\.max\(0,\s*)([\w$]+)(\.length\s*-\s*)RUNNING_TAIL_LINES/,
    build: (m) =>
      `const __tkTail=${half('RUNNING_TAIL_LINES')};` +
      `const ${m[2]}=${m[3]}.slice(-__tkTail);` +
      `${m[4]}${m[5]}${m[6]}${m[7]}__tkTail`,
  },
];

let out = js;
const applied = [];
const missing = [];

for (const edit of edits) {
  const hits = out.match(new RegExp(edit.find.source, 'g'));
  if (!hits) {
    missing.push(edit.name);
    continue;
  }
  if (hits.length !== 1) {
    throw new Error(
      `${edit.name}: anchor is not unique (${hits.length} occurrences) — refusing to guess`
    );
  }
  const m = edit.find.exec(out);
  const replacement = edit.build(m);
  // A function, never a string: a `$` in minified output would otherwise be
  // read as a capture reference. This has bitten the tweakcc patches before.
  out = out.replace(edit.find, () => replacement);
  applied.push(edit.name);
}

if (applied.length === 0) {
  // Nothing matched. Either we already did this, or the shape moved.
  if (out.includes(MARK)) {
    throw new Error('already patched');
  }
  throw new Error(
    'no preview anchor found — the TUI message components changed shape in this release'
  );
}

if (missing.length > 0) {
  throw new Error(
    `patched ${applied.length} site(s) but could not find: ${missing.join(', ')} — ` +
      'partial application refused, the release changed shape'
  );
}

return out;

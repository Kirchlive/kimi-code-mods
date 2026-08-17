// Let a single Read return more of the file.
//
// Kimi caps one Read at 1000 lines, 100 KB, and 2000 characters per line,
// whichever it hits first. Claude Code's equivalent is 2000 lines, so the
// widespread belief that Kimi is the more generous of the two is backwards:
// on real source files the 1000-line cap is reached often, and every time it
// is, the model pays for another tool call, another round trip, and another
// copy of the surrounding context to ask for the rest.
//
//   READ_DESCRIPTION = renderPrompt(read_default, {
//     MAX_LINES: MAX_LINES$1,
//     MAX_BYTES_KB: MAX_BYTES / 1024,
//     MAX_LINE_LENGTH
//   });
//
// THE DESCRIPTION FOLLOWS BY ITSELF
// That is the whole reason this patch is three constants and nothing else.
// The tool description interpolates the same three values — "Returns up to
// ${MAX_LINES} lines or ${MAX_BYTES_KB} KB per call" — so raising them keeps
// what the model is told and what it gets in step, with no second edit and no
// chance of the two drifting apart.
//
// WHERE THEY LIVE, AND WHY THE ANCHOR IS THE WHOLE BLOCK
// All three sit together in the Read tool's own init block:
//
//   MAX_LINES$1 = 1e3;
//   MAX_LINE_LENGTH = 2e3;
//   MAX_BYTES = 100 * 1024;
//
// The bundler placed that block inside the region it labelled `grepTool.ts`,
// which is a fact about the bundle's layout and not about the constants —
// `init_read$1` is what actually owns them.
//
// They are replaced as one block rather than one at a time, because
// `MAX_LINE_LENGTH = 2e3;` also occurs as the tail of `DEFAULT_MAX_LINE_LENGTH
// = 2e3;` in the result builder. Matching it alone finds two places and one of
// them is a different setting entirely, which is exactly how this patch failed
// the first time it ran.
//
// WHAT IT COSTS
// The obvious thing: a Read that would have been truncated now spends the
// tokens instead. The cap is a budget, not a bug — raising it trades round
// trips for context. `moderate` doubles the line cap and leaves the byte cap
// alone, which is the setting that helps most often at the smallest cost,
// because source files hit the line cap long before the byte cap.
//
// ------------------------------------------------------------------ settings
//
// `read_limits` in patch-settings.conf:
//   default   Kimi's own 1000 lines / 100 KB / 2000 chars
//   moderate  2000 lines, 100 KB, 2000 chars
//   large     5000 lines, 512 KB, 4000 chars
// The default matches lib/patch_settings.py.

const MODE = String(settings.get('read_limits', 'default')).toLowerCase();

const PROFILES = {
  default: null,
  moderate: { lines: 2000, bytes: 100 * 1024, lineLength: 2000 },
  large: { lines: 5000, bytes: 512 * 1024, lineLength: 4000 },
};

if (!Object.prototype.hasOwnProperty.call(PROFILES, MODE)) {
  throw new Error(
    `read_limits must be one of ${Object.keys(PROFILES).join(', ')} - got "${MODE}"`);
}

const want = PROFILES[MODE];
if (want === null) {
  throw new Error('already patched');
}

// Kimi's own values, spelled the way the bundler wrote them. Matching the
// exact source form rather than a number is what keeps this patch from
// quietly re-patching an already-raised constant on a second run.
const ANCHOR = 'MAX_LINES$1 = 1e3;\n'
  + '\tMAX_LINE_LENGTH = 2e3;\n'
  + '\tMAX_BYTES = 100 * 1024;';

const REPLACEMENT = `MAX_LINES$1 = ${want.lines};\n`
  + `\tMAX_LINE_LENGTH = ${want.lineLength};\n`
  + `\tMAX_BYTES = ${want.bytes};`;

if (js.includes(REPLACEMENT)) {
  throw new Error('already patched');
}

const n = js.split(ANCHOR).length - 1;
if (n === 0) {
  throw new Error('the Read tool\'s limit block not found - either the shape changed '
    + 'this release, or the constants were already changed to values this patch '
    + 'does not know');
}
if (n !== 1) {
  throw new Error(`the Read tool's limit block is not unique (${n}) - refusing to guess`);
}

return js.replace(ANCHOR, () => REPLACEMENT);

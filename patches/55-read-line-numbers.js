// Drop the line-number prefix from what the Read tool hands the model.
//
// Kimi prefixes every line it returns with its number and a tab, the same
// shape `cat -n` produces:
//
//   function renderLine(entry, lineEndingStyle) {
//     const modelContent = …;
//     const truncated = truncateLine(modelContent, MAX_LINE_LENGTH);
//     const renderedContent = lineEndingStyle === "mixed" ? … : truncated;
//     return { line: `${String(entry.lineNo)}\t${renderedContent}`, … };
//   }
//
// That prefix is paid for on every line of every file read, for the whole
// conversation, which makes it the one saving here that recurs per turn rather
// than once per session. It is also the one with a real cost of its own, so
// the trade is worth stating rather than burying:
//
// WHAT YOU LOSE
// The model can no longer cite a line number from a Read alone, and anything
// that asks it to ("what is on line 40") gets a worse answer. Edits are
// unaffected — Kimi's Edit matches on text, not on line numbers — and so is
// Grep, which prints its own numbers and is untouched by this patch.
//
// WHY THE DESCRIPTION IS REWRITTEN TOO
// The tool description states the output format literally:
//
//   - Output format: `<line-number>\t<content>` per line.
//
// Leaving that in place while removing the numbers would be worse than doing
// nothing: the model would be told to expect a column that is not there, and
// would reasonably conclude the file starts at whatever the first token looks
// like. Behaviour and description move together or not at all.
//
// WHICH COPY
// Kimi ships two engine generations and both contain a `renderLine`. Only
// `agent-core-v2` is live, and the two are told apart by their minified
// suffixes: the dead copy calls `truncateLine$1(modelContent, MAX_LINE_LENGTH$1)`.
// Anchoring on the unsuffixed names is what keeps this patch off the inert
// generation, where it would have looked applied and changed nothing.
//
// ------------------------------------------------------------------ settings
//
// `read_line_numbers` in patch-settings.conf: `on` keeps Kimi's numbering,
// `off` removes it. The default matches lib/patch_settings.py.

const MODE = String(settings.get('read_line_numbers', 'on')).toLowerCase();

if (!['on', 'off'].includes(MODE)) {
  throw new Error(`read_line_numbers must be on or off - got "${MODE}"`);
}

if (MODE === 'on') {
  throw new Error('already patched');
}

// ------------------------------------------------------------- 1. the format

const ANCHOR =
  'const truncated = truncateLine(modelContent, MAX_LINE_LENGTH);\n'
  + '\tconst renderedContent = lineEndingStyle === "mixed" ? makeCarriageReturnsVisible(truncated) : truncated;\n'
  + '\treturn {\n'
  + '\t\tline: `${String(entry.lineNo)}\\t${renderedContent}`,';

const REPLACEMENT =
  'const truncated = truncateLine(modelContent, MAX_LINE_LENGTH);\n'
  + '\tconst renderedContent = lineEndingStyle === "mixed" ? makeCarriageReturnsVisible(truncated) : truncated;\n'
  + '\treturn {\n'
  + '\t\tline: renderedContent,';

if (js.includes(REPLACEMENT)) {
  throw new Error('already patched');
}

const count = js.split(ANCHOR).length - 1;
if (count === 0) {
  throw new Error('renderLine not found in agent-core-v2 - the shape changed this release');
}
if (count !== 1) {
  throw new Error(`renderLine anchor is not unique (${count}) - refusing to guess`);
}

let out = js.replace(ANCHOR, () => REPLACEMENT);

// ---------------------------------------------------- 2. what the model reads

// The sentence exists once per engine generation. Both are rewritten: the
// inert copy costs nothing to correct, and leaving one of them behind would
// mean the next reader has to work out which is which all over again.
//
// The doubled backslash is not a typo. The prompt is a markdown file baked
// into a JavaScript string literal, so the `\t` its author wrote is stored as
// an escaped backslash followed by `t`. Matching a single backslash here finds
// nothing, which is exactly how this patch failed the first time it ran.
const SAYS = '- Output format: `<line-number>\\\\t<content>` per line.';
const SAYS_NOW = '- Output format: the file\'s lines exactly as they are, one per line, '
  + 'with no line numbers.';

const said = out.split(SAYS).length - 1;
if (said === 0) {
  throw new Error('the Read description no longer states its output format - '
    + 'refusing to remove the numbers while the prompt still promises them');
}
out = out.split(SAYS).join(SAYS_NOW);

return out;

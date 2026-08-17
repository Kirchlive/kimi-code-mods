// Restyle or remove the box drawn around the composer at the bottom of the
// screen.
//
// WHO DRAWS WHAT — the finding this patch is built on
// The frame is not one thing. pi-tui renders the editor with its own top and
// bottom border, and those are *whole rows of their own*: a row whose first
// visible character is `─`, spanning the full width. Kimi then post-processes
// that output in `wrapWithSideBorders` (bundled from
// `src/tui/components/editor/custom-editor.ts`), which turns those dash rows
// into `╭…╮` and `╰…╯` and overlays a `│` onto column 0 and the last column of
// every content row — and only where those columns are literal spaces, so the
// inverse cursor at the right edge survives.
//
// That answers the question `off` depends on: the horizontal rules occupy two
// rows that exist whether or not a border is drawn, and the vertical bars sit
// on padding columns the editor has reserved either way. Deleting the rows
// would make the composer two rows shorter than every width and height
// calculation around it expects. So `off` does not delete anything — it
// replaces each box-drawing character with a space. The layout is identical to
// the pixel, and the box is simply not there any more.
//
// HOW, AND WHY IT IS THIS SMALL
// Every border character in that function goes through the `paint` callback
// the caller supplies (`(s) => this.borderColor(s)`), and nothing else does:
// the editor's content is spliced in around those calls, never through them.
// So this patch does not rewrite the function. It renames it, puts a new
// `wrapWithSideBorders` in front, and that wrapper hands the original a
// `paint` that substitutes the characters on the way past.
//
// The alternative — mapping the characters on the function's *output* —
// would have hit box-drawing characters the user typed into the composer.
// Going through `paint` is what keeps the substitution to the frame.
//
// One consequence worth knowing: the `! shell mode` badge is passed in as
// `options.label` and is not painted, so it survives every mode including
// `off`. The scroll indicators (`── ↑ 3 more ──`) are painted, so with `off`
// their dashes turn to spaces and the `↑ 3 more` remains — the information
// stays, the rule around it goes.
//
// WHAT IS NOT OFFERED
// No `round`. The shipped frame already is the round one, which is what
// `default` leaves alone.
//
// ------------------------------------------------------------------ settings
//
// `input_box_border` — `default` (Kimi's rounded box) | `off` | `single` |
// `double` | `bold`.

const MODE = String(settings.get('input_box_border', 'default')).toLowerCase();

const BLANK = ' ';
const SWAPS = {
  off:    { '╭': BLANK, '╮': BLANK, '╰': BLANK, '╯': BLANK, '├': BLANK, '┤': BLANK, '─': BLANK, '│': BLANK },
  single: { '╭': '┌', '╮': '┐', '╰': '└', '╯': '┘' },
  double: { '╭': '╔', '╮': '╗', '╰': '╚', '╯': '╝', '├': '╠', '┤': '╣', '─': '═', '│': '║' },
  bold:   { '╭': '┏', '╮': '┓', '╰': '┗', '╯': '┛', '├': '┣', '┤': '┫', '─': '━', '│': '┃' },
};

if (MODE === 'default') {
  throw new Error('already patched');
}
if (SWAPS[MODE] === undefined) {
  throw new Error(`input_box_border must be one of default, ${Object.keys(SWAPS).join(', ')}`
    + ` - got "${MODE}"`);
}

// The original keeps its body and only loses its name; the wrapper takes the
// name over. Function declarations are hoisted, so the order they appear in
// does not matter, and the single call site keeps calling `wrapWithSideBorders`
// without knowing anything changed.
const ANCHOR = 'function wrapWithSideBorders(lines, paint, options = {}) {\n'
  + '\tlet seenTop = false;';

const REPLACEMENT = 'function wrapWithSideBorders(lines, paint, options = {}) {\n'
  + '\tconst swap = ' + JSON.stringify(SWAPS[MODE]) + ';\n'
  // A function is passed to `replace`, so a `$` in a border character could
  // never be read as a back-reference — and the fallback keeps every character
  // this mode does not rename, which is how `single` gets away with four
  // entries instead of eight.
  + '\treturn wrapWithSideBordersUnstyled(lines, (s) => paint(s.replace(/[╭╮╰╯├┤─│]/g,'
  + ' (ch) => swap[ch] ?? ch)), options);\n'
  + '}\n'
  + 'function wrapWithSideBordersUnstyled(lines, paint, options = {}) {\n'
  + '\tlet seenTop = false;';

if (js.includes('function wrapWithSideBordersUnstyled')) {
  throw new Error('already patched');
}

const count = js.split(ANCHOR).length - 1;
if (count === 0) {
  throw new Error('wrapWithSideBorders not found - the shape changed this release');
}
if (count !== 1) {
  throw new Error(`wrapWithSideBorders is not unique (${count}) - refusing to guess`);
}

return js.replace(ANCHOR, () => REPLACEMENT);

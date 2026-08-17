// Give the user's own messages in the transcript a marker, a frame and a text
// style of your choosing.
//
// The whole component is `src/tui/components/messages/user-message.ts` and it
// ships unminified, so the three things this patch touches are readable in the
// bundle exactly as they are here:
//
//   const marker = this.bullet ?? "✨ ";
//   const bullet = marker.length > 0 ? currentTheme.boldFg("roleUser", marker) : "";
//   const bulletWidth = visibleWidth(bullet);
//   const contentWidth = Math.max(1, safeWidth - bulletWidth);
//   const lines = [];
//   for (const line of this.spacerComponent.render(safeWidth)) lines.push(line);
//   const textLines = new Text(currentTheme.boldFg("roleUser", this.text), 0, 0).render(contentWidth);
//   …
//   const rendered = markOsc133Zone(lines.map((line) => truncateToWidth(line, safeWidth, "…")));
//   if (isRenderCacheEnabled()) this.renderCache = { width: safeWidth, lines: rendered };
//
// THE MARKER IS A DEFAULT, NOT A CONSTANT
// `this.bullet` is a per-entry value: the shell mode passes its own marker when
// it builds the component, and a replayed turn may pass none. Only the `??`
// fallback is rewritten, so an entry that brought its own marker keeps it. That
// is the difference between changing your prompt symbol and flattening every
// message in the transcript to look the same.
//
// WHY THE FRAME IS DRAWN BEFORE THE TRUNCATION, NOT AFTER
// The last thing `render` does is push every line through
// `truncateToWidth(line, safeWidth, "…")` and then store the result in
// `this.renderCache`. A frame added after that point would be cut off at the
// right edge on the first line that reaches full width, and a frame added
// after the cache assignment would only ever be seen on a re-render. The
// injected block therefore sits immediately before both, and the content width
// is reduced by the four columns the frame occupies (`│ ` and ` │`) so that a
// framed line is exactly `safeWidth` wide and the truncation is a no-op rather
// than a mutilation. `topbottom` draws rules only, costs no columns, and so
// leaves the content width alone.
//
// Two lines are deliberately left out of the frame. The spacer line that
// separates one message from the next stays outside it — it is the gap between
// messages, not part of this one — and image thumbnails are passed through
// untouched, because they are terminal graphics escapes whose visible width is
// not a column count that padding may be appended to.
//
// Below eight columns nothing is framed at all. A frame needs four columns
// before the first character of text appears, and a terminal that narrow is
// better off with an unframed message than with a box and no content.
//
// WHY `underline` IS OFFERED AND `inverse` IS NOT
// `Theme` in `src/tui/theme/theme.ts` exposes `fg`, `boldFg`, `dimFg`,
// `italicFg`, `underlineFg` and `strikethroughFg` — each a `chalk` call on the
// palette colour. `underline` maps onto one of them and needs no hand-written
// SGR. There is no inverse variant there, and writing the escape by hand would
// mean owning a colour reset that the theme currently owns, so that value does
// not exist.
//
// The style applies to the message text only; the marker stays bold. The marker
// is a marker whether or not the text next to it is dimmed, and keeping it out
// of the switch means one anchor instead of two.
//
// ------------------------------------------------------------------ settings
//
// `user_message_marker` — `default` keeps Kimi's `✨ `, `none` removes the
//   marker (and the indent that follows it), anything else is used literally,
//   including a trailing space if you want one: `user_message_marker=▌ `.
//   This one is free text, so the menu can offer it but cannot cycle it.
//
// `user_message_border` — `off` | `round` | `single` | `double` | `bold` |
//   `topbottom`. `topbottom` draws a rule above and below and no sides.
//
// `user_message_style` — `default` (bold, as Kimi ships it) | `plain` |
//   `italic` | `dim` | `underline`.
//
// Setting all three to their defaults makes this patch a no-op.

const MARKER = String(settings.get('user_message_marker', 'default'));
const BORDER = String(settings.get('user_message_border', 'off')).toLowerCase();
const STYLE = String(settings.get('user_message_style', 'default')).toLowerCase();

const FRAMES = {
  round:     { tl: '╭', tr: '╮', bl: '╰', br: '╯', h: '─', v: '│' },
  single:    { tl: '┌', tr: '┐', bl: '└', br: '┘', h: '─', v: '│' },
  double:    { tl: '╔', tr: '╗', bl: '╚', br: '╝', h: '═', v: '║' },
  bold:      { tl: '┏', tr: '┓', bl: '┗', br: '┛', h: '━', v: '┃' },
  topbottom: { tl: '',  tr: '',  bl: '',  br: '',  h: '─', v: ''  },
};

const STYLES = {
  default:   'boldFg',
  plain:     'fg',
  italic:    'italicFg',
  dim:       'dimFg',
  underline: 'underlineFg',
};

if (BORDER !== 'off' && FRAMES[BORDER] === undefined) {
  throw new Error(`user_message_border must be one of off, ${Object.keys(FRAMES).join(', ')}`
    + ` - got "${BORDER}"`);
}
if (STYLES[STYLE] === undefined) {
  throw new Error(`user_message_style must be one of ${Object.keys(STYLES).join(', ')}`
    + ` - got "${STYLE}"`);
}

// `✨ ` counts as the default here, so that spelling out the marker Kimi
// already uses does not turn into a patch that changes nothing.
const WANTS_MARKER = MARKER !== 'default' && MARKER !== '✨ ';

if (!WANTS_MARKER && BORDER === 'off' && STYLE === 'default') {
  throw new Error('already patched');
}

// Every anchor below is checked the same way: the shape has to be there exactly
// once, or the patch refuses rather than guessing which occurrence was meant.
const once = (haystack, anchor, what) => {
  const n = haystack.split(anchor).length - 1;
  if (n === 0) throw new Error(`${what} not found - the shape changed this release`);
  if (n !== 1) throw new Error(`${what} is not unique (${n}) - refusing to guess`);
};

let out = js;

// ------------------------------------------------------------------ 1. marker

if (WANTS_MARKER) {
  const ANCHOR = 'const marker = this.bullet ?? "✨ ";';
  const REPLACEMENT = 'const marker = this.bullet ?? '
    + JSON.stringify(MARKER === 'none' ? '' : MARKER) + ';';

  if (out.includes(REPLACEMENT)) throw new Error('already patched');
  once(out, ANCHOR, 'the user message marker');
  out = out.replace(ANCHOR, () => REPLACEMENT);
}

// ------------------------------------------------------------------- 2. style

if (STYLE !== 'default') {
  const ANCHOR = 'currentTheme.boldFg("roleUser", this.text)';
  const REPLACEMENT = `currentTheme.${STYLES[STYLE]}("roleUser", this.text)`;

  if (out.includes(REPLACEMENT)) throw new Error('already patched');
  once(out, ANCHOR, 'the user message text style');
  out = out.replace(ANCHOR, () => REPLACEMENT);
}

// ------------------------------------------------------------------ 3. border

if (BORDER !== 'off') {
  const F = FRAMES[BORDER];
  const PAD = F.v === '' ? 0 : 4;

  // The line that decides how wide the text may be. `const contentWidth = …`
  // alone appears twice in the bundle, so the two lines above it come along to
  // make the anchor unambiguous. `topbottom` costs no columns and leaves this
  // line alone entirely.
  //
  // The `safeWidth >= 8` test is the same one the frame itself is drawn under,
  // and it has to be repeated here: a terminal too narrow for a frame must not
  // pay for one by wrapping its text four columns early.
  const WIDTH_ANCHOR =
    'const bullet = marker.length > 0 ? currentTheme.boldFg("roleUser", marker) : "";\n'
    + '\t\t\tconst bulletWidth = visibleWidth(bullet);\n'
    + '\t\t\tconst contentWidth = Math.max(1, safeWidth - bulletWidth);';
  const WIDTH_REPLACEMENT = WIDTH_ANCHOR.replace(
    'Math.max(1, safeWidth - bulletWidth);',
    `Math.max(1, safeWidth - bulletWidth - (safeWidth >= 8 ? ${PAD} : 0));`);

  // The last step before the truncation and the render cache.
  const FRAME_ANCHOR = 'const rendered = markOsc133Zone(lines.map((line) => {';

  const FRAME = 'if (safeWidth >= 8) {\n'
    + '\t\t\t\tconst frame = ' + JSON.stringify(F) + ';\n'
    + '\t\t\t\tconst paint = (s) => currentTheme.fg("roleUser", s);\n'
    + '\t\t\t\tconst inner = safeWidth - (frame.v === "" ? 0 : 2);\n'
    // The spacer is asked for its own height rather than assumed to be one
    // line: it is a `new Spacer(1)` today, and `render` only fills an array.
    + '\t\t\t\tconst body = lines.splice(this.spacerComponent.render(safeWidth).length);\n'
    + '\t\t\t\tlines.push(paint(frame.tl + frame.h.repeat(inner) + frame.tr));\n'
    + '\t\t\t\tfor (const bodyLine of body) {\n'
    + '\t\t\t\t\tif (frame.v === "" || isImageLine(bodyLine)) {\n'
    + '\t\t\t\t\t\tlines.push(bodyLine);\n'
    + '\t\t\t\t\t\tcontinue;\n'
    + '\t\t\t\t\t}\n'
    + '\t\t\t\t\tconst fill = " ".repeat(Math.max(0, inner - 2 - visibleWidth(bodyLine)));\n'
    + '\t\t\t\t\tlines.push(paint(frame.v) + " " + bodyLine + fill + " " + paint(frame.v));\n'
    + '\t\t\t\t}\n'
    + '\t\t\t\tlines.push(paint(frame.bl + frame.h.repeat(inner) + frame.br));\n'
    + '\t\t\t}\n'
    + '\t\t\t';

  if (out.includes(FRAME)) throw new Error('already patched');
  once(out, FRAME_ANCHOR, 'the user message render step');

  if (PAD > 0) {
    once(out, WIDTH_ANCHOR, 'the user message content width');
    out = out.replace(WIDTH_ANCHOR, () => WIDTH_REPLACEMENT);
  }
  out = out.replace(FRAME_ANCHOR, () => FRAME + FRAME_ANCHOR);
}

return out;

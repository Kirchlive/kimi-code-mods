// The welcome banner: whose name it carries, and the horns on the logo.
//
// `renderWelcomeHeader` builds the box you see at startup out of three pieces:
//
//   const logo = ["▐█▛█▛█▌", "▐█████▌"];
//   ...chalk.bold.hex(currentTheme.palette.primary)("Welcome to Kimi Code!")
//
// The greeting appears three times — in the narrow fallback for a window under
// 24 columns, in the boxed layout, and in the rainbow one `/dance` switches to
// — and all three are replaced, so the name changes with neither the width of
// the terminal nor the mood it is in.
//
// THE HORNS
// A horn needs to rise above the head, and the renderer draws exactly two
// rows — `renderedHeaderLines` indexes `logo[0]` and `logo[1]` and nothing
// else, so a third entry would be built and thrown away. Both the array and
// that line are therefore patched: the array gains a row of tips, and the
// renderer is taught to put it on top.
//
// Triangles, because quarter blocks gave antennae rather than horns: two dots
// floating above the head read as something to receive with, not something to
// gore with. A triangle has a diagonal edge, and the diagonal is the horn.
//
//     ◢       ◣
//     ◥██▛█▛██◤
//      ▐█████▌
//
// Bottom to top on the left: `◥` fills the upper right of its cell and meets
// the head; `◢` above it fills the lower right, so the two diagonals line up
// into one edge running up and out. The right horn is the same pair mirrored.
// The head's top row gains full blocks at the corners so the horns have
// something square to grow out of; the bottom row keeps Kimi's half blocks.
//
// ON WIDTH
// The triangles are East Asian Ambiguous, which usually argues against them —
// a terminal that renders them double-width would push the text beside them
// out of line. Kimi's own logo already ends in `▌`, which is ambiguous too, so
// any terminal that draws this banner correctly today is already treating that
// class as one column. The triangles ride along on that.
//
// The second row is padded to the same width so the head stays under its own
// horns; `logoWidth` is computed from the rows themselves, so the box grows
// with them and needs no second edit.
//
// The logo is drawn with `primary(...)`, which is the theme's own colour —
// pick the `Kimi-Code-Mods` theme and it comes out in the project's red
// without this patch knowing anything about colour.
//
// ------------------------------------------------------------------ settings
//
// `welcome_banner` in patch-settings.conf: `on` | `off`. `off` is a no-op and
// leaves Kimi's own greeting and logo alone.

const ON = String(settings.get('welcome_banner', 'on')).toLowerCase();

if (!['on', 'off'].includes(ON)) {
  throw new Error(`welcome_banner must be on or off - got "${ON}"`);
}
if (ON === 'off') {
  throw new Error('already patched');
}

const GREETING = 'Welcome to Kimi Code!';
const GREETING_NEW = 'Welcome to Kimi Code Mods!';
const LOGO = '["▐█▛█▛█▌", "▐█████▌"]';
const LOGO_NEW = '["◥██▛█▛██◤", " ▐█████▌ ", "◢       ◣"]';

// The renderer draws two rows and stops. A third entry in the array is simply
// never read, so the row carrying the horn tips has to be spliced in here.
const ROWS = 'let renderedHeaderLines = [primary(logo[0].padEnd(logoWidth)) + gap '
  + '+ rightRow0, primary(logo[1].padEnd(logoWidth)) + gap + rightRow1];';
const ROWS_NEW = 'let renderedHeaderLines = [...(logo[2] ? [primary(logo[2])] : []), '
  + 'primary(logo[0].padEnd(logoWidth)) + gap + rightRow0, '
  + 'primary(logo[1].padEnd(logoWidth)) + gap + rightRow1];';

if (js.includes(GREETING_NEW) && js.includes(LOGO_NEW) && js.includes(ROWS_NEW)) {
  throw new Error('already patched');
}

let out = js;

// All three occurrences, counted first: a release that adds or drops one has
// moved something worth looking at, and a half-renamed banner is worse than a
// run that stops and says so.
const greetings = out.split(GREETING).length - 1;
if (greetings === 0) {
  throw new Error('the welcome greeting is gone - it changed this release');
}
if (greetings !== 3) {
  throw new Error(`expected 3 welcome greetings, found ${greetings} - refusing to guess`);
}
out = out.split(GREETING).join(GREETING_NEW);

// The logo array, spelled exactly as the bundle's formatter emits it. It is
// there twice — once for the startup box, once for the `/web` notice — and
// both get the horns, so the two do not end up wearing different heads. A
// count that is neither means the shape moved, which is worth a failure rather
// than a banner half this project's and half Kimi's.
const logos = out.split(LOGO).length - 1;
if (logos === 0) {
  throw new Error('the welcome logo is gone - it changed this release');
}
if (logos !== 2) {
  throw new Error(`expected 2 welcome logos, found ${logos} - refusing to guess`);
}

out = out.split(LOGO).join(LOGO_NEW);

// The extra row, spliced into the startup renderer only. `/web` reads logo[0]
// and logo[1] by name and would ignore a third entry anyway, so there the
// horns show as the side stubs and nothing is out of place.
const rows = out.split(ROWS).length - 1;
if (rows === 0) {
  throw new Error('the header rows moved - the renderer changed this release');
}
if (rows !== 1) {
  throw new Error(`the header rows are not unique (${rows}) - refusing to guess`);
}

return out.replace(ROWS, () => ROWS_NEW);

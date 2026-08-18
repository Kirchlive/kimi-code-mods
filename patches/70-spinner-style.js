// Swap the characters the spinner cycles through, and optionally its speed.
//
// Kimi keeps both spinner alphabets as plain array literals in
// `src/tui/constant/rendering.ts`:
//
//   BRAILLE_SPINNER_FRAMES = ["⠋", "⠙", "⠹", …];
//   MOON_SPINNER_FRAMES    = ["🌑", "🌒", "🌓", …];
//
// and `MoonLoader` (src/tui/components/chrome/moon-loader.ts) copies one of the
// two into the instance when it is constructed:
//
//   this.frames   = style === "moon" ? [...MOON_SPINNER_FRAMES] : [...BRAILLE_SPINNER_FRAMES];
//   this.interval = style === "moon" ? 120 : 80;
//
// The arrays are therefore the whole surface: nothing else in the TUI holds a
// spinner frame, and `start()` walks `this.frames` modulo its length, so an
// array of any size works.
//
// WHY BOTH ARRAYS ARE OVERWRITTEN
// The user never picks `style`; the call site does. `waiting` and `tool` ask
// for "moon", `composing` asks for "braille", and `ThinkingComponent` indexes
// `BRAILLE_SPINNER_FRAMES` directly with its own frame counter. A setting that
// rewrote only one array would change the spinner while a tool runs and leave
// it alone while the model composes — a style that appears and disappears
// depending on what Kimi happens to be doing. Both arrays get the chosen
// frames, so the choice is what the user actually sees, everywhere.
//
// `mirror` is the exception and the reason the literals are read rather than
// assumed: it appends each array's own reverse to itself, so the spinner swings
// back instead of jumping from the last frame to the first. That is tweakcc's
// `reverseMirror`, and it is the one option whose result depends on what Kimi
// shipped this release.
//
// WHAT IT COSTS
// The moon frames are double-width emoji and the rest are single-width, so a
// terminal that measures them badly will wobble the line by a column — that is
// pre-existing for Kimi's own moon spinner and this patch does not fix it, it
// only lets you avoid it by choosing a single-width set.
//
// `spinner_interval_ms` reaches `MoonLoader` only. `ThinkingComponent` runs its
// own `setInterval(…, 80)` for the inline "thinking" spinner and is left alone:
// that timer also drives the component's re-render, so slowing it down would
// slow the thinking text with it.
//
// ------------------------------------------------------------------ settings
//
// `spinner_style` in patch-settings.conf:
//   default  Kimi's own frames, untouched
//   braille  ⠋⠙⠹… everywhere, including where the moon spinner used to be
//   dots     ⣾⣽⣻… a heavier braille cycle
//   moon     🌑🌒🌓… everywhere, including the composing spinner
//   blocks   ▏▎▍… a bar that fills and restarts
//   wave     ▁▃▄▅▆▇█ a column that grows
//   glow     ░▒▓█ four densities
//   colors   🔴🟠🟡🟢🔵🟣 double-width, like the moon set
//   arc      ◜◠◝◞◡◟ a ring drawn in quarters
//   star     ·✢✳✶✻✽ the shape Claude Code uses
//   custom   the frames in `spinner_frames`
//
// `spinner_mirror` runs whichever frames were chosen forwards and then
// backwards, so the spinner swings instead of jumping from the last frame to
// the first. It used to be a *style* of its own, which meant it could only
// ever mirror Kimi's own frames — choosing it and choosing a preset were the
// same decision, and you could not have both. As a switch it applies to every
// style, including your own frames.
//
// `spinner_frames` is only read by `custom`. Frames are separated by spaces
// where there are any, and taken one code point at a time where there are not
// — so `⠋ ⠙ ⠹` and `⠋⠙⠹` mean the same thing, and a frame made of several code
// points (a flag, an emoji with a modifier) is still expressible by separating
// with spaces. Fewer than two frames is refused: a spinner that never changes
// is a character, and there are quieter ways to draw one.
//
// `spinner_interval_ms`: `default` keeps 120 ms for moon and 80 ms for braille,
// or a number from 20 to 2000 that both styles then use. A value outside that
// range is an error, not a silent fallback — a spinner ticking every 5 ms burns
// a core for nothing and one ticking every minute looks frozen. The defaults
// match lib/patch_settings.py, which registers both keys.

const STYLE = String(settings.get('spinner_style', 'default')).toLowerCase();
const RATE = String(settings.get('spinner_interval_ms', 'default')).toLowerCase();
const FRAMES_SETTING = String(settings.get('spinner_frames', 'default'));
const MIRROR = String(settings.get('spinner_mirror', 'off')).toLowerCase();

if (!['on', 'off'].includes(MIRROR)) {
  throw new Error(`spinner_mirror must be on or off - got "${MIRROR}"`);
}

const PRESETS = {
  braille: ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'],
  dots: ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷'],
  moon: ['🌑', '🌒', '🌓', '🌔', '🌕', '🌖', '🌗', '🌘'],
  blocks: ['▏', '▎', '▍', '▌', '▋', '▊', '▉', '█'],
  wave: ['▁', '▃', '▄', '▅', '▆', '▇', '█', '▇', '▆', '▅', '▄', '▃'],
  glow: ['░', '▒', '▓', '█', '▓', '▒'],
  colors: ['🔴', '🟠', '🟡', '🟢', '🔵', '🟣'],
  arc: ['◜', '◠', '◝', '◞', '◡', '◟'],
  star: ['·', '✢', '✳', '✶', '✻', '✽'],
};

// Exported for the menu, which draws each preset next to its name so the
// choice is made by looking rather than by reading a word. Kept as one table
// here so the two cannot drift: a preset the menu offers and the patch does
// not know would be a row that fails when it is applied.
function kimiModsSpinnerFrames(setting) {
  const raw = String(setting);
  const parts = raw.trim().split(/\s+/).filter(Boolean);
  return parts.length > 1 ? parts : Array.from(raw.trim());
}

const CHOICES = ['default', 'custom'].concat(Object.keys(PRESETS));
if (!CHOICES.includes(STYLE)) {
  throw new Error(`spinner_style must be one of ${CHOICES.join(', ')} - got "${STYLE}"`);
}

let custom = null;
if (STYLE === 'custom') {
  if (FRAMES_SETTING === 'default' || !FRAMES_SETTING.trim()) {
    throw new Error('spinner_style is custom but spinner_frames is empty - '
      + 'set the frames, or pick a preset');
  }
  custom = kimiModsSpinnerFrames(FRAMES_SETTING);
  if (custom.length < 2) {
    throw new Error(`spinner_frames needs at least two frames - got ${custom.length}`);
  }
}

let ms = null;
if (RATE !== 'default') {
  if (!/^\d+$/.test(RATE)) {
    throw new Error(`spinner_interval_ms must be default or a number - got "${RATE}"`);
  }
  ms = Number(RATE);
  if (ms < 20 || ms > 2000) {
    throw new Error(`spinner_interval_ms must be between 20 and 2000 - got ${ms}`);
  }
}

if (STYLE === 'default' && ms === null && MIRROR === 'off') {
  throw new Error('already patched');
}

let out = js;

// ------------------------------------------------------------- 1. the frames

// The literal is located rather than spelled out, because `mirror` needs to
// know what is in it. Bounded on both ends: the assignment opens the array and
// the first `\n\t];` after it closes the array, which is what the bundle's
// formatter emits for a multi-line literal. Anything else in between and the
// JSON parse below refuses the file instead of guessing.
function readFrames(name) {
  const HEAD = `\t${name} = [`;
  const hits = out.split(HEAD).length - 1;
  if (hits === 0) {
    throw new Error(`${name} not found - the shape changed this release`);
  }
  if (hits !== 1) {
    throw new Error(`${name} is not unique (${hits}) - refusing to guess`);
  }
  const at = out.indexOf(HEAD);
  const close = out.indexOf('\n\t];', at);
  if (close < 0) {
    throw new Error(`${name} is no longer a plain array literal - refusing to guess`);
  }
  let list;
  try {
    list = JSON.parse('[' + out.slice(at + HEAD.length, close) + ']');
  } catch {
    throw new Error(`${name} holds something other than string literals - refusing to guess`);
  }
  if (!list.length || !list.every(f => typeof f === 'string')) {
    throw new Error(`${name} holds something other than string literals - refusing to guess`);
  }
  return { text: out.slice(at, close + 4), list, name };
}

function writeFrames(name, list) {
  return `\t${name} = [\n` + list.map(f => '\t\t' + JSON.stringify(f)).join(',\n') + '\n\t];';
}

// A mirrored array is a palindrome of even length, and neither of Kimi's two is
// one. That is what tells a second run apart from a first: without it `mirror`
// would happily mirror its own output and double the frame count on every
// application, which the runner's idempotency check would catch only after the
// spinner had already grown to forty frames.
const isMirrored = list =>
  list.length % 2 === 0 && list.every((f, i) => f === list[list.length - 1 - i]);

for (const name of ['BRAILLE_SPINNER_FRAMES', 'MOON_SPINNER_FRAMES']) {
  if (STYLE === 'default' && MIRROR === 'off') break;
  const found = readFrames(name);
  const chosen = STYLE === 'default' ? found.list
    : (STYLE === 'custom' ? custom : PRESETS[STYLE]);
  const wanted = MIRROR === 'on' && !isMirrored(chosen)
    ? chosen.concat([...chosen].reverse())
    : chosen;
  const replacement = writeFrames(name, wanted);
  if (replacement === found.text) continue;
  out = out.replace(found.text, () => replacement);
}

// ------------------------------------------------------------- 2. the speed

if (ms !== null) {
  const DONE = `this.interval = ${ms};`;
  if (!out.includes(DONE)) {
    const ANCHOR = 'this.interval = style === "moon" ? 120 : 80;';
    const hits = out.split(ANCHOR).length - 1;
    if (hits === 0) {
      throw new Error('the MoonLoader interval not found - the shape changed this release');
    }
    if (hits !== 1) {
      throw new Error(`the MoonLoader interval is not unique (${hits}) - refusing to guess`);
    }
    out = out.replace(ANCHOR, () => DONE);
  }
}

if (out === js) {
  throw new Error('already patched');
}

return out;

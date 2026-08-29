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
const MIRROR = String(settings.get('spinner_mirror', 'on')).toLowerCase();

// The working spinner: the one Kimi turns while it waits on the model or on a
// tool. `follow` means "whatever the thinking spinner is", which is what this
// patch did for both arrays before the two could be told apart — so a settings
// file written back then still means what it meant.
const W_STYLE = String(settings.get('working_style', 'follow')).toLowerCase();
const W_FRAMES_SETTING = String(settings.get('working_frames', 'default'));
const W_MIRROR = String(settings.get('working_mirror', 'on')).toLowerCase();

for (const [name, value] of [['spinner_mirror', MIRROR], ['working_mirror', W_MIRROR]]) {
  if (!['on', 'off'].includes(value)) {
    throw new Error(`${name} must be on or off - got "${value}"`);
  }
}

const PRESETS = {
  braille: ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'],
  dots: ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷'],
  moon: ['🌑', '🌒', '🌓', '🌔', '🌕', '🌖', '🌗', '🌘'],
  blocks: ['▏', '▎', '▍', '▌', '▋', '▊', '▉', '█'],
  wave: ['▁', '▃', '▄', '▅', '▆', '▇', '█', '▇', '▆', '▅', '▄', '▃'],
  glow: ['░', '▒', '▓', '█', '▓', '▒'],
  'kimi-code-mods': ['🔵', '🟢', '🟡', '🟠', '🔴'],
  // Legacy name for the kimi-code-mods set — kept parseable so a settings
  // file from before the rename still means the same five frames.
  colors: ['🔵', '🟢', '🟡', '🟠', '🔴'],
  arc: ['◜', '◠', '◝', '◞', '◡', '◟'],
  star: ['·', '✢', '✳', '✶', '✻', '✽'],
};

// Exported for the menu, which draws each preset next to its name so the
// choice is made by looking rather than by reading a word. Kept as one table
// here so the two cannot drift: a preset the menu offers and the patch does
// not know would be a row that fails when it is applied.
function kimiCodeModsSpinnerFrames(setting) {
  const raw = String(setting);
  const parts = raw.trim().split(/\s+/).filter(Boolean);
  return parts.length > 1 ? parts : Array.from(raw.trim());
}

const CHOICES = ['default', 'custom'].concat(Object.keys(PRESETS));
if (!CHOICES.includes(STYLE)) {
  throw new Error(`spinner_style must be one of ${CHOICES.join(', ')} - got "${STYLE}"`);
}
if (!CHOICES.concat(['follow']).includes(W_STYLE)) {
  throw new Error(`working_style must be one of follow, ${CHOICES.join(', ')}`
    + ` - got "${W_STYLE}"`);
}

// Both channels resolve `custom` the same way, and refuse the same way: a
// style asking for frames that were never written is a typo, not a request
// for Kimi's own set.
function resolveCustom(style, raw, styleKey, framesKey) {
  if (style !== 'custom') return null;
  if (raw === 'default' || !raw.trim()) {
    throw new Error(`${styleKey} is custom but ${framesKey} is empty - `
      + 'set the frames, or pick a preset');
  }
  const list = kimiCodeModsSpinnerFrames(raw);
  if (list.length < 2) {
    throw new Error(`${framesKey} needs at least two frames - got ${list.length}`);
  }
  return list;
}

const custom = resolveCustom(STYLE, FRAMES_SETTING, 'spinner_style', 'spinner_frames');
const wCustom = resolveCustom(W_STYLE, W_FRAMES_SETTING, 'working_style', 'working_frames');

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

// No early "nothing asked for" guard: the left margin below is fixed whatever
// the settings say, so only the `out === js` check at the end can tell a second
// run from a first.

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

// One array per channel. `BRAILLE_SPINNER_FRAMES` is what Kimi shows while it
// thinks and composes; `MOON_SPINNER_FRAMES` is what it turns while it waits on
// the model or on a tool. Setting them separately is the whole point of
// `working_style` — before it existed both got the same frames, which made the
// choice follow Kimi around instead of describing what it was doing.
const CHANNELS = [
  { name: 'BRAILLE_SPINNER_FRAMES', style: STYLE, mirror: MIRROR, custom },
  {
    name: 'MOON_SPINNER_FRAMES',
    style: W_STYLE === 'follow' ? STYLE : W_STYLE,
    mirror: W_STYLE === 'follow' ? MIRROR : W_MIRROR,
    custom: W_STYLE === 'follow' ? custom : wCustom,
  },
];
for (const channel of CHANNELS) {
  if (channel.style === 'default' && channel.mirror === 'off') continue;
  const found = readFrames(channel.name);
  const chosen = channel.style === 'default' ? found.list
    : (channel.style === 'custom' ? channel.custom : PRESETS[channel.style]);
  const wanted = channel.mirror === 'on' && !isMirrored(chosen)
    ? chosen.concat([...chosen].reverse())
    : chosen;
  const replacement = writeFrames(channel.name, wanted);
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

// -------------------------------------------------------- 3. the left margin

// `MoonLoader extends Text` and asks for `paddingX = 1`, so `Text.render`
// prefixes every line of the indicator with one space — the thinking and the
// working line both sit one column further in than the transcript above them.
// Zero puts them back on the same left edge. The literal is unique in the
// bundle; the patched form does not occur in it at all, which is what tells a
// second run apart from a first here.
const MARGIN_DONE = 'super("", 0, 0);';
if (!out.includes(MARGIN_DONE)) {
  const ANCHOR = 'super("", 1, 0);';
  const hits = out.split(ANCHOR).length - 1;
  if (hits === 0) {
    throw new Error('the MoonLoader padding not found - the shape changed this release');
  }
  if (hits !== 1) {
    throw new Error(`the MoonLoader padding is not unique (${hits}) - refusing to guess`);
  }
  out = out.replace(ANCHOR, () => MARGIN_DONE);
}

if (out === js) {
  throw new Error('already patched');
}

return out;

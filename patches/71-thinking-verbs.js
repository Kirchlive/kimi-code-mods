// Rotate the word next to the spinner instead of showing one fixed one.
//
// Kimi has no verb list to extend. It has two literals, one per activity:
//
//   src/tui/components/messages/thinking.ts, the `live` branch:
//     currentTheme.fg("textDim", "thinking...")
//
//   src/tui/kimi-tui.ts, the `composing` case:
//     this.ensureActivitySpinner("braille", "working...", (s) => currentTheme.fg("primary", s))
//
// So the list has to be brought along, and the two sites have to be reached in
// two different ways — which is the whole interesting part of this patch.
//
// WHY THE COMPOSING SITE IS NOT THE ONE THAT GETS EDITED
// `ensureActivitySpinner(style, label, colorFn)` is not a per-frame call. It
// runs when the activity pane is rebuilt, and then hands the label to
// `MoonLoader` once via the constructor or `setLabel`. Putting the rotation
// there would mean the word changes when Kimi switches state — that is, almost
// never during the long turn where a changing word would actually be worth
// something. So the rotation is spliced into `MoonLoader.updateDisplay()`,
// which the loader's existing `setInterval` already calls on every frame. The
// composing label is recognised by its value: a label of exactly "working..."
// is Kimi's fixed word and gets replaced at draw time, anything else is passed
// through untouched.
//
// That "anything else" is the point of the design. `waiting` labels itself with
// `waitingSpinnerLabel(stepRetry)`, which reports retry attempts — real
// information about a request that is failing, and the last thing that should
// be swapped for a mood word. `tool` passes no label at all. Both keep working
// exactly as before, without this patch having to know they exist.
//
// WHY THE WORD IS DERIVED FROM THE CLOCK
// No new timer is created. `MoonLoader.start()` already ticks every 80–120 ms
// and `ThinkingComponent` every 80 ms; a word picked per frame would strobe.
// `Math.floor(Date.now() / 3500)` gives a value that changes roughly every
// three and a half seconds and is the same for every caller, so a spinner does
// not need to carry a counter, nothing has to be reset when a spinner is
// recreated mid-turn, and two components drawing at once agree on the word.
// The cost is that the switch is not aligned to when the turn started: the
// first word can be on screen for anywhere between an instant and 3.5 seconds.
// A counter would fix that and would have to live somewhere — this does not,
// and the difference is invisible in practice.
//
// ------------------------------------------------------------------ settings
//
// `thinking_verbs` in patch-settings.conf: `off` keeps Kimi's two fixed words,
// `on` rotates. The default matches lib/patch_settings.py, which registers the
// same key.
//
// `thinking_verbs_list` — `default` uses the words below, anything else is a
//   comma-separated list of your own. A word is used as written, so trailing
//   punctuation is yours to include or leave out.
//
// `thinking_verbs_format` — where the word goes. `{}` is the word and the
//   default is the word alone; `{}…` and `· {}` are the other obvious shapes.
//   A format without `{}` is refused rather than silently showing a fixed
//   string on every frame, which is what "rotate the verb" is meant to avoid.

const MODE = String(settings.get('thinking_verbs', 'off')).toLowerCase();
const LIST = String(settings.get('thinking_verbs_list', 'default'));
const FORMAT = String(settings.get('thinking_verbs_format', '{}'));

if (!['on', 'off'].includes(MODE)) {
  throw new Error(`thinking_verbs must be on or off - got "${MODE}"`);
}
if (MODE === 'on' && !FORMAT.includes('{}')) {
  throw new Error(`thinking_verbs_format must contain {} - got "${FORMAT}"`);
}

if (MODE === 'off') {
  throw new Error('already patched');
}

if (js.includes('kimiCodeModsActivityVerb')) {
  throw new Error('already patched');
}

// ------------------------------------------------------------- 1. the words

// Spliced between two regions, which is top level in this bundle, so the
// function declaration is in scope for both call sites below — they live in
// different `__esmMin` modules but share this one file scope, the same way
// `BRAILLE_SPINNER_FRAMES` is declared here and read there. The `const` is
// initialised long before any of it runs; nothing draws a spinner while the
// bundle is still defining its modules.
const SPLICE_AT = '//#endregion\n//#region src/tui/components/messages/thinking.ts';

const spliceHits = js.split(SPLICE_AT).length - 1;
if (spliceHits === 0) {
  throw new Error('the thinking.ts region not found - the shape changed this release');
}
if (spliceHits !== 1) {
  throw new Error(`the thinking.ts region is not unique (${spliceHits}) - refusing to guess`);
}

const BUILT_IN_VERBS = [
  'thinking...', 'working...', 'reasoning...', 'planning...',
  'reading...', 'tracing...', 'checking...', 'drafting...',
  'refining...', 'analysing...', 'wiring...', 'sketching...',
  'considering...', 'untangling...', 'verifying...', 'weighing...',
];

const chosen = LIST === 'default' || !LIST.trim()
  ? BUILT_IN_VERBS
  : LIST.split(',').map(w => w.trim()).filter(Boolean);

if (!chosen.length) {
  throw new Error('thinking_verbs_list has no words in it - '
    + 'leave it at default, or list some');
}

const VERBS = chosen.map(w => FORMAT.split('{}').join(w));

const HELPER =
  '//#endregion\n'
  + '//#region patches/71-thinking-verbs.js\n'
  + 'const KIMICODEMODS_ACTIVITY_VERBS = [\n'
  + VERBS.map(v => '\t' + JSON.stringify(v)).join(',\n') + '\n'
  + '];\n'
  + 'function kimiCodeModsActivityVerb() {\n'
  + '\treturn KIMICODEMODS_ACTIVITY_VERBS[Math.floor(Date.now() / 3500) '
  + '% KIMICODEMODS_ACTIVITY_VERBS.length];\n'
  + '}\n'
  + '//#endregion\n'
  + '//#region src/tui/components/messages/thinking.ts';

let out = js.replace(SPLICE_AT, () => HELPER);

// ------------------------------------------------------ 2. the thinking line

const THINKS = 'currentTheme.fg("textDim", "thinking...")';
const THINKS_NOW = 'currentTheme.fg("textDim", kimiCodeModsActivityVerb())';

const thinkHits = out.split(THINKS).length - 1;
if (thinkHits === 0) {
  throw new Error('the thinking label not found - the shape changed this release');
}
if (thinkHits !== 1) {
  throw new Error(`the thinking label is not unique (${thinkHits}) - refusing to guess`);
}
out = out.replace(THINKS, () => THINKS_NOW);

// ----------------------------------------------------- 3. the spinner label

// The composing call site is not edited, only confirmed: the replacement below
// keys on the literal "working..." arriving as a label, so if that call ever
// stops passing it the patch would quietly rotate nothing. Checking it here
// turns that into a failed run instead of a feature that silently disappeared.
const COMPOSING =
  'this.ensureActivitySpinner("braille", "working...", (s) => currentTheme.fg("primary", s))';

const composingHits = out.split(COMPOSING).length - 1;
if (composingHits === 0) {
  throw new Error('the composing spinner no longer asks for "working..." - '
    + 'the label this patch keys on is gone');
}
if (composingHits !== 1) {
  throw new Error(`the composing spinner call is not unique (${composingHits}) - refusing to guess`);
}

const LABEL = 'const baseText = this.label ? `${coloredFrame} ${this.label}` : coloredFrame;';
const LABEL_NOW =
  'const activeLabel = this.label === "working..." ? kimiCodeModsActivityVerb() : this.label;\n'
  + '\t\tconst baseText = activeLabel ? `${coloredFrame} ${activeLabel}` : coloredFrame;';

const labelHits = out.split(LABEL).length - 1;
if (labelHits === 0) {
  throw new Error('MoonLoader.updateDisplay not found - the shape changed this release');
}
if (labelHits !== 1) {
  throw new Error(`MoonLoader.updateDisplay is not unique (${labelHits}) - refusing to guess`);
}
out = out.replace(LABEL, () => LABEL_NOW);

return out;

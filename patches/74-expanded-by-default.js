// Show thinking blocks and tool output expanded from the start.
//
// Kimi collapses both and offers ctrl-o to reveal them. That is the right
// default for a demo and the wrong one for reading along: the interesting part
// of a turn is usually the part that is folded away, and reaching for a
// keystroke every time is a tax on the one thing the transcript is for.
//
// Two independent flags, in two components, so the setting has two halves:
//
//   ThinkingComponent = class { text; showMarker; mode; expanded = false; ui; … }
//   … activitySpinner: null, toolOutputExpanded: false, sessions: [] …
//
// The first is the per-block state of a thinking section; the second is the
// session-wide toggle ctrl-o flips. Turning on only the first would look
// inconsistent — thinking open, tool results shut — so `expanded` moves both
// and the two sub-values exist for people who want exactly one.
//
// WHAT IT COSTS
// Nothing in tokens: this is what the terminal draws, not what the model is
// sent. It costs screen. On a long turn with large tool results the composer
// is pushed further from where you are reading, which is the reason Kimi
// folds them in the first place.
//
// WHY THE ANCHORS CARRY THEIR NEIGHBOURS
// `expanded = false;` appears seven times across the TUI — compaction dialog,
// tool calls, goal markers, and more. Only one of them belongs to the thinking
// component, and the only thing that tells them apart is the field around it.
// The anchor therefore includes the declarations either side, which is also
// what makes it fail loudly rather than silently patch the wrong component
// when the class gains a field.
//
// ------------------------------------------------------------------ settings
//
// `expanded_by_default` in patch-settings.conf:
//   off       Kimi's own folding
//   thinking  thinking blocks only
//   tools     tool output only
//   both      both
// The default matches lib/patch_settings.py.

const MODE = String(settings.get('expanded_by_default', 'off')).toLowerCase();
const ALLOWED = ['off', 'thinking', 'tools', 'both'];

if (!ALLOWED.includes(MODE)) {
  throw new Error(`expanded_by_default must be one of ${ALLOWED.join(', ')} - got "${MODE}"`);
}

if (MODE === 'off') {
  throw new Error('already patched');
}

const wantThinking = MODE === 'thinking' || MODE === 'both';
const wantTools = MODE === 'tools' || MODE === 'both';

let out = js;
let changed = 0;

function splice(label, anchor, replacement) {
  if (out.includes(replacement)) {
    return;                                  // this half is already in place
  }
  const n = out.split(anchor).length - 1;
  if (n === 0) {
    throw new Error(`${label} not found - the shape changed this release`);
  }
  if (n !== 1) {
    throw new Error(`${label} is not unique (${n}) - refusing to guess`);
  }
  out = out.replace(anchor, () => replacement);
  changed++;
}

if (wantThinking) {
  splice('the thinking component\'s expanded flag',
    'ThinkingComponent = class {\n\t\ttext;\n\t\tshowMarker;\n\t\tmode;\n\t\texpanded = false;',
    'ThinkingComponent = class {\n\t\ttext;\n\t\tshowMarker;\n\t\tmode;\n\t\texpanded = true;');
}

if (wantTools) {
  splice('the session-wide tool-output flag',
    'toolOutputExpanded: false,',
    'toolOutputExpanded: true,');
}

if (changed === 0) {
  throw new Error('already patched');
}

return out;

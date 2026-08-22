// Run Kimi in the alternate screen buffer, however it was started.
//
// `createTUIState` picks the renderer from an environment variable:
//
//   const ui = process.env["KIMI_CODE_TUI_FULL_SCREEN"] === "1"
//     ? new TuiAltScreen(...)
//     : new TuiInline(...)
//
// That works, and `bin/kimi` exports the variable — but only for the sessions
// it launches. Start Kimi from a shell that never sourced the profile, from an
// editor, from a task runner, or by calling the binary directly, and the test
// reads undefined and the inline renderer wins. The setting was therefore true
// of a launcher rather than of Kimi.
//
// Replacing the test with `true` moves the decision into the binary, which is
// the one thing every way of starting Kimi has in common. The variable is left
// in place and `bin/kimi` still exports it; it simply no longer decides
// anything here, so setting it to 0 will not switch the renderer back. Turning
// this setting off and running the patches again is what does that.
//
// WHAT IT COSTS
// The alternate screen keeps no scrollback of its own: what Kimi drew is gone
// when it exits, and the shell's own history comes back untouched underneath.
// That is the whole point of it for some people and the reason others leave it
// off, which is why this is a setting and not a fix.
//
// ------------------------------------------------------------------ settings
//
// `fullscreen` in patch-settings.conf: `on` | `off`. `off` is a no-op and
// leaves Kimi reading the environment variable exactly as it shipped.

const ON = String(settings.get('fullscreen', 'off')).toLowerCase();

if (!['on', 'off'].includes(ON)) {
  throw new Error(`fullscreen must be on or off - got "${ON}"`);
}
if (ON === 'off') {
  throw new Error('already patched');
}

const ANCHOR = 'process.env["KIMI_CODE_TUI_FULL_SCREEN"] === "1" ? new TuiAltScreen';
const REPLACEMENT = 'true ? new TuiAltScreen';

if (js.includes(REPLACEMENT)) {
  throw new Error('already patched');
}
const hits = js.split(ANCHOR).length - 1;
if (hits === 0) {
  throw new Error('the fullscreen test is gone - the shape changed this release');
}
if (hits !== 1) {
  throw new Error(`the fullscreen test is not unique (${hits}) - refusing to guess`);
}

return js.replace(ANCHOR, () => REPLACEMENT);

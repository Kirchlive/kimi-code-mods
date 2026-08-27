// Walk the subagent dock with the arrow keys, and open one to watch it work.
//
// Requires patches/82-agent-dock.js — this patch only adds movement to the
// list that one draws, and is a no-op whenever `agent_dock` is off. It has no
// switch of its own on purpose: a dock you cannot walk is fine, arrows that
// walk a dock that is not there are not.
//
// WHERE THE KEYS COME FROM
// Kimi already distinguishes an arrow key pressed in a *non-empty* composer
// (move the cursor) from one pressed in an empty one, and routes the latter
// through two dedicated hooks in
// `src/tui/controllers/editor-keyboard.ts`:
//
//   editor.onUpArrowEmpty   = () => { if (host.btwPanelController.scroll("up")) …
//   editor.onDownArrowEmpty = () => host.btwPanelController.scroll("down");
//
// Both return a boolean meaning "I consumed this key". That is the whole
// contract this patch needs, so the dock is offered the key first and Kimi's
// own handling runs unchanged whenever the dock declines. Typing is never
// affected: with any text in the composer these hooks do not fire at all.
//
// `onSubmit` and `onEscape` are wrapped the same way — but only ever act when
// a row is actually selected, so Enter keeps sending prompts and Escape keeps
// doing what it did for as long as the composer holds the focus.
//
// WHAT ENTER OPENS
// `AgentActivityViewer`, the component `/tasks` already uses to show what a
// subagent is doing — steps, tool calls, output — over a screen takeover, the
// same mechanism the tasks browser opens with. It reads its content straight
// from the activity store record, so a foreground agent works as well as a
// background one; the task metadata it would otherwise show in the header is
// simply absent, which the component already tolerates.
//
// Its own key handling gives us Escape, q, ctrl-o and the scrolling for free,
// and `onClose` puts the screen back the way it was.
//
// WHY THE VIEWER IS NOT KEPT IN SYNC
// The tasks browser re-pushes props every second so a running agent's view
// keeps growing. This patch does not: the record object it hands over is the
// live one from the store, and the viewer re-reads it on every render. What is
// missing is the repaint, so the view only advances when something else asks
// the screen to redraw — which, while an agent is working, is constantly.

const MODE = String(settings.get('agent_dock', 'off')).toLowerCase();

if (MODE === 'off') {
  throw new Error('already patched');
}

let out = js;

function splice(label, anchor, replacement) {
  if (out.includes(replacement)) {
    return;
  }
  const n = out.split(anchor).length - 1;
  if (n === 0) {
    throw new Error(`${label} not found - the shape changed this release`);
  }
  if (n !== 1) {
    throw new Error(`${label} is not unique (${n}) - refusing to guess`);
  }
  out = out.replace(anchor, () => replacement);
}

if (!out.includes('var kmodsAgentDock = {')) {
  throw new Error('82-agent-dock.js has not run - nothing to navigate');
}

for (const name of ['kmodsAgentDockNav']) {
  if (out.includes(name)) {
    throw new Error(`the name ${name} is already taken in this bundle`);
  }
}

// ------------------------------------------------------------- the navigator
//
// Hung off the dock object rather than declared beside it, so both patches
// keep exactly one name between them and the state lives where the rows that
// read it live.
splice('the dock object',
  'var kmodsAgentDock = {\n',
  'var kmodsAgentDockNav = {\n' +
  '\t/** Down from the composer selects the first agent, then walks down the\n' +
  '\t*  list. Returns false once there is nothing below, so the key falls\n' +
  '\t*  through to whatever Kimi did with it before. */\n' +
  '\tdown() {\n' +
  '\t\tconst count = kmodsAgentDock.records().length;\n' +
  '\t\tif (count === 0) return false;\n' +
  '\t\tif (kmodsAgentDock.selected >= count - 1) return false;\n' +
  '\t\tkmodsAgentDock.selected += 1;\n' +
  '\t\treturn true;\n' +
  '\t},\n' +
  '\t/** Up walks back and hands the focus to the composer at the top. */\n' +
  '\tup() {\n' +
  '\t\tif (kmodsAgentDock.selected < 0) return false;\n' +
  '\t\tkmodsAgentDock.selected -= 1;\n' +
  '\t\treturn true;\n' +
  '\t},\n' +
  '\tclear() {\n' +
  '\t\tif (kmodsAgentDock.selected < 0) return false;\n' +
  '\t\tkmodsAgentDock.selected = -1;\n' +
  '\t\treturn true;\n' +
  '\t},\n' +
  '\tselectedRecord() {\n' +
  '\t\tconst records = kmodsAgentDock.records();\n' +
  '\t\tif (kmodsAgentDock.selected < 0 || kmodsAgentDock.selected >= records.length) return void 0;\n' +
  '\t\treturn records[kmodsAgentDock.selected];\n' +
  '\t},\n' +
  '\t/** Open the selected agent over the whole screen. Any failure leaves the\n' +
  '\t*  selection alone and reports false, so a broken view can never swallow\n' +
  '\t*  the Enter that would have sent a prompt. */\n' +
  '\topen(host) {\n' +
  '\t\tconst record = this.selectedRecord();\n' +
  '\t\tif (record === void 0) return false;\n' +
  '\t\tif (typeof AgentActivityViewer === "undefined" || typeof beginScreenTakeover === "undefined") return false;\n' +
  '\t\tconst state = host?.state;\n' +
  '\t\tif (state === void 0 || state.ui === void 0) return false;\n' +
  '\t\ttry {\n' +
  '\t\t\tlet takeover;\n' +
  '\t\t\tconst viewer = new AgentActivityViewer({\n' +
  '\t\t\t\ttaskId: record.agentId,\n' +
  '\t\t\t\tinfo: void 0,\n' +
  '\t\t\t\trecord,\n' +
  '\t\t\t\tonClose: () => {\n' +
  '\t\t\t\t\tendScreenTakeover(state.ui, takeover);\n' +
  '\t\t\t\t\tstate.ui.setFocus(state.editor);\n' +
  '\t\t\t\t\tstate.ui.requestRender(true);\n' +
  '\t\t\t\t}\n' +
  '\t\t\t}, state.terminal);\n' +
  '\t\t\ttakeover = beginScreenTakeover(state.ui, viewer);\n' +
  '\t\t\tstate.ui.setFocus(viewer);\n' +
  '\t\t\tstate.ui.requestRender(true);\n' +
  '\t\t\treturn true;\n' +
  '\t\t} catch {\n' +
  '\t\t\treturn false;\n' +
  '\t\t}\n' +
  '\t}\n' +
  '};\n' +
  'var kmodsAgentDock = {\n');

// ------------------------------------------------------------------ the keys
splice('the empty-composer down arrow',
  '\t\teditor.onDownArrowEmpty = () => host.btwPanelController.scroll("down");',
  '\t\teditor.onDownArrowEmpty = () => {\n' +
  '\t\t\tif (kmodsAgentDockNav.down()) {\n' +
  '\t\t\t\thost.state.ui.requestRender();\n' +
  '\t\t\t\treturn true;\n' +
  '\t\t\t}\n' +
  '\t\t\treturn host.btwPanelController.scroll("down");\n' +
  '\t\t};');

splice('the empty-composer up arrow',
  '\t\teditor.onUpArrowEmpty = () => {\n' +
  '\t\t\tif (host.btwPanelController.scroll("up")) return true;',
  '\t\teditor.onUpArrowEmpty = () => {\n' +
  '\t\t\tif (kmodsAgentDockNav.up()) {\n' +
  '\t\t\t\thost.state.ui.requestRender();\n' +
  '\t\t\t\treturn true;\n' +
  '\t\t\t}\n' +
  '\t\t\tif (host.btwPanelController.scroll("up")) return true;');

// Enter opens the highlighted agent instead of sending the composer's text.
// Only when something is highlighted — otherwise this is not in the path at
// all.
splice('the composer submit',
  '\t\teditor.onSubmit = (text) => {',
  '\t\teditor.onSubmit = (text) => {\n' +
  '\t\t\tif (kmodsAgentDockNav.selectedRecord() !== void 0) {\n' +
  '\t\t\t\tconst opened = kmodsAgentDockNav.open(host);\n' +
  '\t\t\t\tkmodsAgentDockNav.clear();\n' +
  '\t\t\t\tif (opened) return;\n' +
  '\t\t\t}');

// `onEscape` is a void handler — every branch of it ends in a bare `return`,
// so this one does too rather than inventing a boolean the caller never reads.
splice('the composer escape',
  '\t\teditor.onEscape = () => {',
  '\t\teditor.onEscape = () => {\n' +
  '\t\t\tif (kmodsAgentDockNav.clear()) {\n' +
  '\t\t\t\thost.state.ui.requestRender();\n' +
  '\t\t\t\treturn;\n' +
  '\t\t\t}');

return out;

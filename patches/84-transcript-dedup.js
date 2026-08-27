// Drop the transcript's per-agent displays, because the dock already shows
// the same information.
//
// Merges what were patches/84-swarm-grid-off.js and
// patches/85-agent-group-off.js. Requires patches/82-agent-dock.js and is a
// no-op whenever `agent_dock` is off — without the dock these displays are
// the only per-agent views there are, and removing them would be a straight
// loss.
//
// WHAT GOES AND WHAT STAYS
//
// 1. The swarm grid and status line. `AgentSwarmProgressComponent.render`
//    builds its block as a list of lines:
//
//      const lines = [
//        "",
//        this.renderHeader(innerWidth, summary),     // ─ Agent Swarm ─ … ─
//        "",
//        ...this.renderGrid(…),                      // 001 [⣿⣿⣀…] 002 [⣤⣀…]
//        "",
//        this.renderStatusLine(innerWidth),          // ▍ Working… ━━━━━
//        ""
//      ];
//
//    The grid goes, and so does the status line. The header still names the
//    swarm and its model — that is all the transcript needs to say, because
//    *which* agent is doing what and how far along the whole thing is are
//    both answered once, in the dock, where they stay put instead of
//    scrolling away.
//
// 2. The agent group. When more than one subagent is launched in the same
//    step, Kimi collects them into an `AgentGroupComponent` and draws a tree
//    into the transcript — field for field what the dock now shows, except
//    that this copy scrolls away with the conversation and the dock does
//    not. The component stays in the tree and receives its events, but both
//    children are emptied on every flush and the leading spacer is never
//    added, so it draws nothing.
//
// WHY NOT THE OTHER WAY AROUND
// The grid and the group are the older answer to the same question and the
// weaker one: they are bound to one tool call in the transcript, disappear
// with it, tell you nothing about foreground agents spawned any other way,
// and their cells are too narrow for a file name. Keeping both means reading
// the same three agents twice in two different notations.
//
// WHAT THIS COSTS
// The grid shows each member's latest model text, which the dock does not —
// the dock shows the current tool call instead. If you want the sentence an
// agent last wrote rather than the file it is writing, that is now one
// keystroke away in the agent view (enter on a row) rather than on screen.
//
// ------------------------------------------------------------------ settings
//
// None of its own. Follows `agent_dock` in patch-settings.conf: off there
// leaves the transcript exactly as Kimi ships it.

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

// ----------------------------------------------------- 1. the swarm grid
//
// `snapshots` is still read by `summarizeSnapshots` for the header, so
// nothing above becomes dead by dropping the grid call.
splice('the swarm block',
  '\t\t\tconst lines = [\n' +
  '\t\t\t\t"",\n' +
  '\t\t\t\tthis.renderHeader(innerWidth, summary),\n' +
  '\t\t\t\t"",\n' +
  '\t\t\t\t...this.renderGrid(innerWidth, this.availableGridHeight?.(), snapshots, nowMs),\n' +
  '\t\t\t\t"",\n' +
  '\t\t\t\tthis.renderStatusLine(innerWidth),\n' +
  '\t\t\t\t""\n' +
  '\t\t\t];',
  '\t\t\tconst lines = [\n' +
  '\t\t\t\t"",\n' +
  '\t\t\t\tthis.renderHeader(innerWidth, summary),\n' +
  '\t\t\t\t""\n' +
  '\t\t\t];');

// ----------------------------------------------------- 2. the agent group
//
// The blank line above the block goes with it; a component that draws
// nothing should not cost a row either.
//
// Anchored on the class head rather than the constructor alone: the read
// group next door is built exactly the same way, down to the field list,
// and a constructor-shaped anchor matches both.
splice('the agent group\'s constructor',
  '\tAgentGroupComponent = class extends Container {\n' +
  '\t\tui;\n' +
  '\t\tentries = [];\n' +
  '\t\theaderText;\n' +
  '\t\tbodyContainer;\n' +
  '\t\tthrottleTimer = null;\n' +
  '\t\tlastFlushPhases = /* @__PURE__ */ new Map();\n' +
  '\t\t_invalidating = false;\n' +
  '\t\tconstructor(ui) {\n' +
  '\t\t\tsuper();\n' +
  '\t\t\tthis.ui = ui;\n' +
  '\t\t\tthis.addChild(new Spacer(1));',
  '\tAgentGroupComponent = class extends Container {\n' +
  '\t\tui;\n' +
  '\t\tentries = [];\n' +
  '\t\theaderText;\n' +
  '\t\tbodyContainer;\n' +
  '\t\tthrottleTimer = null;\n' +
  '\t\tlastFlushPhases = /* @__PURE__ */ new Map();\n' +
  '\t\t_invalidating = false;\n' +
  '\t\tconstructor(ui) {\n' +
  '\t\t\tsuper();\n' +
  '\t\t\tthis.ui = ui;');

// Everything the flush would have drawn is discarded. The snapshots are
// still read and the phase map still updated, so `detectPhaseTransition`
// and the listeners behave exactly as before — this only throws away the
// output.
splice('the agent group\'s flush',
  '\t\t\tconst snapshots = this.entries.map((e) => e.tc.getSubagentSnapshot());\n' +
  '\t\t\tthis.headerText.setText(this.buildHeader(snapshots));\n' +
  '\t\t\tthis.bodyContainer.clear();',
  '\t\t\tconst snapshots = this.entries.map((e) => e.tc.getSubagentSnapshot());\n' +
  '\t\t\tthis.headerText.setText("");\n' +
  '\t\t\tthis.bodyContainer.clear();\n' +
  '\t\t\tif (true) {\n' +
  '\t\t\t\tthis.lastFlushPhases.clear();\n' +
  '\t\t\t\tthis.entries.forEach((entry, i) => {\n' +
  '\t\t\t\t\tconst snap = snapshots[i];\n' +
  '\t\t\t\t\tif (snap !== void 0) this.lastFlushPhases.set(entry.toolCallId, snap.phase);\n' +
  '\t\t\t\t});\n' +
  '\t\t\t\tthis.invalidate();\n' +
  '\t\t\t\tthis.ui?.requestRender();\n' +
  '\t\t\t\treturn;\n' +
  '\t\t\t}');

return out;

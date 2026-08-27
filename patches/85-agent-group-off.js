// Drop the transcript's agent group, because the dock already shows it.
//
// Companion to patches/84-swarm-grid-off.js, which does the same for the
// swarm's grid. Requires patches/82-agent-dock.js and is a no-op whenever
// `agent_dock` is off.
//
// WHAT GOES
// When more than one subagent is launched in the same step, Kimi collects
// them into an `AgentGroupComponent` (bundled from
// `src/tui/components/messages/agent-group.ts`) and draws this into the
// transcript:
//
//   ● Running 3 agents (2 done, 1 running) · 2m 43s
//     ├─ coder · Docs: Teilnehmer-Perspektive · K3 · high · 5 tools · 2m 28s · 37.7k tok · ✓ Completed
//     ├─ coder · Docs: Troubleshooter-Perspektive · K3 · high · 7 tools · 2m 13s · 37.5k tok · ✓ Completed
//     └─ coder · Docs: Konzepte/Glossar-Perspektive · K3 · high · 6 tools · 2m 43s · 39.9k tok · Running
//            Used Write (…/docs/konzepte-glossar.md)
//     Press Ctrl+B to run in background
//
// Which is, field for field, what the dock now shows — except that this copy
// scrolls away with the conversation and the dock does not.
//
// WHAT IS LOST, AND WHAT IS NOT
// Nothing that is only here. The group never mounts the agents' own cards as
// children — the comment in the bundle says so plainly, it renders their
// snapshots — so no result text or output lives in this block. What it does
// carry alone is the `Press Ctrl+B to run in background` hint and, once every
// agent is done, a one-line tally (`3 coder agents finished · 18 tools · …`).
// Ctrl+B keeps working; it is only the reminder that goes.
//
// HOW
// The component is a `Container` that keeps its rows in two children. Rather
// than intercept the many places that build and update it, both children are
// emptied on every flush and the leading spacer is never added — the component
// stays in the tree, receives its events, and draws nothing. That keeps the
// group's bookkeeping (`attach`, snapshot listeners, phase tracking) intact for
// anything else that reaches into it.
//
// ------------------------------------------------------------------ settings
//
// None of its own. Follows `agent_dock` in patch-settings.conf.

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

// The blank line above the block goes with it; a component that draws nothing
// should not cost a row either.
//
// Anchored on the class head rather than the constructor alone: the read
// group next door is built exactly the same way, down to the field list, and
// a constructor-shaped anchor matches both.
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

// Everything the flush would have drawn is discarded. The snapshots are still
// read and the phase map still updated, so `detectPhaseTransition` and the
// listeners behave exactly as before — this only throws away the output.
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

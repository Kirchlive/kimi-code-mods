// Drop the swarm's per-agent grid, because the dock already shows it.
//
// Requires patches/82-agent-dock.js and is a no-op whenever `agent_dock` is
// off — without the dock this grid is the only per-agent view there is, and
// removing it would be a straight loss.
//
// WHAT GOES AND WHAT STAYS
// `AgentSwarmProgressComponent.render` (bundled from
// `src/tui/components/messages/agent-swarm-progress.ts`) builds its block as a
// list of lines:
//
//   const lines = [
//     "",
//     this.renderHeader(innerWidth, summary),        // ─ Agent Swarm ─ … ─
//     "",
//     ...this.renderGrid(…),                         // 001 [⣿⣿⣀…] 002 [⣤⣀…]
//     "",
//     this.renderStatusLine(innerWidth),             // ▍ Working… ━━━━━
//     ""
//   ];
//
// The grid goes, and so does the status line. The header still names the
// swarm and its model — that is all the transcript needs to say, because
// *which* agent is doing what and how far along the whole thing is are both
// answered once, in the dock, where they stay put instead of scrolling away.
//
// WHY NOT THE OTHER WAY AROUND
// The grid is the older answer to the same question and the weaker one: it is
// bound to one tool call in the transcript, disappears with it, tells you
// nothing about foreground agents spawned any other way, and its cells are too
// narrow for a file name. Keeping both means reading the same three agents
// twice in two different notations.
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
// leaves the swarm grid exactly as Kimi ships it.

const MODE = String(settings.get('agent_dock', 'off')).toLowerCase();

if (MODE === 'off') {
  throw new Error('already patched');
}

const ANCHOR =
  '\t\t\tconst lines = [\n' +
  '\t\t\t\t"",\n' +
  '\t\t\t\tthis.renderHeader(innerWidth, summary),\n' +
  '\t\t\t\t"",\n' +
  '\t\t\t\t...this.renderGrid(innerWidth, this.availableGridHeight?.(), snapshots, nowMs),\n' +
  '\t\t\t\t"",\n' +
  '\t\t\t\tthis.renderStatusLine(innerWidth),\n' +
  '\t\t\t\t""\n' +
  '\t\t\t];';

const REPLACEMENT =
  '\t\t\tconst lines = [\n' +
  '\t\t\t\t"",\n' +
  '\t\t\t\tthis.renderHeader(innerWidth, summary),\n' +
  '\t\t\t\t""\n' +
  '\t\t\t];';

if (js.includes(REPLACEMENT) && !js.includes(ANCHOR)) {
  throw new Error('already patched');
}

const n = js.split(ANCHOR).length - 1;
if (n === 0) {
  throw new Error('the swarm block is not built this way any more');
}
if (n !== 1) {
  throw new Error(`the swarm block is not unique (${n}) - refusing to guess`);
}

// `snapshots` is still read by `summarizeSnapshots` for the header, so nothing
// above becomes dead by dropping the grid call.
return js.replace(ANCHOR, () => REPLACEMENT);

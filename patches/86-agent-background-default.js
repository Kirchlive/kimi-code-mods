// Send subagents to the background whether or not the model thought to.
//
// THE PROBLEM
// A foreground subagent holds the whole turn. While one runs, the composer is
// dead: the user cannot type, and the main agent cannot start anything else or
// answer a question. Kimi has the alternative built in — `run_in_background`
// on the `Agent` tool returns immediately and reports back in a later turn —
// but whether it gets used is left to the model, and the shipped tool
// description talks it out of it ("Default to a foreground subagent").
//
// The prompt override in system-prompts/ turns that advice around. This patch
// is the part that does not depend on the model taking advice: the flag is set
// on the way past, so a subagent launched without it still runs detached.
//
// WHERE
// `SubagentTool.resolveExecution` is the single funnel every `Agent` call goes
// through before anything is spawned — the display text, the permission rule
// and the eventual launch all read the same `args` object it is handed. Adding
// the flag there means the rest of the machinery, including the row Kimi draws
// and the `automatic_notification` wording in the result, behaves exactly as
// it would have if the model had asked for it.
//
// The guard is `canRunInBackground()`, the tool's own check that `TaskList`,
// `TaskOutput` and `TaskStop` are enabled. Forcing the flag without it would
// turn every subagent launch into a rejection.
//
// WHAT IT DOES NOT COVER
// `AgentSwarm`. It has no background mode at all — no such parameter exists in
// its schema — so a swarm still holds the turn until its last member is done.
// The swarm's own description now says so, and points at several `Agent` calls
// as the way to stay responsive; if that is not enough, `AgentSwarm` can be
// switched off entirely under `[tools] disabled` in config.toml, which leaves
// the model no blocking option to reach for.
//
// WHAT IT COSTS
// A result the main agent needed immediately now arrives one turn later: it
// launches, ends its turn, and continues when the notification lands. That is
// the same shape Claude Code has, and it is the price of a composer that stays
// usable. Set `agent_background = default` to hand the decision back to the
// model.
//
// IMMEDIATE MODE
// `always` still lets the model continue the turn after dispatching — the
// loop calls it once more, and it can read a file or answer a question while
// the agent works. `immediate` sets `stopTurn: true` on the tool result, so
// the turn ends the moment the agent is dispatched. The model cannot add
// another tool call or a closing sentence — the dispatch IS the turn.
//
// That is the stricter guarantee: no continuation means no chance of the
// model deciding to wait, poll, or "just check one more thing." The cost is
// that a response that would have dispatched an agent AND done something
// else in the same turn now does only the dispatch.
//
// ------------------------------------------------------------------ settings
//
// `agent_background` in patch-settings.conf:
//   default    the model decides, guided by the tool description
//   always     every subagent that can run detached does
//   immediate  like always, and the turn ends at dispatch
//
// `agent_dock` forces `always` while it is on, and the menu will not let the
// row be changed then. The dock exists to show what is running beside a
// composer you can still type into; with foreground subagents the composer is
// frozen for exactly as long as there is anything in the dock to look at, so
// the two settings would cancel each other out. The default matches
// lib/patch_settings.py.

const DOCK = String(settings.get('agent_dock', 'off')).toLowerCase();
const CHOSEN = String(settings.get('agent_background', 'default')).toLowerCase();
const ALLOWED = ['default', 'always', 'immediate'];

if (!ALLOWED.includes(CHOSEN)) {
  throw new Error(`agent_background must be one of ${ALLOWED.join(', ')} - got "${CHOSEN}"`);
}

const MODE = DOCK === 'off' ? CHOSEN : (CHOSEN === 'immediate' ? 'immediate' : 'always');

if (MODE === 'default') {
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

// ------------------------------------------------------------- 1. the flag
splice('the subagent tool\'s execution resolution',
  '\t\tasync resolveExecution(args) {\n' +
  '\t\t\tconst requestedProfileName = args.subagent_type?.length ? args.subagent_type : void 0;',
  '\t\tasync resolveExecution(args) {\n' +
  '\t\t\tif (args.run_in_background !== true && this.canRunInBackground()) args = {\n' +
  '\t\t\t\t...args,\n' +
  '\t\t\t\trun_in_background: true\n' +
  '\t\t\t};\n' +
  '\t\t\tconst requestedProfileName = args.subagent_type?.length ? args.subagent_type : void 0;');

// ------------------------------------------------------------- 2. stopTurn
if (MODE === 'immediate') {
  // v1 (agent-core) uses `this.allowBackground`; v2 (agent-core-v2) uses
  // `allowBackground, false` and `allowBackground, true`. All four return
  // sites get the same stopTurn flag.
  const pairs = [
    ['formatBackgroundAgentResult$1(taskId, handle, args.description, this.allowBackground)',
     'formatBackgroundAgentResult$1(taskId, handle, args.description, this.allowBackground)'],
    ['formatBackgroundAgentResult(taskId, handle, args.description, allowBackground, false)',
     'formatBackgroundAgentResult(taskId, handle, args.description, allowBackground, false)'],
    ['formatBackgroundAgentResult(taskId, handle, args.description, allowBackground, true)',
     'formatBackgroundAgentResult(taskId, handle, args.description, allowBackground, true)'],
  ];
  for (const [call] of pairs) {
    const anchor = `return { output: ${call} };`;
    const replacement = `return { output: ${call}, stopTurn: true };`;
    if (out.includes(replacement)) continue;
    if (out.includes(anchor)) {
      out = out.replace(anchor, () => replacement);
    }
  }
}

return out;

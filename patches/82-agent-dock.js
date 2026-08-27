// A standing list of subagents under the composer, the way Claude Code shows
// one — instead of a line that scrolls away with the transcript.
//
// WHAT KIMI ALREADY DOES
// Every running subagent is drawn as a tree inside the transcript
// (`AgentGroupComponent`, bundled from
// `src/tui/components/messages/agent-group.ts`), with exactly the line this
// patch wants:
//
//   ├─ explore · Bus-Repo analysieren · K3 · high · 27 tools · 3m 16s · 68k tok · Running
//
// The trouble is where it lives. It is a transcript entry, so it moves up and
// out of view as soon as the conversation continues, and it is gone entirely
// once the turn ends. The footer keeps only a count — `[1 agent running]`,
// and only for *background* tasks.
//
// WHAT THIS PATCH MOVES, AND WHAT IT DOES NOT
// The data is already collected. `SubagentActivityStore` (bundled from
// `src/tui/controllers/subagent-activity-store.ts`) holds one record per
// subagent — name, description, model, effort, status — and is a controller,
// not a component, so it survives whatever the transcript does. Four things
// were missing, and this patch adds exactly those:
//
//   1. a way to reach the store from the footer     (a static `current`)
//   2. elapsed time, tokens, tool count, end time   (the record had none)
//   3. an identity that survives a late spawn       (see `ensureRecord`)
//   4. records that outlive the turn                (see PRUNING below)
//
// The row it draws says, in this order: which agent, what it is working on,
// what it is doing right now, on which model and effort, how many tool calls,
// for how long, at what context size — and, set flush right so several agents
// can be compared at a glance, how far along it looks.
//
// It does not add a second data source, a timer, or a component. The footer
// reads the store while it draws, and the store is written by events that
// already request a render.
//
// WHY THE FOOTER CAN GROW
// `FooterComponent.render` ends in `return [line1, line2]`, which reads like a
// fixed height and is not one. The footer sits in a `GutterContainer` docked
// with `shrink: 1, minSize: 1`, and the container renderer takes however many
// lines the child hands back. Returning more rows is enough; nothing else in
// the layout needs to know. `shrink` is what keeps a narrow terminal honest,
// and the row cap below is what keeps twelve agents from eating the screen.
//
// PRUNING — the one behaviour this patch overrides rather than extends
// `pruneForegroundOnlyRecord` drops the record of any subagent that never
// became a background task, at the moment it finishes. The comment in the
// bundle gives the reason plainly: such an agent can never appear in `/tasks`,
// so its record would sit there for the rest of the session with nothing to
// show it.
//
// That reason is sound and this patch does not dismiss it. On `all` the record
// is kept, but only under three limits: it must have reached a terminal state
// (an agent still marked `running` at turn end was interrupted, and would
// otherwise hang in the dock as if it were still working), at most
// AGENT_DOCK_KEEP finished records are held at once, and each is dropped from
// the display after AGENT_DOCK_TTL_MS. On `running` the original pruning is
// left completely alone.
//
// WHAT IS NOT HERE
// Walking the list with the arrow keys is patches/83-agent-dock-nav.js; this
// patch only owns `selected` so that one has somewhere to put it. Taking the
// swarm's own per-agent grid out of the transcript, which this dock makes
// redundant, is patches/84-swarm-grid-off.js. Both follow `agent_dock` and do
// nothing while it is off.
//
// Neither patch redirects your typing. Kimi has the machinery for it —
// `withInteractiveAgent(agentId, fn)` already routes `steer`, `prompt` and
// `cancel` at a chosen agent, and `/btw` uses it — but a composer that can
// address someone other than the main agent has to say so on screen, or a
// prompt lands with the wrong reader. That is a separate patch and a larger
// one.
//
// ------------------------------------------------------------------ settings
//
// `agent_dock` in patch-settings.conf:
//   off      Kimi's footer, unchanged
//   running  list the agents that are working right now
//   all      also keep the ones that just finished, briefly
// The default matches lib/patch_settings.py.

const MODE = String(settings.get('agent_dock', 'off')).toLowerCase();
const ALLOWED = ['off', 'running', 'all'];

if (!ALLOWED.includes(MODE)) {
  throw new Error(`agent_dock must be one of ${ALLOWED.join(', ')} - got "${MODE}"`);
}

if (MODE === 'off') {
  throw new Error('already patched');
}

let out = js;

function splice(label, anchor, replacement) {
  if (out.includes(replacement)) {
    return;                                    // this piece is already in place
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

// A name that already exists in the bundle would be shadowed or would shadow,
// and either way the failure would surface as a blank footer rather than an
// error. Cheaper to refuse now.
for (const name of ['kmodsAgentDock', 'AGENT_DOCK_MODE', 'AGENT_DOCK_MAX_ROWS',
                    'AGENT_DOCK_KEEP', 'AGENT_DOCK_TTL_MS']) {
  if (out.includes(name)) {
    throw new Error(`the name ${name} is already taken in this bundle`);
  }
}

// ---------------------------------------------------------------- 1. the store
//
// `current` is how the footer finds the store. The store is constructed once
// per session (`activityStore = new SubagentActivityStore()`) and cleared, not
// replaced, on reset — so a single static reference stays correct for the life
// of the process. Instance fields initialise before the constructor body on a
// base class, so `records` exists by the time anything reads it.
splice('the activity store\'s head',
  'var SubagentActivityStore = class {\n\trecords = /* @__PURE__ */ new Map();',
  'var SubagentActivityStore = class {\n' +
  '\tstatic current;\n' +
  '\t/** Hands out cohort numbers — see `ensureRecord`. */\n' +
  '\tstatic groupSeq = 0;\n' +
  '\tconstructor() {\n' +
  '\t\tSubagentActivityStore.current = this;\n' +
  '\t}\n' +
  '\t/** Drop the oldest finished records, keeping at most `keep` of them.\n' +
  '\t*  Called where the engine would otherwise have deleted them outright. */\n' +
  '\ttrimFinished(keep) {\n' +
  '\t\tconst finished = [...this.records.values()].filter((r) => r.endedAt !== void 0);\n' +
  '\t\tif (finished.length <= keep) return;\n' +
  '\t\tfinished.sort((a, b) => a.endedAt - b.endedAt);\n' +
  '\t\tfor (const record of finished.slice(0, finished.length - keep)) this.drop(record.agentId);\n' +
  '\t}\n' +
  '\trecords = /* @__PURE__ */ new Map();');

// Late-arriving identity. `recordFor` invents a placeholder record for any
// agent it has not seen — `agentName: agentId`, no description, no model, no
// effort — and child events routinely reach the store before
// `subagent.spawned` does. `ensureRecord` then finds that placeholder and
// refreshes only `status`, so the real name and model never land: the dock
// showed `agent-0 · 0 tools · 29s · 15.2k tok · Running` where it should have
// read `explore · Bus-Repo analysieren · K3 · high · …`.
//
// This was harmless before the dock existed. The store only fed the activity
// viewer, which reads a subagent's name and model from
// `backgroundAgentMetadata` instead. Drawing from the record is what made it
// visible, so it is fixed here rather than worked around in the row builder.
//
// Only fields the spawn actually carries are copied, so a genuine re-spawn
// cannot blank out what is already known.
splice('the record refresh',
  '\tensureRecord(spawn) {\n' +
  '\t\tconst existing = this.records.get(spawn.agentId);\n' +
  '\t\tif (existing !== void 0) {\n' +
  '\t\t\texisting.status = "running";\n' +
  '\t\t\texisting.resultSummary = void 0;\n' +
  '\t\t\texisting.error = void 0;\n' +
  '\t\t\treturn existing;\n' +
  '\t\t}',
  '\tensureRecord(spawn) {\n' +
  '\t\tconst existing = this.records.get(spawn.agentId);\n' +
  '\t\tif (existing !== void 0) {\n' +
  '\t\t\texisting.status = "running";\n' +
  '\t\t\texisting.resultSummary = void 0;\n' +
  '\t\t\texisting.error = void 0;\n' +
  '\t\t\tif (spawn.agentName !== void 0 && spawn.agentName !== spawn.agentId) existing.agentName = spawn.agentName;\n' +
  '\t\t\tif (spawn.description !== void 0) existing.description = spawn.description;\n' +
  '\t\t\tif (spawn.model !== void 0) existing.model = spawn.model;\n' +
  '\t\t\tif (spawn.effort !== void 0) existing.effort = spawn.effort;\n' +
  '\t\t\tif (spawn.parentToolCallId) existing.parentToolCallId = spawn.parentToolCallId;\n' +
  '\t\t\treturn existing;\n' +
  '\t\t}');

// Elapsed time and a tool count, neither of which the record carried. The
// values the transcript card shows live in `ToolCallComponent` and die with
// it, which is why they are recomputed here rather than borrowed.
splice('the record literal',
  '\t\tconst record = {\n' +
  '\t\t\tagentId: spawn.agentId,\n' +
  '\t\t\tagentName: spawn.agentName,\n' +
  '\t\t\tdescription: spawn.description,\n' +
  '\t\t\tparentToolCallId: spawn.parentToolCallId,\n' +
  '\t\t\tmodel: spawn.model,\n' +
  '\t\t\teffort: spawn.effort,\n' +
  '\t\t\tsteps: [],\n' +
  '\t\t\ttotalSteps: 0,\n' +
  '\t\t\tstatus: "running",\n' +
  '\t\t\tversion: 0\n' +
  '\t\t};',
  '\t\t// An agent that starts while another is already working belongs with\n' +
  '\t\t// it: they were launched together and are read together, so they also\n' +
  '\t\t// leave the dock together. An agent that starts alone opens a cohort\n' +
  '\t\t// of its own.\n' +
  '\t\tlet cohort;\n' +
  '\t\tfor (const other of this.records.values()) {\n' +
  '\t\t\tif (other.status !== "running") continue;\n' +
  '\t\t\tcohort = other.dockGroup;\n' +
  '\t\t\tbreak;\n' +
  '\t\t}\n' +
  '\t\tconst record = {\n' +
  '\t\t\tagentId: spawn.agentId,\n' +
  '\t\t\tagentName: spawn.agentName,\n' +
  '\t\t\tdescription: spawn.description,\n' +
  '\t\t\tparentToolCallId: spawn.parentToolCallId,\n' +
  '\t\t\tmodel: spawn.model,\n' +
  '\t\t\teffort: spawn.effort,\n' +
  '\t\t\tsteps: [],\n' +
  '\t\t\ttotalSteps: 0,\n' +
  '\t\t\tstatus: "running",\n' +
  '\t\t\tstartedAt: Date.now(),\n' +
  '\t\t\ttoolCount: 0,\n' +
  '\t\t\tdockGroup: cohort ?? ++SubagentActivityStore.groupSeq,\n' +
  '\t\t\tversion: 0\n' +
  '\t\t};');

// Tokens. `agent.status.updated` reaches the store through `applyEvent` — the
// handler forwards every child event before it looks for a transcript card —
// but the switch has no case for it, so the numbers were being discarded here
// and read only off the card. `contextTokens` wins over the usage sum, which
// is the same precedence the transcript card applies.
splice('the store\'s event switch',
  '\tapplyEvent(event) {\n\t\tswitch (event.type) {\n\t\t\tcase "turn.step.started": {',
  '\tapplyEvent(event) {\n' +
  '\t\tswitch (event.type) {\n' +
  '\t\t\tcase "agent.status.updated": {\n' +
  '\t\t\t\tconst record = this.recordFor(event.agentId);\n' +
  '\t\t\t\tif (event.contextTokens !== void 0 && event.contextTokens > 0) record.contextTokens = event.contextTokens;\n' +
  '\t\t\t\tconst usage = event.usage?.total ?? event.usage?.currentTurn;\n' +
  '\t\t\t\tif (usage !== void 0) record.usageTokens = (usage.input ?? 0) + (usage.output ?? 0);\n' +
  '\t\t\t\tthis.bump(record);\n' +
  '\t\t\t\treturn;\n' +
  '\t\t\t}\n' +
  '\t\t\tcase "turn.step.started": {');

// Track when a result came back and whether it was an error, so the
// indicator can show green (success) or red (failure) until the next call
// starts. No timers — the colour flips on the event and stays until the
// next one replaces it.
splice('the store\'s tool result',
  '\t\t\tcase "tool.result": {\n' +
  '\t\t\t\tconst record = this.records.get(event.agentId);\n' +
  '\t\t\t\tconst call = record === void 0 ? void 0 : this.findToolCall(record, event.toolCallId);\n' +
  '\t\t\t\tif (record === void 0 || call === void 0) return;',
  '\t\t\tcase "tool.result": {\n' +
  '\t\t\t\tconst record = this.records.get(event.agentId);\n' +
  '\t\t\t\tconst call = record === void 0 ? void 0 : this.findToolCall(record, event.toolCallId);\n' +
  '\t\t\t\tif (record === void 0 || call === void 0) return;\n' +
  '\t\t\t\trecord.openCalls = Math.max(0, (record.openCalls ?? 1) - 1);\n' +
  '\t\t\t\trecord.lastResultAt = Date.now();\n' +
  '\t\t\t\trecord.lastResultError = event.isError === true;');

// The tool count. `steps` is capped at twenty and cannot be counted after the
// fact, so the tally is kept as it happens — once per call, on the branch that
// decides the call is new.
//
// Both branches, and that is the point: a tool call whose arguments stream in
// is created by `tool.call.delta` first, so by the time `tool.call.started`
// arrives `findToolCall` already returns it and the count below never fires.
// Counting only there read `0 tools` on screen while the very same row showed
// `Read benutzer-alltag.md` — the activity came through, the tally did not.
splice('the store\'s streaming tool call',
  '\t\t\t\tlet call = this.findToolCall(record, event.toolCallId);\n' +
  '\t\t\t\tif (call === void 0) {\n' +
  '\t\t\t\t\tcall = {\n' +
  '\t\t\t\t\t\tid: event.toolCallId,\n' +
  '\t\t\t\t\t\tname: event.name ?? "",\n' +
  '\t\t\t\t\t\targs: {},\n' +
  '\t\t\t\t\t\tstatus: "running",\n' +
  '\t\t\t\t\t\tstartedAt: Date.now()\n' +
  '\t\t\t\t\t};\n' +
  '\t\t\t\t\tthis.currentStep(record).toolCalls.push(call);\n' +
  '\t\t\t\t}',
  '\t\t\t\tlet call = this.findToolCall(record, event.toolCallId);\n' +
  '\t\t\t\tif (call === void 0) {\n' +
  '\t\t\t\t\tcall = {\n' +
  '\t\t\t\t\t\tid: event.toolCallId,\n' +
  '\t\t\t\t\t\tname: event.name ?? "",\n' +
  '\t\t\t\t\t\targs: {},\n' +
  '\t\t\t\t\t\tstatus: "running",\n' +
  '\t\t\t\t\t\tstartedAt: Date.now()\n' +
  '\t\t\t\t\t};\n' +
  '\t\t\t\t\trecord.toolCount = (record.toolCount ?? 0) + 1;\n' +
  '\t\t\t\t\trecord.lastResultAt = void 0;\n' +
  '\t\t\t\t\trecord.lastResultError = false;\n' +
  '\t\t\t\t\trecord.openCalls = (record.openCalls ?? 0) + 1;\n' +
  '\t\t\t\t\tthis.currentStep(record).toolCalls.push(call);\n' +
  '\t\t\t\t}');

splice('the store\'s tool.call.started case',
  '\t\t\tcase "tool.call.started": {\n' +
  '\t\t\t\tconst record = this.recordFor(event.agentId);\n' +
  '\t\t\t\tconst existing = this.findToolCall(record, event.toolCallId);\n' +
  '\t\t\t\tconst args = capArgStrings(argsRecord(event.args));',
  '\t\t\tcase "tool.call.started": {\n' +
  '\t\t\t\tconst record = this.recordFor(event.agentId);\n' +
  '\t\t\t\tconst existing = this.findToolCall(record, event.toolCallId);\n' +
  '\t\t\t\tif (existing === void 0) {\n' +
  '\t\t\t\t\trecord.toolCount = (record.toolCount ?? 0) + 1;\n' +
  '\t\t\t\t\trecord.lastResultAt = void 0;\n' +
  '\t\t\t\t\trecord.lastResultError = false;\n' +
  '\t\t\t\t\trecord.openCalls = (record.openCalls ?? 0) + 1;\n' +
  '\t\t\t\t}\n' +
  '\t\t\t\tconst args = capArgStrings(argsRecord(event.args));');

// When an agent reached its end. Without this the only place a record ever got
// a timestamp was the pruning below, which is reached through
// `subagent.completed` — a swarm member finishes without going that way, so its
// record ended up `completed` but undated, and the dock, which shows a finished
// agent only while it is recent, dropped it on the spot. Two agents reading
// `✓ Fertig` in the swarm header while the dock showed neither was exactly this.
splice('the store\'s completion',
  '\tmarkCompleted(agentId, resultSummary) {\n' +
  '\t\tconst record = this.records.get(agentId);\n' +
  '\t\tif (record === void 0) return;\n' +
  '\t\trecord.status = "completed";',
  '\tmarkCompleted(agentId, resultSummary) {\n' +
  '\t\tconst record = this.records.get(agentId);\n' +
  '\t\tif (record === void 0) return;\n' +
  '\t\trecord.endedAt ??= Date.now();\n' +
  '\t\trecord.status = "completed";');

splice('the store\'s failure',
  '\tmarkFailed(agentId, error) {\n' +
  '\t\tconst record = this.records.get(agentId);\n' +
  '\t\tif (record === void 0) return;\n' +
  '\t\trecord.status = "failed";',
  '\tmarkFailed(agentId, error) {\n' +
  '\t\tconst record = this.records.get(agentId);\n' +
  '\t\tif (record === void 0) return;\n' +
  '\t\trecord.endedAt ??= Date.now();\n' +
  '\t\trecord.status = "failed";');

// Agents that outlive the turn they were started in.
//
// `resetRuntimeState` wipes the activity store at the start of every turn, and
// for foreground subagents that is right — they ended with the turn. A
// background agent does not. It keeps working and keeps emitting, but its
// record is gone, so `recordFor` invents a placeholder and `subagent.spawned`
// — the one event carrying its name, description and model — is long past.
//
// On screen that read as a row that lost its identity mid-flight: the elapsed
// time jumped back to zero, the name became `agent-3`, the model vanished,
// while the tool count and tokens kept climbing. It looked like a display bug
// and was a lifetime bug.
//
// It could not surface before subagents were detached from the turn: nothing
// used to survive a reset. Now something does, so the reset has to be told the
// difference — everything that is still running is kept, the rest goes as
// before.
splice('the runtime reset',
  '\tresetRuntimeState() {\n' +
  '\t\tthis.subagentInfo.clear();\n' +
  '\t\tthis.backgroundAgentMetadata.clear();\n' +
  '\t\tthis.activityStore.clear();',
  '\tresetRuntimeState() {\n' +
  '\t\tconst stillWorking = [...this.activityStore.records.values()].filter((r) => r.status === "running");\n' +
  '\t\tconst keptInfo = new Map();\n' +
  '\t\tconst keptMeta = new Map();\n' +
  '\t\tfor (const record of stillWorking) {\n' +
  '\t\t\tconst info = this.subagentInfo.get(record.agentId);\n' +
  '\t\t\tif (info !== void 0) keptInfo.set(record.agentId, info);\n' +
  '\t\t\tconst meta = this.backgroundAgentMetadata.get(record.agentId);\n' +
  '\t\t\tif (meta !== void 0) keptMeta.set(record.agentId, meta);\n' +
  '\t\t}\n' +
  '\t\tthis.subagentInfo.clear();\n' +
  '\t\tthis.backgroundAgentMetadata.clear();\n' +
  '\t\tthis.activityStore.clear();\n' +
  '\t\tfor (const record of stillWorking) this.activityStore.records.set(record.agentId, record);\n' +
  '\t\tfor (const [id, info] of keptInfo) this.subagentInfo.set(id, info);\n' +
  '\t\tfor (const [id, meta] of keptMeta) this.backgroundAgentMetadata.set(id, meta);',
  );

// -------------------------------------------------------------- 2. the pruning
if (MODE === 'all') {
  splice('the foreground-record pruning',
    '\tpruneForegroundOnlyRecord(subagentId) {\n' +
    '\t\tif (this.backgroundAgentMetadata.has(subagentId)) return;',
    '\tpruneForegroundOnlyRecord(subagentId) {\n' +
    '\t\tconst kept = this.activityStore.get(subagentId);\n' +
    '\t\tif (kept !== void 0 && kept.status !== "running") {\n' +
    '\t\t\tkept.endedAt ??= Date.now();\n' +
    '\t\t\tthis.activityStore.trimFinished(AGENT_DOCK_KEEP);\n' +
    '\t\t\treturn;\n' +
    '\t\t}\n' +
    '\t\tif (this.backgroundAgentMetadata.has(subagentId)) return;');
}

// -------------------------------------------------------------- 3. the footer
//
// Declared as `var` so hoisting covers the case of an event arriving before
// this region has run. The footer region is defined earlier in the bundle than
// the store, which is why the reference is guarded rather than assumed.
const helpers =
  'var AGENT_DOCK_MODE = ' + JSON.stringify(MODE) + ';\n' +
  'var AGENT_DOCK_MAX_ROWS = 5;\n' +
  'var AGENT_DOCK_KEEP = 8;\n' +
  'var AGENT_DOCK_TTL_MS = 1e4;\n' +
  'var AGENT_DOCK_CYCLE_MS = 3e3;\n' +

  'var AGENT_DOCK_BAR_CELLS = 8;\n' +
  '// The unlit cell, the same character Kimi\'s own swarm bar rests on.\n' +
  'var AGENT_DOCK_BAR_EMPTY = "\\u28C0";\n' +
  '// The bar, frame by frame, most tool calls first — `find` takes the first\n' +
  '// match, and a count between two entries holds the lower frame until it\n' +
  '// reaches the next.\n' +
  '//\n' +
  '// Drawn by hand rather than computed. A formula gives every frame the same\n' +
  '// one-cell edge; these were chosen so the leading edge reads as a slope\n' +
  '// that flattens as the bar fills — which sometimes takes two cells\n' +
  '// (`\\u28F7\\u28C4` at six) and sometimes one. The last three frames keep the\n' +
  '// eighth cell moving after the other seven are full, so a long run does not\n' +
  '// look frozen.\n' +
  'var AGENT_DOCK_BAR_FRAMES = [\n' +
  '\t{ from: 20, bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28E7" },\n' +
  '\t{ from: 14, bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28E6" },\n' +
  '\t{ from: 10, bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28C6" },\n' +
  '\t{ from: 8,  bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28F7\\u28C4" },\n' +
  '\t{ from: 7,  bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28E6\\u28C0" },\n' +
  '\t{ from: 6,  bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28F7\\u28C4\\u28C0" },\n' +
  '\t{ from: 5,  bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28F6\\u28C0\\u28C0" },\n' +
  '\t{ from: 4,  bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28C4\\u28C0\\u28C0" },\n' +
  '\t{ from: 3,  bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28C4\\u28C0\\u28C0\\u28C0" },\n' +
  '\t{ from: 2,  bar: "\\u28FF\\u28FF\\u28FF\\u28C4\\u28C0\\u28C0\\u28C0\\u28C0" },\n' +
  '\t{ from: 1,  bar: "\\u28FF\\u28F7\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0" },\n' +
  '\t{ from: 0,  bar: "\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0" }\n' +
  '];\n' +
  'var AGENT_DOCK_STOPWORDS = new Set(["je", "und", "oder", "der", "die", "das",\n' +
  '\t"den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "fuer",\n' +
  '\t"f\\u00FCr", "mit", "von", "vom", "zu", "zur", "zum", "aus", "auf", "im",\n' +
  '\t"in", "am", "an", "bei", "nach", "\\u00FCber", "unter", "pro", "als", "wie",\n' +
  '\t"jeweils", "the", "a", "of", "for", "with", "to", "from", "on", "at",\n' +
  '\t"by", "and", "or", "each", "per", "into"]);\n' +
  'var kmodsAgentDock = {\n' +
  '\t/** Index of the highlighted agent, -1 when the composer has the focus.\n' +
  '\t*  Owned here rather than in the footer so a navigation patch can move it\n' +
  '\t*  without touching how the rows are drawn. */\n' +
  '\tselected: -1,\n' +
  '\t/** Agent names that have been worn by two agents at once. Once a name is\n' +
  '\t*  in here it stays, so a number never disappears from a row that had\n' +
  '\t*  one. */\n' +
  '\tduplicated: /* @__PURE__ */ new Set(),\n' +
  '\t/** m:ss, and h:mm:ss once an agent has been at it for an hour. */\n' +
  '\telapsed(ms) {\n' +
  '\t\tconst total = Math.max(0, Math.floor(ms / 1e3));\n' +
  '\t\tconst hours = Math.floor(total / 3600);\n' +
  '\t\tconst minutes = Math.floor((total % 3600) / 60);\n' +
  '\t\tconst seconds = total % 60;\n' +
  '\t\tconst ss = String(seconds).padStart(2, "0");\n' +
  '\t\tif (hours > 0) return `${String(hours)}:${String(minutes).padStart(2, "0")}:${ss}`;\n' +
  '\t\treturn `${String(minutes)}:${ss}`;\n' +
  '\t},\n' +
  '\t/** Always thousands, never a decimal point: the column has to stay the\n' +
  '\t*  same width as it climbs, and a tenth of a k is noise at this size.\n' +
  '\t*  Zero is printed rather than hidden — the count only arrives with the\n' +
  '\t*  first `agent.status.updated`, and dropping the field until then made\n' +
  '\t*  neighbouring rows line up differently for a few seconds, which reads\n' +
  '\t*  as missing information rather than as information not yet in. */\n' +
  '\ttokens(n) {\n' +
  '\t\treturn `${String(Math.round(n / 1e3))}k`;\n' +
  '\t},\n' +
  '\t/** The bar for a given tool count, coloured up to its leading edge:\n' +
  '\t*  everything through the last non-empty cell is lit, the rest is the\n' +
  '\t*  dim ground it runs on. */\n' +
  '\tbar(record) {\n' +
  '\t\tconst tools = record.toolCount ?? 0;\n' +
  '\t\tconst frame = (AGENT_DOCK_BAR_FRAMES.find((f) => tools >= f.from)\n' +
  '\t\t\t?? AGENT_DOCK_BAR_FRAMES[AGENT_DOCK_BAR_FRAMES.length - 1]).bar;\n' +
  '\t\tlet edge = -1;\n' +
  '\t\tfor (let i = frame.length - 1; i >= 0; i--) {\n' +
  '\t\t\tif (frame[i] !== AGENT_DOCK_BAR_EMPTY) {\n' +
  '\t\t\t\tedge = i;\n' +
  '\t\t\t\tbreak;\n' +
  '\t\t\t}\n' +
  '\t\t}\n' +
  '\t\tconst lit = frame.slice(0, edge + 1);\n' +
  '\t\tconst rest = frame.slice(edge + 1);\n' +
  '\t\treturn currentTheme.dim("[") + (lit ? currentTheme.fg("success", lit) : "") +\n' +
  '\t\t\tcurrentTheme.dim(rest) + currentTheme.dim("]");\n' +
  '\t},\n' +
  '\t/** The tail of the row: a bar while it works, a verdict once it is done. */\n' +
  '\tstatusText(record) {\n' +
  '\t\tif (record.status === "completed") return currentTheme.fg("success", "Finished \\u2713");\n' +
  '\t\tif (record.status === "failed") return currentTheme.fg("error", "Failed \\u2717");\n' +
  '\t\treturn this.bar(record);\n' +
  '\t},\n' +
  '\t/** The same tail without colour, so its width can be measured without\n' +
  '\t*  parsing escape sequences back out of the rendered string. */\n' +
  '\tstatusPlain(record) {\n' +
  '\t\tif (record.status === "completed") return "Finished \\u2713";\n' +
  '\t\tif (record.status === "failed") return "Failed \\u2717";\n' +
  '\t\treturn `[${"x".repeat(AGENT_DOCK_BAR_CELLS)}]`;\n' +
  '\t},\n' +
  '\t/** Width of the right-hand column. The bar is the widest thing that\n' +
  '\t*  goes in it, and every verdict is padded to match, so the bars of\n' +
  '\t*  several agents line up under each other and can be read as a group\n' +
  '\t*  rather than one at a time. */\n' +
  '\tstatusWidth() {\n' +
  '\t\treturn AGENT_DOCK_BAR_CELLS + 2;\n' +
  '\t},\n' +
  '\t/** Two words, `where what`. Descriptions arrive as whole sentences —\n' +
  '\t*  "3 Agenten: README \\u2192 je 2 docs #1 (coder)" — and a row that carries one\n' +
  '\t*  of those pushes the bar off the right edge. Bare numbers, arrows,\n' +
  '\t*  `#1` indices and parenthesised asides carry nothing here, so they are\n' +
  '\t*  dropped and the first two real words survive. */\n' +
  '\ttwoWords(text, limit = 2) {\n' +
  '\t\tif (typeof text !== "string" || text.length === 0) return "";\n' +
  '\t\tconst kept = [];\n' +
  '\t\tconst all = [];\n' +
  '\t\tfor (const raw of text.split(/\\s+/)) {\n' +
  '\t\t\tif (/^\\(.*\\)[.,;:]?$/.test(raw)) continue;\n' +
  '\t\t\tconst word = raw.replace(/^[^\\p{L}\\p{N}]+/u, "").replace(/[^\\p{L}\\p{N}.\\-_]+$/u, "");\n' +
  '\t\t\tif (word.length === 0 || !/\\p{L}/u.test(word)) continue;\n' +
  '\t\t\tconst clipped = word.length > 20 ? `${word.slice(0, 19)}\\u2026` : word;\n' +
  '\t\t\tall.push(clipped);\n' +
  '\t\t\tif (!AGENT_DOCK_STOPWORDS.has(word.toLowerCase())) kept.push(clipped);\n' +
  '\t\t}\n' +
  '\t\t// Function words survive the filter above — they are letters — but\n' +
  '\t\t// carry nothing: "3 Agenten je 2 docs" reduced to "Agenten je", which\n' +
  '\t\t// says half of nothing. They are dropped unless doing so would leave\n' +
  '\t\t// too little to say at all.\n' +
  '\t\tconst words = kept.length >= limit ? kept : (kept.length > 0 && all.length < limit ? kept : all);\n' +
  '\t\treturn words.slice(0, limit).join(" ");\n' +
  '\t},\n' +
  '\t/** The bullet, doubling as a state light rather than a blink.\n' +
  '\t*  Four states, no timers: empty when idle, grey while a call is out,\n' +
  '\t*  green on the last call coming back clean, red on it coming back bad.\n' +
  '\t*  The colour flips the moment the event lands — a short call shows its\n' +
  '\t*  colour for exactly as long as the next render takes, which is enough\n' +
  '\t*  when the footer repaints on every event anyway. */\n' +
  '\tmarker(record) {\n' +
  '\t\tif (record.status === "completed") return currentTheme.fg("success", "\\u2713 ");\n' +
  '\t\tif (record.status === "failed") return currentTheme.fg("error", "\\u2717 ");\n' +
  '\t\tif (record.lastResultError === true) return currentTheme.fg("error", "\\u25CF ");\n' +
  '\t\tif (record.lastResultAt !== void 0) return currentTheme.fg("success", "\\u25CF ");\n' +
  '\t\tif ((record.openCalls ?? 0) > 0) return currentTheme.dim("\\u25CF ");\n' +
  '\t\treturn currentTheme.fg("primary", "\\u25EF ");\n' +
  '\t},\n' +
  '\t/** The subject of a tool call, in one word: the file it touches, the\n' +
  '\t*  program it runs, the pattern it looks for. */\n' +
  '\tsubject(args) {\n' +
  '\t\tif (args === void 0 || args === null) return "";\n' +
  '\t\tfor (const key of ["file_path", "path", "pattern", "command", "url", "query", "description"]) {\n' +
  '\t\t\tconst raw = args[key];\n' +
  '\t\t\tif (typeof raw !== "string" || raw.length === 0) continue;\n' +
  '\t\t\t// A shell command says what it does in its first two words —\n' +
  '\t\t\t// `git status`, `npm test`. Only the program name would leave the\n' +
  '\t\t\t// row saying `Bash git`, which is barely more than `Bash`.\n' +
  '\t\t\tconst head = key === "command" ? raw.trim().split(/\\s+/).slice(0, 2).join(" ") : raw;\n' +
  '\t\t\tconst leaf = key === "command" ? head : (head.split("/").filter(Boolean).pop() ?? head);\n' +
  '\t\t\treturn leaf.length > 24 ? `${leaf.slice(0, 23)}\\u2026` : leaf;\n' +
  '\t\t}\n' +
  '\t\treturn "";\n' +
  '\t},\n' +
  '\t/** What the agent is doing right now, as `where what`.\n' +
  '\t*\n' +
  '\t*  The newest call that actually names a target wins, not simply the\n' +
  '\t*  newest call. A tool call is created the moment its arguments start\n' +
  '\t*  streaming, and at that point it carries a name and nothing else — so\n' +
  '\t*  taking the newest unconditionally left the row reading `Write` for as\n' +
  '\t*  long as the arguments took to arrive, which says where nothing is\n' +
  '\t*  happening. Falling back to the last complete call keeps the field\n' +
  '\t*  answering the question, at the cost of being one call behind for a\n' +
  '\t*  moment. A bare name is used only when no call has ever had a target. */\n' +
  '\ttask(record) {\n' +
  '\t\tconst steps = record.steps ?? [];\n' +
  '\t\tlet fallback = "";\n' +
  '\t\tfor (let i = steps.length - 1; i >= 0; i--) {\n' +
  '\t\t\tconst calls = steps[i].toolCalls ?? [];\n' +
  '\t\t\tfor (let j = calls.length - 1; j >= 0; j--) {\n' +
  '\t\t\t\tconst call = calls[j];\n' +
  '\t\t\t\tif (typeof call.name !== "string" || call.name.length === 0) continue;\n' +
  '\t\t\t\tconst subject = this.subject(call.args);\n' +
  '\t\t\t\tif (subject) return `${call.name} ${subject}`;\n' +
  '\t\t\t\tif (!fallback) fallback = call.name;\n' +
  '\t\t\t}\n' +
  '\t\t}\n' +
  '\t\treturn fallback;\n' +
  '\t},\n' +
  '\t/** Join the fields into a row that fits, in three escalating steps.\n' +
  '\t*\n' +
  '\t*  First the separators give up their spacing, from the right: the\n' +
  '\t*  numbers at that end read fine as `3:16·68k`, the words on the left do\n' +
  '\t*  not. Then the shrinkable text fields are trimmed, longest first. Only\n' +
  '\t*  if that still is not enough is the row cut.\n' +
  '\t*\n' +
  '\t*  The order matters because the status sits on the right: cutting the\n' +
  '\t*  row first — which is what a plain truncate does — takes the bar off\n' +
  '\t*  the screen and leaves the description that caused the overflow in\n' +
  '\t*  place, which is precisely backwards. */\n' +
  '\tfit(fields, width) {\n' +
  '\t\tconst tightest = fields.length - 1;\n' +
  '\t\tconst render = (tight) => {\n' +
  '\t\t\tlet out = "";\n' +
  '\t\t\tlet plain = "";\n' +
  '\t\t\tfields.forEach((field, i) => {\n' +
  '\t\t\t\tif (i > 0) {\n' +
  '\t\t\t\t\tconst sep = i > tightest - tight ? "\\u00B7" : " \\u00B7 ";\n' +
  '\t\t\t\t\tout += currentTheme.dim(sep);\n' +
  '\t\t\t\t\tplain += sep;\n' +
  '\t\t\t\t}\n' +
  '\t\t\t\tout += field.rendered ?? (field.plain === true ? field.text : currentTheme.dim(field.text));\n' +
  '\t\t\t\tplain += field.text;\n' +
  '\t\t\t});\n' +
  '\t\t\treturn { out, width: plain.length };\n' +
  '\t\t};\n' +
  '\t\tfor (let tight = 0; tight <= tightest; tight++) {\n' +
  '\t\t\tconst attempt = render(tight);\n' +
  '\t\t\tif (attempt.width <= width) return attempt.out;\n' +
  '\t\t}\n' +
  '\t\tfor (let guard = 0; guard < 40; guard++) {\n' +
  '\t\t\tlet target;\n' +
  '\t\t\tfor (const field of fields) {\n' +
  '\t\t\t\tif (field.shrink !== true || field.text.length <= 6) continue;\n' +
  '\t\t\t\tif (target === void 0 || field.text.length > target.text.length) target = field;\n' +
  '\t\t\t}\n' +
  '\t\t\tif (target === void 0) break;\n' +
  '\t\t\ttarget.text = `${target.text.slice(0, target.text.length - 2).trimEnd()}\\u2026`;\n' +
  '\t\t\tconst attempt = render(tightest);\n' +
  '\t\t\tif (attempt.width <= width) return attempt.out;\n' +
  '\t\t}\n' +
  '\t\treturn truncateToWidth(render(tightest).out, width);\n' +
  '\t},\n' +
  '\t/** Records worth drawing.\n' +
  '\t*\n' +
  '\t*  Running ones always. Finished ones only on `all`, and then by cohort\n' +
  '\t*  rather than one by one: agents launched together stay until ten\n' +
  '\t*  seconds after the *last* of them is done, so a group that was read as\n' +
  '\t*  a group also leaves as one. Watching rows wink out singly while their\n' +
  '\t*  siblings worked on was the thing that made the dock feel restless.\n' +
  '\t*\n' +
  '\t*  The exception is room. While as many agents are working as the dock\n' +
  '\t*  can show, finished ones give up their place immediately — a working\n' +
  '\t*  agent nobody can see is worse than a finished one shown a moment\n' +
  '\t*  less. A cohort broken up that way does not re-form: its members are\n' +
  '\t*  marked, and from then on each keeps its own ten seconds. */\n' +
  '\trecords() {\n' +
  '\t\tif (typeof SubagentActivityStore === "undefined") return [];\n' +
  '\t\tconst store = SubagentActivityStore.current;\n' +
  '\t\tif (store === void 0 || store === null) return [];\n' +
  '\t\tconst now = Date.now();\n' +
  '\t\tconst all = [...store.records.values()];\n' +
  '\t\tconst working = all.filter((r) => r.status === "running");\n' +
  '\t\tif (AGENT_DOCK_MODE !== "all") return working;\n' +
  '\t\t// Finished agents are guests: they may stay only while there is room\n' +
  '\t\t// left over, and the newest are the ones worth keeping. Working agents\n' +
  '\t\t// never give up their place — a bar nobody can see is the one thing\n' +
  '\t\t// this dock exists to prevent.\n' +
  '\t\t//\n' +
  '\t\t// Measuring only the working ones against the cap was too generous:\n' +
  '\t\t// four working and five finished fit none of them into view, and the\n' +
  '\t\t// working ones ended up on the second page of a rotation.\n' +
  '\t\tconst room = Math.max(0, AGENT_DOCK_MAX_ROWS - working.length);\n' +
  '\t\tconst guests = all\n' +
  '\t\t\t.filter((r) => r.status !== "running" && r.endedAt !== void 0)\n' +
  '\t\t\t.sort((a, b) => b.endedAt - a.endedAt)\n' +
  '\t\t\t.slice(0, room);\n' +
  '\t\tconst welcome = new Set(guests.map((r) => r.agentId));\n' +
  '\t\t// Everyone turned away leaves their cohort behind: they will not come\n' +
  '\t\t// back as a block once space frees up again.\n' +
  '\t\tfor (const record of all) {\n' +
  '\t\t\tif (record.status !== "running" && !welcome.has(record.agentId)) record.dockAlone = true;\n' +
  '\t\t}\n' +
  '\t\tconst busy = new Set(working.map((r) => r.dockGroup));\n' +
  '\t\tconst lastEnd = /* @__PURE__ */ new Map();\n' +
  '\t\tfor (const record of all) {\n' +
  '\t\t\tif (record.endedAt === void 0 || record.dockAlone === true) continue;\n' +
  '\t\t\tif ((lastEnd.get(record.dockGroup) ?? 0) < record.endedAt) lastEnd.set(record.dockGroup, record.endedAt);\n' +
  '\t\t}\n' +
  '\t\treturn all.filter((record) => {\n' +
  '\t\t\tif (record.status === "running") return true;\n' +
  '\t\t\tif (record.endedAt === void 0 || !welcome.has(record.agentId)) return false;\n' +
  '\t\t\t// A cohort with someone still working waits for them.\n' +
  '\t\t\tif (record.dockAlone !== true && busy.has(record.dockGroup)) return true;\n' +
  '\t\t\tconst since = record.dockAlone === true ? record.endedAt : (lastEnd.get(record.dockGroup) ?? record.endedAt);\n' +
  '\t\t\treturn now - since <= AGENT_DOCK_TTL_MS;\n' +
  '\t\t});\n' +
  '\t},\n' +
  '\t/** One agent:\n' +
  '\t*  indicator bar name · model · effort · N tools · Nk · m:ss · task\n' +
  '\t*  The bar sits left, right after the indicator, so all rows share the\n' +
  '\t*  same left edge for the bar and can be compared at a glance. */\n' +
  '\tline(record, width, selected = false, note = "", ordinal = 0, shared = false) {\n' +
  '\t\tconst name = (record.agentName ?? "agent") + (ordinal > 0 ? ` #${String(ordinal)}` : "");\n' +
  '\t\tconst topic = shared ? "" : this.twoWords(record.description, 1);\n' +
  '\t\tconst label = topic ? `${name} ${topic}` : name;\n' +
  '\t\tconst fields = [{\n' +
  '\t\t\ttext: label,\n' +
  '\t\t\trendered: currentTheme.fg("primary", name) + (topic ? ` ${currentTheme.dim(topic)}` : "")\n' +
  '\t\t}];\n' +
  '\t\tif (record.model !== void 0) fields.push({ text: record.model });\n' +
  '\t\tif (record.effort !== void 0) fields.push({ text: record.effort });\n' +
  '\t\tconst toolCount = record.toolCount ?? 0;\n' +
  '\t\tfields.push({ text: `${String(toolCount)} tool${toolCount === 1 ? "" : "s"}` });\n' +
  '\t\tconst tokens = record.contextTokens && record.contextTokens > 0 ? record.contextTokens : record.usageTokens ?? 0;\n' +
  '\t\tif (tokens > 0) fields.push({ text: this.tokens(tokens) });\n' +
  '\t\tif (record.startedAt !== void 0) fields.push({ text: this.elapsed((record.endedAt ?? Date.now()) - record.startedAt) });\n' +
  '\t\t// Task last — it is the longest field and the first to be trimmed.\n' +
  '\t\tconst task = this.task(record);\n' +
  '\t\tif (task) fields.push({ text: task, shrink: true });\n' +
  '\t\tif (note) fields.push({ text: note });\n' +
  '\t\t// Completed/failed verdict as a field, not a right-aligned block.\n' +
  '\t\tif (record.status === "completed") fields.push({ text: "Finished \\u2713", rendered: currentTheme.fg("success", "Finished \\u2713") });\n' +
  '\t\tif (record.status === "failed") fields.push({ text: "Failed \\u2717", rendered: currentTheme.fg("error", "Failed \\u2717") });\n' +
  '\t\tconst head = selected ? currentTheme.fg("primary", "\\u276F ") : this.marker(record);\n' +
  '\t\t// The bar sits left, right after the indicator, so all rows share the\n' +
  '\t\t// same left edge for the bar and can be compared at a glance.\n' +
  '\t\tconst barStr = record.status === "running" ? this.bar(record) + " " : "";\n' +
  '\t\tconst prefix = "  " + head + barStr;\n' +
  '\t\tconst prefixWidth = 2 + 2 + (record.status === "running" ? AGENT_DOCK_BAR_CELLS + 2 + 1 : 0);\n' +
  '\t\tconst room = Math.max(0, width - prefixWidth);\n' +
  '\t\tconst left = this.fit(fields, room);\n' +
  '\t\treturn truncateToWidth(prefix + left, width);\n' +
  '\t},\n' +
  '\t/** The rows appended below the footer, or none at all when no subagent\n' +
  '\t*  is worth showing — an empty dock must cost no screen.\n' +
  '\t*\n' +
  '\t*  More agents than fit are cycled rather than hidden. The page comes\n' +
  '\t*  from the clock instead of a timer, so nothing has to be ticked: the\n' +
  '\t*  footer already repaints while agents work, which is exactly when\n' +
  '\t*  there is something to cycle through. */\n' +
  '\tlines(width, selected = this.selected) {\n' +
  '\t\tconst records = this.records();\n' +
  '\t\tif (records.length === 0) {\n' +
  '\t\t\tthis.selected = -1;\n' +
  '\t\t\treturn [];\n' +
  '\t\t}\n' +
  '\t\tif (selected >= records.length) selected = records.length - 1;\n' +
  '\t\tlet shown = records;\n' +
  '\t\tlet page = 0;\n' +
  '\t\tlet pages = 1;\n' +
  '\t\tlet firstIndex = 0;\n' +
  '\t\tif (records.length > AGENT_DOCK_MAX_ROWS) {\n' +
  '\t\t\tpages = Math.ceil(records.length / AGENT_DOCK_MAX_ROWS);\n' +
  '\t\t\tpage = selected >= 0\n' +
  '\t\t\t\t? Math.floor(selected / AGENT_DOCK_MAX_ROWS) % pages\n' +
  '\t\t\t\t: Math.floor(Date.now() / AGENT_DOCK_CYCLE_MS) % pages;\n' +
  '\t\t\t// With a row selected the page follows the selection and the clock\n' +
  '\t\t\t// is ignored — a list that keeps turning under a cursor cannot be\n' +
  '\t\t\t// aimed at, and the arrow keys are for aiming.\n' +
  '\t\t\t//\n' +
  '\t\t\t// The last page is pinned to the end rather than left short: a\n' +
  '\t\t\t// dock that shrinks to one row for three seconds reads as a\n' +
  '\t\t\t// glitch. Pages overlap slightly instead, and every agent is\n' +
  '\t\t\t// still reached.\n' +
  '\t\t\tconst start = Math.min(page * AGENT_DOCK_MAX_ROWS, records.length - AGENT_DOCK_MAX_ROWS);\n' +
  '\t\t\tshown = records.slice(start, start + AGENT_DOCK_MAX_ROWS);\n' +
  '\t\t\tfirstIndex = start;\n' +
  '\t\t}\n' +
  '\t\t// No `main` row: it names the agent you are already talking to and\n' +
  '\t\t// costs a line saying so. Where the pages stand goes on the last row\n' +
  '\t\t// instead, and only while there are pages — a list that swaps itself\n' +
  '\t\t// out with nothing to explain it reads as a fault.\n' +
  '\t\t// Number each agent once and keep it on the record. Deriving the\n' +
  '\t\t// number from the current list instead made it move: when the second\n' +
  '\t\t// of two agents finished and dropped out, the name was no longer\n' +
  '\t\t// duplicated and `coder #1` silently became `coder` mid-run, which\n' +
  '\t\t// reads as a different agent. Counting per name across the whole\n' +
  '\t\t// list, not the visible page, also keeps it steady while cycling.\n' +
  '\t\tconst seen = /* @__PURE__ */ new Map();\n' +
  '\t\tfor (const record of records) {\n' +
  '\t\t\tconst key = record.agentName ?? "agent";\n' +
  '\t\t\tconst n = (seen.get(key) ?? 0) + 1;\n' +
  '\t\t\tseen.set(key, n);\n' +
  '\t\t\trecord.dockOrdinal ??= n;\n' +
  '\t\t\t// Once a name has been worn by two agents at once, every one of\n' +
  '\t\t\t// them keeps its number for the rest of the session.\n' +
  '\t\t\tif (n > 1) this.duplicated.add(key);\n' +
  '\t\t}\n' +
  '\t\t// Is the description common to all of them? Then it distinguishes\n' +
  '\t\t// nobody and every row is better off without it. Compared at the same\n' +
  '\t\t// length that gets drawn — comparing two words while showing one let\n' +
  '\t\t// three rows that differ only in a dropped second word each keep a\n' +
  '\t\t// first word identical to the others.\n' +
  '\t\tconst descriptions = new Set(records.map((r) => this.twoWords(r.description, 1)));\n' +
  '\t\tconst shared = records.length > 1 && descriptions.size === 1;\n' +
  '\t\tconst rows = shown.map((record, i) => this.line(\n' +
  '\t\t\trecord,\n' +
  '\t\t\twidth,\n' +
  '\t\t\tfirstIndex + i === selected,\n' +
  '\t\t\t"",\n' +
  '\t\t\tthis.duplicated.has(record.agentName ?? "agent") ? record.dockOrdinal : 0,\n' +
  '\t\t\tshared\n' +
  '\t\t));\n' +
  '\t\t// A footer line, the way Claude Code carries one: what is off screen,\n' +
  '\t\t// and which keys apply here. A list that quietly swaps itself out\n' +
  '\t\t// reads as a fault, and keys nobody names are keys nobody presses.\n' +
  '\t\t// It costs a row, so it appears only when it has something to say —\n' +
  '\t\t// which is never in the ordinary case of a few agents and no cursor.\n' +
  '\t\tconst hidden = records.length - shown.length;\n' +
  '\t\tconst notes = [];\n' +
  '\t\tif (hidden > 0) notes.push(`\\u2193 ${String(hidden)} more  ${String(page + 1)}/${String(pages)}`);\n' +
  '\t\tif (selected >= 0) notes.push("\\u2191\\u2193 select \\u00B7 enter view \\u00B7 esc back");\n' +
  '\t\telse if (hidden > 0) notes.push("\\u2191\\u2193 select");\n' +
  '\t\tif (notes.length > 0) rows.push(truncateToWidth(currentTheme.dim(`  ${notes.join("  \\u00B7  ")}`), width));\n' +
  '\t\treturn rows;\n' +
  '\t}\n' +
  '};\n';

splice('the footer component\'s head', 'var FooterComponent = class {', helpers + 'var FooterComponent = class {');

splice('the footer\'s two-line return',
  '\t\treturn [truncateToWidth(line1, width), truncateToWidth(line2, width)];',
  '\t\treturn [truncateToWidth(line1, width), truncateToWidth(line2, width), ...kmodsAgentDock.lines(width)];');

return out;

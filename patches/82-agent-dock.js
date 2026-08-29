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
// Walking the list with the arrow keys is included below (the navigation
// section). Taking the transcript's per-agent displays out, which this dock
// makes redundant, is patches/84-transcript-dedup.js. Both follow
// `agent_dock` and do nothing while it is off.
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

// How many agents the dock shows at once. Free text in the settings file
// (the menu cycles 1-10, wider lists are noise at footer height); anything
// outside 1-20 or not a number is a typo, and a typo must not silently
// change the layout.
const ROWS_RAW = String(settings.get('agent_dock_rows', '5')).trim();
const ROWS = /^\d+$/.test(ROWS_RAW) ? parseInt(ROWS_RAW, 10) : NaN;
if (!Number.isInteger(ROWS) || ROWS < 1 || ROWS > 20) {
  throw new Error(`agent_dock_rows must be a number from 1 to 20 - got "${ROWS_RAW}"`);
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

// Already applied? The footer splice is the last one and the most specific —
// if its replacement is in the bundle, every earlier splice ran too, and the
// names below are ours. Checking here keeps the idempotency verdict in the
// contract's own words ('already patched') instead of the name guard's.
if (out.includes('...kmodsAgentDock.lines(width)')) {
  throw new Error('already patched');
}

// A name that already exists in the bundle would be shadowed or would shadow,
// and either way the failure would surface as a blank footer rather than an
// error. Cheaper to refuse now. This only fires for names we did not write —
// our own are caught by the check above.
for (const name of ['kmodsAgentDock', 'kmodsAgentDockNav', 'kmodsDockHost', 'AGENT_DOCK_MODE', 'AGENT_DOCK_MAX_ROWS',
                    'AGENT_DOCK_KEEP', 'AGENT_DOCK_TTL_MS', 'AGENT_DOCK_STOP_TTL_MS']) {
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
  '\t\t\t\trecord.lastResultError = event.isError === true;\n' +
  '\t\t\t\tif (event.isError === true) {\n' +
  '\t\t\t\t\tconst now = Date.now();\n' +
  '\t\t\t\t\t// A failure inside an open window extends it and turns it into a\n' +
  '\t\t\t\t\t// series; the first failure of a window holds solid.\n' +
  '\t\t\t\t\trecord.failSolo = !(record.failUntil !== void 0 && now < record.failUntil);\n' +
  '\t\t\t\t\tif (record.failSolo) record.failStart = now;\n' +
  '\t\t\t\t\trecord.failUntil = now + AGENT_DOCK_FAIL_MS;\n' +
  '\t\t\t\t}');

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
  '\t\t\t\t\trecord.lastCallAt = Date.now();\n' +
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
  '\t\t\t\t\trecord.lastCallAt = Date.now();\n' +
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
  '\t\tconst stillWorking = [...this.activityStore.records.values()].filter((r) => r.status === "running" || r.endedAt !== void 0);\n' +
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

// `clearAgentSwarmProgress` is called from `handleTurnBegin` at the start of
// every turn, wiping the swarm progress map before the still-running members
// have a chance to re-emit their spawn events. The dock rows vanish for a
// beat and come back with new numbering. Preserving the entries whose agents
// are still running keeps the rows — and their ordinals — intact.
splice('the swarm progress clear',
  '\tclearAgentSwarmProgress() {\n' +
  '\t\tfor (const progress of this.agentSwarmProgress.values()) progress.dispose();\n' +
  '\t\tthis.agentSwarmProgress.clear();',
  '\tclearAgentSwarmProgress() {\n' +
  '\t\tconst running = new Set();\n' +
  '\t\tfor (const record of this.activityStore.records.values()) {\n' +
  '\t\t\tif (record.status === "running" && record.parentToolCallId) running.add(record.parentToolCallId);\n' +
  '\t\t}\n' +
  '\t\tfor (const [key, progress] of this.agentSwarmProgress) {\n' +
  '\t\t\tif (running.has(key)) continue;\n' +
  '\t\t\tprogress.dispose();\n' +
  '\t\t\tthis.agentSwarmProgress.delete(key);\n' +
  '\t\t}');

// -------------------------------------------------------------- 2. the pruning
//
// A swarm member stays foreground-shaped even when its swarm is a registered
// background task: `KmodsSwarmTask` carries the parent's tool-call id, not the
// members' agent ids, so the turn-end sweep (`dropForegroundOnlyActivityRecords`,
// called from `handleTurnEnd`) matches none of them and drops their records
// while they are still working. With `agent_background = immediate` the turn
// ends the moment the swarm is dispatched — the sweep runs BEFORE the members'
// `subagent.spawned` events even exist (spawn awaits binding, permissions, turn
// setup; the sweep runs 3ms after task registration), and the records that
// arrive later come back as `agent-N` placeholders.
//
// The parentToolCallId guard below cannot fix that timing: at sweep time there
// is no record to match. The robust fix is one level up, in the sweep itself:
// a record marked `running` is never dropped at turn end. The sweep's original
// purpose — clearing foreground subagents aborted with the turn, which emit no
// terminal event — does not apply here: every subagent these patches dispatch
// runs detached, and swarm members always terminate through the batch.
splice('the turn-end record sweep',
  '\tdropForegroundOnlyActivityRecords() {\n' +
  '\t\tfor (const agentId of this.activityStore.agentIds()) this.pruneForegroundOnlyRecord(agentId);\n' +
  '\t}',
  '\tdropForegroundOnlyActivityRecords() {\n' +
  '\t\tfor (const agentId of this.activityStore.agentIds()) {\n' +
  '\t\t\tconst record = this.activityStore.get(agentId);\n' +
  '\t\t\tif (record !== void 0 && record.status === "running") continue;\n' +
  '\t\t\tthis.pruneForegroundOnlyRecord(agentId);\n' +
  '\t\t}\n' +
  '\t}');

// The parentToolCallId guard stays as the second line of defence: a member
// whose record exists AND is running AND shares its parent call with a
// registered task is kept even if something else calls the prune directly.
//
// Keeping *finished* records is an `all`-only behaviour below it.
const SWARM_GUARD =
  '\t\tconst kept = this.activityStore.get(subagentId);\n' +
  '\t\tif (kept !== void 0 && kept.status === "running" && kept.parentToolCallId) {\n' +
  '\t\t\tfor (const info of this.deps.backgroundTasks.values()) {\n' +
  '\t\t\t\tif (info.kind === "agent" && info.parentToolCallId === kept.parentToolCallId) return;\n' +
  '\t\t\t}\n' +
  '\t\t}\n';

// ------------------------------------------------------------- 2b. the badge
//
// The footer's own `[N agents running]` badge says what the dock shows in
// full rows directly underneath it. Redundant at best, misleading at worst —
// it counts background tasks while the dock also lists foreground ones.
// The shared splice() cannot take this one: its early return tests
// `includes(replacement)`, and an empty replacement is found everywhere —
// which made this removal a silent no-op since the day it was written, badge
// showing the whole time. Explicit checks instead.
{
  const BADGE =
    '\t\tif (this.backgroundAgentCount > 0) {\n' +
    '\t\t\tconst noun = this.backgroundAgentCount === 1 ? "agent" : "agents";\n' +
    '\t\t\ttaskBadges.push(chalk.hex(colors.primary)(`[${String(this.backgroundAgentCount)} ${noun} running]`));\n' +
    '\t\t}\n';
  const n = out.split(BADGE).length - 1;
  if (n === 0) {
    throw new Error('the footer agent badge not found - the shape changed this release');
  }
  if (n !== 1) {
    throw new Error(`the footer agent badge is not unique (${n}) - refusing to guess`);
  }
  out = out.replace(BADGE, () => '');
}

if (MODE === 'all') {
  splice('the foreground-record pruning',
    '\tpruneForegroundOnlyRecord(subagentId) {\n' +
    '\t\tif (this.backgroundAgentMetadata.has(subagentId)) return;',
    '\tpruneForegroundOnlyRecord(subagentId) {\n' +
    SWARM_GUARD +
    '\t\tif (kept !== void 0 && kept.status !== "running") {\n' +
    '\t\t\tkept.endedAt ??= Date.now();\n' +
    '\t\t\tthis.activityStore.trimFinished(AGENT_DOCK_KEEP);\n' +
    '\t\t\treturn;\n' +
    '\t\t}\n' +
    '\t\tif (this.backgroundAgentMetadata.has(subagentId)) return;');
} else {
  splice('the foreground-record pruning',
    '\tpruneForegroundOnlyRecord(subagentId) {\n' +
    '\t\tif (this.backgroundAgentMetadata.has(subagentId)) return;',
    '\tpruneForegroundOnlyRecord(subagentId) {\n' +
    SWARM_GUARD +
    '\t\tif (this.backgroundAgentMetadata.has(subagentId)) return;');
}

// -------------------------------------------------------------- 3. the footer
//
// Declared as `var` so hoisting covers the case of an event arriving before
// this region has run. The footer region is defined earlier in the bundle than
// the store, which is why the reference is guarded rather than assumed.
const helpers =
  'var AGENT_DOCK_MODE = ' + JSON.stringify(MODE) + ';\n' +
  'var AGENT_DOCK_MAX_ROWS = ' + String(ROWS) + ';\n' +
  'var AGENT_DOCK_KEEP = 8;\n' +
  'var AGENT_DOCK_TTL_MS = 1e4;\n' +
  '// A dock-stopped row lingers three seconds, not ten: you watched the stop,\n' +
  '// the row only has to confirm it landed.\n' +
  'var AGENT_DOCK_STOP_TTL_MS = 3e3;\n' +
  'var AGENT_DOCK_CYCLE_MS = 3e3;\n' +
  '// How long a failure window lasts: the first failure holds solid red for\n' +
  '// the whole window; each further failure inside it turns it into a series\n' +
  '// (blink) and extends it.\n' +
  'var AGENT_DOCK_FAIL_MS = 2e3;\n' +

  'var AGENT_DOCK_BAR_CELLS = 8;\n' +
  '// The unlit cell, the same character Kimi\'s own swarm bar rests on.\n' +
  'var AGENT_DOCK_BAR_EMPTY = "\\u28C0";\n' +
  '// The bar, frame by frame, most tool calls first — `find` takes the first\n' +
  '// match, and a count between two entries holds the lower frame until it\n' +
  '// reaches the next.\n' +
  '//\n' +
  '// Drawn by hand rather than computed. Every second step fills one whole\n' +
  '// cell for the first four; from ten on a half cell (`\\u28C7`) marks the\n' +
  '// leading edge between the full ones, so the bar keeps moving while the\n' +
  '// steps between frames grow. The last frame lands at thirty.\n' +
  'var AGENT_DOCK_BAR_FRAMES = [\n' +
  '\t{ from: 30, bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28C7" },\n' +
  '\t{ from: 27, bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28C0" },\n' +
  '\t{ from: 24, bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28C7\\u28C0" },\n' +
  '\t{ from: 21, bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28C0\\u28C0" },\n' +
  '\t{ from: 16, bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28C7\\u28C0\\u28C0" },\n' +
  '\t{ from: 13, bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28FF\\u28C0\\u28C0\\u28C0" },\n' +
  '\t{ from: 10, bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28C7\\u28C0\\u28C0\\u28C0" },\n' +
  '\t{ from: 8,  bar: "\\u28FF\\u28FF\\u28FF\\u28FF\\u28C0\\u28C0\\u28C0\\u28C0" },\n' +
  '\t{ from: 6,  bar: "\\u28FF\\u28FF\\u28FF\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0" },\n' +
  '\t{ from: 4,  bar: "\\u28FF\\u28FF\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0" },\n' +
  '\t{ from: 2,  bar: "\\u28FF\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0" },\n' +
  '\t{ from: 0,  bar: "\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0\\u28C0" }\n' +
  '];\n' +
  'var kmodsAgentDock = {\n' +
  '\t/** Index of the highlighted agent, -1 when the composer has the focus.\n' +
  '\t*  Owned here rather than in the footer so a navigation patch can move it\n' +
  '\t*  without touching how the rows are drawn. */\n' +
  '\tselected: -1,\n' +
  '\t/** Set when `s` stops an agent: the row takes a short "stopping" beat\n' +
  '\t*  before the engine\'s own events turn it into `failed`. */\n' +
  '\tstoppedAt: 0,\n' +
  '\t/** Left edge of the sliding window over the records, in record indexes.\n' +
  '\t*  Kept between renders so a repaint does not re-derive it and snap the\n' +
  '\t*  list back under a resting cursor. Only meaningful while more records\n' +
  '\t*  exist than rows fit. */\n' +
  '\twindowStart: 0,\n' +
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
  '\t/** The bar for a given step count, coloured up to its leading edge:\n' +
  '\t*  everything through the last non-empty cell is lit, the rest is the\n' +
  '\t*  dim ground it runs on. Steps, not tool calls: the loop marks its own\n' +
  '\t*  progress in them, so the bar moves at the same pace for every agent\n' +
  '\t*  instead of racing whoever shells out the most. */\n' +
  '\tbar(record) {\n' +
  '\t\tconst steps = record.totalSteps ?? 0;\n' +
  '\t\tconst frame = (AGENT_DOCK_BAR_FRAMES.find((f) => steps >= f.from)\n' +
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
  '\t/** The bullet as a true state light, with a clock where the state is\n' +
  '\t*  time-shaped. Each row blinks on its own phase, anchored at the event\n' +
  '\t*  that started the state — a global `now % period` would pulse every\n' +
  '\t*  agent in lockstep, which reads as one light, not many.\n' +
  '\t*\n' +
  '\t*  Precedence, top first: terminal verdicts, the failure window, a call in\n' +
  '\t*  flight (green blink 1200/500 from the call\'s start), between calls with\n' +
  '\t*  the model at work (grey blink 1200/500 from the result), never-called-\n' +
  '\t*  yet (hollow grey), and the quiet floor (hollow green). The hollow circle\n' +
  '\t*  carries every colour the full one does — a blink\'s off-beat is the same\n' +
  '\t*  state, not a lesser one. */\n' +
  '\tmarker(record) {\n' +
  '\t\tif (record.status === "completed") return currentTheme.fg("success", "\\u2713 ");\n' +
  '\t\tif (record.status === "failed") return currentTheme.fg("error", "\\u2717 ");\n' +
  '\t\tconst now = Date.now();\n' +
  '\t\tconst full = "\\u25CF ";\n' +
  '\t\tconst open = "\\u25EF ";\n' +
  '\t\tif (record.failUntil !== void 0 && now < record.failUntil) {\n' +
  '\t\t\tif (record.failSolo === true) return currentTheme.fg("error", full);\n' +
  '\t\t\tconst t = now - (record.failStart ?? now);\n' +
  '\t\t\treturn t % 1000 < 500 ? currentTheme.fg("error", full) : currentTheme.fg("error", open);\n' +
  '\t\t}\n' +
  '\t\tif ((record.openCalls ?? 0) > 0) {\n' +
  '\t\t\tconst t = now - (record.lastCallAt ?? now);\n' +
  '\t\t\treturn t % 1700 < 1200 ? currentTheme.fg("success", full) : currentTheme.fg("success", open);\n' +
  '\t\t}\n' +
  '\t\tif (record.lastResultAt !== void 0) {\n' +
  '\t\t\tconst t = now - record.lastResultAt;\n' +
  '\t\t\treturn t % 1700 < 1200 ? currentTheme.dim(full) : currentTheme.dim(open);\n' +
  '\t\t}\n' +
  '\t\tif ((record.toolCount ?? 0) === 0) return currentTheme.dim(open);\n' +
  '\t\treturn currentTheme.fg("success", open);\n' +
  '\t},\n' +
  '\t/** The subject of a tool call: the file it touches, the program it runs,\n' +
  '\t*  the pattern it looks for. Paths keep their tail — the segments that\n' +
  '\t*  actually identify the file — and shed leading ones when long. Shell\n' +
  '\t*  commands shrink in steps: paths first, the `cd … &&` lead-in next,\n' +
  '\t*  trailing arguments last. */\n' +
  '\tsubject(args) {\n' +
  '\t\tif (args === void 0 || args === null) return "";\n' +
  '\t\tfor (const key of ["file_path", "path", "pattern", "command", "url", "query", "description"]) {\n' +
  '\t\t\tconst raw = args[key];\n' +
  '\t\t\tif (typeof raw !== "string" || raw.length === 0) continue;\n' +
  '\t\t\tif (key === "command") return this.commandTail(raw);\n' +
  '\t\t\tif (key === "file_path" || key === "path") return this.pathTail(raw);\n' +
  '\t\t\treturn raw;\n' +
  '\t\t}\n' +
  '\t\treturn "";\n' +
  '\t},\n' +
  '\t/** A path with its tail kept: `/\u2026/src/cmd/clui/main.go` rather than\n' +
  '\t*  `/Users/rob/Development/\u2026`. Leading segments go first, one at a time,\n' +
  '\t*  until what is left fits. */\n' +
  '\tpathTail(raw, max = 40) {\n' +
  '\t\tif (raw.length <= max) return raw;\n' +
  '\t\tconst segs = raw.split("/").filter(Boolean);\n' +
  '\t\tif (segs.length <= 2) return raw;\n' +
  '\t\tlet keep = segs.length - 1;\n' +
  '\t\twhile (keep > 1 && ("/\u2026/" + segs.slice(-keep).join("/")).length > max) keep--;\n' +
  '\t\treturn "/\u2026/" + segs.slice(-keep).join("/");\n' +
  '\t},\n' +
  '\t/** A shell command, shortened in steps rather than cut mid-token:\n' +
  '\t*  full → long path tokens tailed → `cd <dir> && ` off → trailing\n' +
  '\t*  arguments off, rightmost first, down to the bare command. The row\n' +
  '\t*  fitter takes over from whatever step still does not fit. */\n' +
  '\tcommandTail(raw) {\n' +
  '\t\tconst trimmed = raw.trim();\n' +
  '\t\tif (trimmed.length <= 56) return trimmed;\n' +
  '\t\tconst tokens = trimmed.split(/\\s+/);\n' +
  '\t\tconst tailed = tokens.map((t) => t.includes("/") ? this.pathTail(t, 24) : t).join(" ");\n' +
  '\t\tif (tailed.length <= 56) return tailed;\n' +
  '\t\tconst cdMatch = tailed.match(/^cd\\s+\\S+\\s*&&\\s*/);\n' +
  '\t\tconst noCd = cdMatch ? tailed.slice(cdMatch[0].length) : tailed;\n' +
  '\t\tif (noCd.length <= 56) return noCd;\n' +
  '\t\tconst words = noCd.split(/\\s+/);\n' +
  '\t\twhile (words.length > 3 && words.join(" ").length > 56) words.pop();\n' +
  '\t\treturn words.join(" ");\n' +
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
  '\t\t\t// A pre-rendered field would keep its old text under the new one —\n' +
  '\t\t\t// drop it, so the row re-renders from the shortened text.\n' +
  '\t\t\ttarget.rendered = void 0;\n' +
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
  '\t\t\t// An agent stopped from the dock leaves on its own short clock:\n' +
  '\t\t\t// the stop was seen happening, so the row only has to confirm it.\n' +
  '\t\t\treturn now - since <= (record.dockStopped === true ? AGENT_DOCK_STOP_TTL_MS : AGENT_DOCK_TTL_MS);\n' +
  '\t\t});\n' +
  '\t},\n' +
  '\t/** The agent\'s own description, at most two words — enough to tell\n' +
  '\t*  "Explore documents" from "Write docs" without paying for the sentence\n' +
  '\t*  it came from. */\n' +
  '\ttwoWords(text) {\n' +
  '\t\tif (typeof text !== "string" || text.length === 0) return "";\n' +
  '\t\treturn text.trim().split(/\\s+/).slice(0, 2).join(" ");\n' +
  '\t},\n' +
  '\t/** One agent:\n' +
  '\t*  [❯] indicator elapsed bar name #N · model · effort · N tools · Nk · desc · task\n' +
  '\t*  The bar (or the verdict bracket, once done) sits at a fixed left edge,\n' +
  '\t*  so rows can be compared at a glance; the task ends the line and is the\n' +
  '\t*  first field to shrink. */\n' +
  '\tline(record, width, selected = false, ordinal = 0) {\n' +
  '\t\tconst name = (record.agentName ?? "agent") + ` #${String(Math.max(1, ordinal))}`;\n' +
  '\t\tconst fields = [{\n' +
  '\t\t\ttext: name,\n' +
  '\t\t\trendered: currentTheme.fg("primary", name)\n' +
  '\t\t}];\n' +
  '\t\t// Model and effort: the v1 engine does not put them on the spawn\n' +
  '\t\t// event, so the record arrives without them. The metadata map is\n' +
  '\t\t// written by the same handler and carries them for background agents.\n' +
  '\t\tconst model = record.model ?? kmodsAgentDock.metaFor(record)?.model;\n' +
  '\t\tconst effort = record.effort ?? kmodsAgentDock.metaFor(record)?.thinkingEffort;\n' +
  '\t\tif (model !== void 0) fields.push({ text: model });\n' +
  '\t\tif (effort !== void 0) fields.push({ text: effort });\n' +
  '\t\tconst toolCount = record.toolCount ?? 0;\n' +
  '\t\tfields.push({ text: `${String(toolCount)} tool${toolCount === 1 ? "" : "s"}` });\n' +
  '\t\tconst tokens = record.contextTokens && record.contextTokens > 0 ? record.contextTokens : record.usageTokens ?? 0;\n' +
  '\t\tif (tokens > 0) fields.push({ text: this.tokens(tokens) });\n' +
  '\t\tconst desc = this.twoWords(record.description);\n' +
  '\t\tif (desc) fields.push({ text: desc });\n' +
  '\t\t// Task last — it is the longest field and the first to be trimmed.\n' +
  '\t\t// The tool name wears the primary colour, the way the same call does\n' +
  '\t\t// in the transcript; its subject stays dim. A finished agent with no\n' +
  '\t\t// task reads "idle" rather than nothing.\n' +
  '\t\tconst task = this.task(record);\n' +
  '\t\tif (task) {\n' +
  '\t\t\tconst sp = task.indexOf(" ");\n' +
  '\t\t\tconst rendered = sp === -1 ? currentTheme.fg("primary", task)\n' +
  '\t\t\t\t: currentTheme.fg("primary", task.slice(0, sp)) + " " + currentTheme.dim(task.slice(sp + 1));\n' +
  '\t\t\tfields.push({ text: task, shrink: true, rendered });\n' +
  '\t\t} else if (record.status !== "running") fields.push({ text: "idle" });\n' +
  '\t\t// The selector owns the leftmost cell at a fixed two columns, so a row\n' +
  '\t\t// never shifts when it gains focus: a selected one reads ❯ ●, an\n' +
  '\t\t// unselected one keeps the same width with two spaces.\n' +
  '\t\tconst sel = selected ? currentTheme.dim("\\u276F ") : "  ";\n' +
  '\t\tconst time = record.startedAt !== void 0 ? this.elapsed((record.endedAt ?? Date.now()) - record.startedAt) + " " : "";\n' +
  '\t\t// Bar position: the bar while running, the verdict bracket once done —\n' +
  '\t\t// same edge, same width, the whole verdict dimmed like the bar\'s own.\n' +
  '\t\tlet mid;\n' +
  '\t\tif (record.status === "completed") mid = currentTheme.dim("[Finished]") + " ";\n' +
  '\t\telse if (record.status === "failed") mid = currentTheme.dim("[") + currentTheme.fg("error", "Failed") + currentTheme.dim("]") + "   ";\n' +
  '\t\telse mid = this.bar(record) + " ";\n' +
  '\t\tconst prefix = sel + this.marker(record) + time + mid;\n' +
  '\t\tconst prefixWidth = 2 + 2 + visibleWidth(time) + AGENT_DOCK_BAR_CELLS + 2 + 1;\n' +
  '\t\tconst room = Math.max(0, width - prefixWidth);\n' +
  '\t\tconst left = this.fit(fields, room);\n' +
  '\t\treturn truncateToWidth(prefix + left, width);\n' +
  '\t},\n' +
  '\t/** The metadata map entry for a record, if there is one. Read lazily\n' +
  '\t*  so the dock does not hold a reference that would go stale on reset. */\n' +
  '\tmetaFor(record) {\n' +
  '\t\tif (typeof SubagentActivityStore === "undefined") return void 0;\n' +
  '\t\tconst store = SubagentActivityStore.current;\n' +
  '\t\tif (store === void 0 || store === null) return void 0;\n' +
  '\t\treturn store.backgroundAgentMetadata?.get(record.agentId);\n' +
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
  '\t\t\tthis.windowStart = 0;\n' +
  '\t\t\treturn [];\n' +
  '\t\t}\n' +
  '\t\tif (selected >= records.length) selected = records.length - 1;\n' +
  '\t\tlet shown = records;\n' +
  '\t\tlet firstIndex = 0;\n' +
  '\t\tif (records.length > AGENT_DOCK_MAX_ROWS) {\n' +
  '\t\t\t// A sliding window, not pages. With a cursor the window follows it\n' +
  '\t\t\t// one row at a time — the arrow stays on the bottom row while the\n' +
  '\t\t\t// list scrolls under it, instead of jumping a whole page and\n' +
  '\t\t\t// landing the cursor two rows up. Without a cursor the window is\n' +
  '\t\t\t// driven by the clock, as before: the footer already repaints\n' +
  '\t\t\t// while agents work, so nothing has to be ticked. The window is\n' +
  '\t\t\t// remembered between renders so a repaint without a keypress does\n' +
  '\t\t\t// not snap back to wherever the selection arithmetic would put it.\n' +
  '\t\t\tconst maxStart = records.length - AGENT_DOCK_MAX_ROWS;\n' +
  '\t\t\tif (selected >= 0) {\n' +
  '\t\t\t\tif (selected < this.windowStart) this.windowStart = selected;\n' +
  '\t\t\t\telse if (selected >= this.windowStart + AGENT_DOCK_MAX_ROWS) this.windowStart = selected - AGENT_DOCK_MAX_ROWS + 1;\n' +
  '\t\t\t} else {\n' +
  '\t\t\t\tconst pages = Math.ceil(records.length / AGENT_DOCK_MAX_ROWS);\n' +
  '\t\t\t\tthis.windowStart = Math.min(Math.floor(Date.now() / AGENT_DOCK_CYCLE_MS) % pages * AGENT_DOCK_MAX_ROWS, maxStart);\n' +
  '\t\t\t}\n' +
  '\t\t\tthis.windowStart = Math.max(0, Math.min(this.windowStart, maxStart));\n' +
  '\t\t\tshown = records.slice(this.windowStart, this.windowStart + AGENT_DOCK_MAX_ROWS);\n' +
  '\t\t\tfirstIndex = this.windowStart;\n' +
  '\t\t}\n' +
  '\t\t// No `main` row: it names the agent you are already talking to and\n' +
  '\t\t// costs a line saying so. Where the pages stand goes on the last row\n' +
  '\t\t// instead, and only while there are pages — a list that swaps itself\n' +
  '\t\t// out with nothing to explain it reads as a fault.\n' +
  '\t\t// Number each agent once and keep it on the record. Deriving the\n' +
  '\t\t// number from the current list instead made it move: when the second\n' +
  '\t\t// of two agents finished and dropped out, `coder #1` silently became\n' +
  '\t\t// `coder` mid-run, which reads as a different agent. Counting per name\n' +
  '\t\t// across the whole list, not the visible page, also keeps it steady\n' +
  '\t\t// while cycling.\n' +
  '\t\tconst seen = /* @__PURE__ */ new Map();\n' +
  '\t\tfor (const record of records) {\n' +
  '\t\t\tconst key = record.agentName ?? "agent";\n' +
  '\t\t\tconst n = (seen.get(key) ?? 0) + 1;\n' +
  '\t\t\tseen.set(key, n);\n' +
  '\t\t\trecord.dockOrdinal ??= n;\n' +
  '\t\t}\n' +
  '\t\tconst rows = shown.map((record, i) => this.line(\n' +
  '\t\t\trecord,\n' +
  '\t\t\twidth,\n' +
  '\t\t\tfirstIndex + i === selected,\n' +
  '\t\t\trecord.dockOrdinal ?? 0\n' +
  '\t\t));\n' +
  '\t\t// A footer line, the way Claude Code carries one: what is off screen,\n' +
  '\t\t// and which keys apply here. A list that quietly swaps itself out\n' +
  '\t\t// reads as a fault, and keys nobody names are keys nobody presses.\n' +
  '\t\t// It costs a row, so it appears only when it has something to say.\n' +
  '\t\t// The count is what is hidden *below* the window: rows above are\n' +
  '\t\t// where the cursor came from, rows below are where ↓ still goes.\n' +
  '\t\t// The key legend rides on every dock that has records at all — a\n' +
  '\t\t// hidden legend reads as "no agent there", which is never true when\n' +
  '\t\t// this line renders.\n' +
  '\t\tconst hiddenBelow = records.length - (firstIndex + shown.length);\n' +
  '\t\tconst notes = [];\n' +
  '\t\tif (hiddenBelow > 0) notes.push(`\\u2193 ${String(hiddenBelow)} more`);\n' +
  '\t\tnotes.push("\\u2191\\u2193 select \\u00B7 enter view \\u00B7 ctrl+k stop \\u00B7 esc back");\n' +
  '\t\tif (notes.length > 0) rows.push(truncateToWidth(currentTheme.dim(`  ${notes.join("  \\u00B7  ")}`), width));\n' +
  '\t\treturn rows;\n' +
  '\t}\n' +
  '};\n';

splice('the footer component\'s head', 'var FooterComponent = class {', helpers + 'var FooterComponent = class {');

splice('the footer\'s two-line return',
  '\t\treturn [truncateToWidth(line1, width), truncateToWidth(line2, width)];',
  '\t\treturn [truncateToWidth(line1, width), truncateToWidth(line2, width), ...kmodsAgentDock.lines(width)];');

// ------------------------------------------------------------ 4. navigation
//
// Walk the subagent dock with the arrow keys, and open one to watch it work.
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
  '\t/** Stop the highlighted agent. Foreground ones go through their turn\n' +
  '\t*  cancel, background ones through the task registry — the same two\n' +
  '\t*  paths /btw and the tasks browser use. The row stays: the dock shows\n' +
  '\t*  the kill as `✗ [Failed]` like any other ended agent, and the\n' +
  '\t*  selection moves nowhere, so a second `s` cannot hit the wrong row. */\n' +
  '\tstop(host) {\n' +
  '\t\tconst record = this.selectedRecord();\n' +
  '\t\tif (record === void 0 || record.status !== "running") return false;\n' +
  '\t\tconst session = host?.session;\n' +
  '\t\tif (session === void 0) return false;\n' +
  '\t\tlet taskId;\n' +
  '\t\tfor (const info of host.backgroundTasks?.values() ?? []) {\n' +
  '\t\t\tif (info.kind === "agent" && info.agentId === record.agentId) { taskId = info.taskId; break; }\n' +
  '\t\t}\n' +
  '\t\tif (taskId !== void 0) {\n' +
  '\t\t\tsession.stopBackgroundTask(taskId, { reason: "Stopped from the agent dock" }).catch(() => {});\n' +
  '\t\t} else if (host.harness !== void 0 && typeof host.harness.withInteractiveAgent === "function") {\n' +
  '\t\t\thost.harness.withInteractiveAgent(record.agentId, () => session.cancel()).catch(() => {});\n' +
  '\t\t}\n' +
  '\t\t// The engine\'s own events will mark the record failed when the kill\n' +
  '\t\t// settles. Until then the dock says so itself — and the row leaves\n' +
  '\t\t// after three seconds instead of the usual ten, because a stop you\n' +
  '\t\t// ordered needs no linger.\n' +
  '\t\trecord.status = "failed";\n' +
  '\t\trecord.endedAt = Date.now();\n' +
  '\t\trecord.dockStopped = true;\n' +
  '\t\tkmodsAgentDock.stoppedAt = record.endedAt;\n' +
  '\t\thost.state.ui.requestRender();\n' +
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
// `handleInput` sits on the editor, the host one scope up — the stop key
// needs both, so the composer setup parks the host on the editor itself.
splice('the dock host hand-off',
  '\t\teditor.onDownArrowEmpty = () => host.btwPanelController.scroll("down");',
  '\t\teditor.kmodsDockHost = host;\n' +
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

// `ctrl+k` stops the highlighted agent. It lives at the top of `handleInput`
// rather than on a named handler — Kimi gives the composer no plain-letter
// hook, and the key only exists while the composer is empty and a row is
// selected, so it can never eat input meant as text. Not a bare letter:
// `s` collides with typing the moment the composer has content, `ctrl+s`
// already belongs to Kimi (`editor.onCtrlS`), and `ctrl+t` toggles the todo
// list (`onToggleTodoExpand`). `ctrl+k` is free and carries the association.
splice('the composer stop key',
  '\thandleInput(data) {\n' +
  '\t\tconst normalized = normalizeCapsLockedCtrl(data);',
  '\thandleInput(data) {\n' +
  '\t\tconst normalized = normalizeCapsLockedCtrl(data);\n' +
  '\t\tif (typeof kmodsAgentDockNav !== "undefined" && kmodsAgentDock.selected >= 0 &&\n' +
  '\t\t\t\tthis.getText() === "" && matchesKey(normalized, Key.ctrl("k")) &&\n' +
  '\t\t\t\tkmodsAgentDockNav.stop(this.kmodsDockHost)) return;');

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

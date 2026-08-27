// Let AgentSwarm run detached from the turn, the way a single Agent can.
//
// THE GAP
// `Agent(run_in_background=true)` returns at once and reports back later.
// `AgentSwarm` cannot: it holds the turn until its last member is done, so the
// composer is dead for minutes. That is not an oversight in the tool — it is
// what the tool *is*:
//
//   return renderSwarmResults((await this.swarmService.run({ … })));
//
// The swarm's return value is the collected answers of every member. There is
// no seam where an `await` could simply be dropped.
//
// WHY THE OBVIOUS FIX DOES NOT WORK
// Each task the swarm builds already carries `runInBackground: false`, and
// flipping it does change how a member is announced — `subagent.spawned`
// carries the flag, the handler files it under `backgroundAgentMetadata` and
// counts it in the footer badge. But the batch still awaits `handle.completion`
// per member, and nothing registers a task, so no result would ever be
// delivered back to the model. The flag alone buys the appearance of a
// background run without its plumbing.
//
// WHAT MAKES A BACKGROUND RUN
// One line, in the `Agent` tool:
//
//   taskId = this.tasks.registerTask(new SubagentTask(handle, description, controller), { detached: true, … });
//
// A registered task is what gets an id, an entry in `/tasks`, and — the point —
// an automatic notification carrying its output when it settles. The swarm tool
// has no task service at all, which is the actual reason it cannot detach.
//
// WHAT THIS PATCH DOES
// Gives it one, and registers the *swarm* as a single task rather than its
// members as many. The members stay foreground children of that task, exactly
// as they are today — the batch, the retries, the rate limiting and the
// per-member events all keep working untouched. Only the waiting moves: the
// promise that would have been awaited becomes the task's completion, and the
// tool returns an id immediately.
//
// That choice is deliberate. Registering each member separately would mean
// rebuilding the swarm's result collection — `renderSwarmResults` renders all
// members into one document, and a swarm half-reported is worse than one
// reported late. One task, one notification, the same combined output the model
// would have received anyway, only in a later turn.
//
// WHAT IT COSTS
// The combined result arrives a turn later, and a swarm no longer aborts with
// the turn that launched it — it is a background task now, so `/tasks` and
// `TaskStop` are how it is cancelled. `swarmMode` is left to its own
// `shouldAutoExit`, which already ends it at turn end.
//
// ------------------------------------------------------------------ settings
//
// Follows `agent_background` in patch-settings.conf, and therefore `agent_dock`
// as well:
//   default    the swarm blocks the turn, as Kimi ships it
//   always     the swarm runs detached
//   immediate  like always, and the turn ends at dispatch (stopTurn)
// Requires patches/86-agent-background-default.js to be in the same run; on its
// own the single-agent path would still be left to the model.

const DOCK = String(settings.get('agent_dock', 'off')).toLowerCase();
const CHOSEN = String(settings.get('agent_background', 'default')).toLowerCase();
const MODE = DOCK === 'off' ? CHOSEN : (CHOSEN === 'immediate' ? 'immediate' : 'always');

if (MODE !== 'always' && MODE !== 'immediate') {
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

// Already applied? The task class is the first thing this patch writes and
// the most specific string it owns — if it is in the bundle, the names below
// are ours, and the verdict belongs to the contract, not the name guard.
if (out.includes('var KmodsSwarmTask = class {')) {
  throw new Error('already patched');
}

for (const name of ['KmodsSwarmTask', 'kmodsSwarmResult']) {
  if (out.includes(name)) {
    throw new Error(`the name ${name} is already taken in this bundle`);
  }
}

// ------------------------------------------------------------------ the task
//
// The shape a task has to satisfy is small: a `kind`, an `idPrefix`, a
// `description`, `start(sink)` and `toInfo(base)`. This one mirrors
// `SubagentTask` — the same abort wiring, the same settle calls — but waits on
// the swarm's combined result instead of a single agent's completion.
//
// `kind: "agent"` rather than a kind of its own: the task browser and the
// notification text branch on it, and every reader of `agentId` already guards
// against it being absent (`info.kind !== "agent" || info.agentId === void 0`).
// A new kind would fall through all of them into a default nobody wrote.
splice('the swarm tool\'s fields',
  '\tAgentSwarmTool = class AgentSwarmTool {\n' +
  '\t\tswarmService;\n' +
  '\t\tswarmMode;',
  'var KmodsSwarmTask = class {\n' +
  '\tcompletion;\n' +
  '\tdescription;\n' +
  '\tabortController;\n' +
  '\tagentCount;\n' +
  '\tkind = "agent";\n' +
  '\tidPrefix = "swarm";\n' +
  '\tagentId;\n' +
  '\tsubagentType = "swarm";\n' +
  '\tparentToolCallId;\n' +
  '\tmodel;\n' +
  '\tthinkingEffort;\n' +
  '\tconstructor(completion, description, abortController, agentCount, parentToolCallId) {\n' +
  '\t\tthis.completion = completion;\n' +
  '\t\tthis.description = description;\n' +
  '\t\tthis.abortController = abortController;\n' +
  '\t\tthis.agentCount = agentCount;\n' +
  '\t\tthis.parentToolCallId = parentToolCallId;\n' +
  '\t}\n' +
  '\tasync start(sink) {\n' +
  '\t\tconst requestAbort = () => {\n' +
  '\t\t\tthis.abortController.abort(sink.signal.reason);\n' +
  '\t\t};\n' +
  '\t\tif (sink.signal.aborted) requestAbort();\n' +
  '\t\telse sink.signal.addEventListener("abort", requestAbort, { once: true });\n' +
  '\t\ttry {\n' +
  '\t\t\tsink.appendOutput(await this.completion);\n' +
  '\t\t\tawait sink.settle({ status: "completed" });\n' +
  '\t\t} catch (error) {\n' +
  '\t\t\tconst message = error instanceof Error ? error.message : String(error);\n' +
  '\t\t\tif (sink.signal.aborted) {\n' +
  '\t\t\t\tawait sink.settle({ status: "killed" });\n' +
  '\t\t\t} else {\n' +
  '\t\t\t\tawait sink.settle({\n' +
  '\t\t\t\t\tstatus: "failed",\n' +
  '\t\t\t\t\tstopReason: message\n' +
  '\t\t\t\t});\n' +
  '\t\t\t}\n' +
  '\t\t} finally {\n' +
  '\t\t\tsink.signal.removeEventListener("abort", requestAbort);\n' +
  '\t\t}\n' +
  '\t}\n' +
  '\ttoInfo(base) {\n' +
  '\t\treturn {\n' +
  '\t\t\t...base,\n' +
  '\t\t\tkind: "agent",\n' +
  '\t\t\tagentId: this.agentId,\n' +
  '\t\t\tsubagentType: this.subagentType,\n' +
  '\t\t\tparentToolCallId: this.parentToolCallId,\n' +
  '\t\t\tmodel: this.model,\n' +
  '\t\t\tthinkingEffort: this.thinkingEffort\n' +
  '\t\t};\n' +
  '\t}\n' +
  '};\n' +
  '\tAgentSwarmTool = class AgentSwarmTool {\n' +
  '\t\tswarmService;\n' +
  '\t\tkmodsTasks;\n' +
  '\t\tswarmMode;');

// ------------------------------------------------------- the service, injected
//
// Appended as the last constructor parameter so every existing index keeps its
// meaning; the container resolves it the same way the `Agent` tool's does.
splice('the swarm tool\'s constructor',
  '\t\tconstructor(swarmService, scopeContext, swarmMode, config, flags, subagents, profile) {\n' +
  '\t\t\tthis.swarmService = swarmService;',
  '\t\tconstructor(swarmService, scopeContext, swarmMode, config, flags, subagents, profile, kmodsTasks) {\n' +
  '\t\t\tthis.kmodsTasks = kmodsTasks;\n' +
  '\t\t\tthis.swarmService = swarmService;');

// The whole block, not just its last line: `__decorateParam(6, …)` with that
// same service appears elsewhere too.
splice('the swarm tool\'s decorators',
  '\tAgentSwarmTool = __decorate([\n' +
  '\t\t__decorateParam(0, ISessionSwarmService),\n' +
  '\t\t__decorateParam(1, IAgentScopeContext),\n' +
  '\t\t__decorateParam(2, IAgentSwarmService),\n' +
  '\t\t__decorateParam(3, IConfigService),\n' +
  '\t\t__decorateParam(4, IFlagService),\n' +
  '\t\t__decorateParam(5, ISessionSubagentService),\n' +
  '\t\t__decorateParam(6, IAgentProfileService)',
  '\tAgentSwarmTool = __decorate([\n' +
  '\t\t__decorateParam(0, ISessionSwarmService),\n' +
  '\t\t__decorateParam(1, IAgentScopeContext),\n' +
  '\t\t__decorateParam(2, IAgentSwarmService),\n' +
  '\t\t__decorateParam(3, IConfigService),\n' +
  '\t\t__decorateParam(4, IFlagService),\n' +
  '\t\t__decorateParam(5, ISessionSubagentService),\n' +
  '\t\t__decorateParam(6, IAgentProfileService),\n' +
  '\t\t__decorateParam(7, IAgentTaskService)');

// ------------------------------------------------------------- the detachment
//
// The promise is built exactly as before — same call, same mapping — and then
// handed to a task instead of being awaited. Should registration fail (the task
// limit is the realistic case), the swarm is awaited after all rather than
// abandoned: a slow answer beats a lost one.
splice('the swarm tool\'s result',
  '\t\t\treturn renderSwarmResults((await this.swarmService.run({\n' +
  '\t\t\t\tcallerAgentId: this.callerAgentId,\n' +
  '\t\t\t\ttasks\n' +
  '\t\t\t})).map(({ task, ...result }) => ({\n' +
  '\t\t\t\tspec: task.data,\n' +
  '\t\t\t\t...result\n' +
  '\t\t\t})));',
  '\t\t\tconst kmodsSwarmResult = this.swarmService.run({\n' +
  '\t\t\t\tcallerAgentId: this.callerAgentId,\n' +
  '\t\t\t\ttasks\n' +
  '\t\t\t}).then((results) => renderSwarmResults(results.map(({ task, ...result }) => ({\n' +
  '\t\t\t\tspec: task.data,\n' +
  '\t\t\t\t...result\n' +
  '\t\t\t}))));\n' +
  '\t\t\tif (this.kmodsTasks === void 0) return await kmodsSwarmResult;\n' +
  '\t\t\tconst kmodsController = new AbortController();\n' +
  '\t\t\tlet kmodsTaskId;\n' +
  '\t\t\ttry {\n' +
  '\t\t\t\tkmodsTaskId = this.kmodsTasks.registerTask(new KmodsSwarmTask(\n' +
  '\t\t\t\t\tkmodsSwarmResult,\n' +
  '\t\t\t\t\targs.description,\n' +
  '\t\t\t\t\tkmodsController,\n' +
  '\t\t\t\t\ttasks.length,\n' +
  '\t\t\t\t\ttoolCallId\n' +
  '\t\t\t\t), {\n' +
  '\t\t\t\t\tdetached: true,\n' +
  '\t\t\t\t\ttimeoutMs\n' +
  '\t\t\t\t});\n' +
  '\t\t\t} catch {\n' +
  '\t\t\t\treturn await kmodsSwarmResult;\n' +
  '\t\t\t}\n' +
  '\t\t\treturn [\n' +
  '\t\t\t\t`task_id: ${kmodsTaskId}`,\n' +
  '\t\t\t\t"status: running",\n' +
  '\t\t\t\t`agents: ${String(tasks.length)}`,\n' +
  '\t\t\t\t"automatic_notification: true",\n' +
  '\t\t\t\t"",\n' +
  '\t\t\t\t`description: ${args.description}`,\n' +
  '\t\t\t\t"",\n' +
  '\t\t\t\t"next_step: This turn is OVER. The swarm runs as a background task and its combined result arrives as a <notification> in a future turn. Do NOT call WaitFor, TaskOutput, or any other tool to check on it. Do NOT end your response with a summary of what the swarm will do — end the turn now. If there is nothing else to do, say so briefly and stop. To cancel the swarm, use TaskStop with the task_id above."\n' +
  '\t\t\t].join("\\n");');

// ------------------------------------------------------------- stopTurn
//
// In `immediate` mode the turn ends the moment the swarm is dispatched.
// The execution wrapper reads `{ output: ... }` from `runSwarm`; adding
// `stopTurn: true` there means the loop skips the continuation call and
// the model is never re-invoked.
if (MODE === 'immediate') {
  // The anchor carries the `resolveExecution` tail: `ToolAccesses.all()`
  // without a `$1` suffix is what tells the live v2 copy from the inert v1
  // twin — the `execution` body itself is byte-identical in both.
  splice('the swarm tool\'s execution wrapper',
    '\t\t\t\taccesses: ToolAccesses.all(),\n' +
    '\t\t\t\tdescription: `Launching agent swarm: ${args.description}`,\n' +
    '\t\t\t\tdisplay: {\n' +
    '\t\t\t\t\tkind: "agent_call",\n' +
    '\t\t\t\t\tagent_name: `swarm (${agentCount} subagents)`,\n' +
    '\t\t\t\t\tprompt: args.description\n' +
    '\t\t\t\t},\n' +
    '\t\t\t\tapprovalRule: this.name,\n' +
    '\t\t\t\texecute: (ctx) => this.execution(args, ctx)\n' +
    '\t\t\t};\n' +
    '\t\t}\n' +
    '\t\tasync execution(args, context) {\n' +
    '\t\t\ttry {\n' +
    '\t\t\t\tthis.swarmMode.enter("tool");\n' +
    '\t\t\t\treturn { output: await this.runSwarm(args, context.signal, context.toolCallId) };',
    '\t\t\t\taccesses: ToolAccesses.all(),\n' +
    '\t\t\t\tdescription: `Launching agent swarm: ${args.description}`,\n' +
    '\t\t\t\tdisplay: {\n' +
    '\t\t\t\t\tkind: "agent_call",\n' +
    '\t\t\t\t\tagent_name: `swarm (${agentCount} subagents)`,\n' +
    '\t\t\t\t\tprompt: args.description\n' +
    '\t\t\t\t},\n' +
    '\t\t\t\tapprovalRule: this.name,\n' +
    '\t\t\t\texecute: (ctx) => this.execution(args, ctx)\n' +
    '\t\t\t};\n' +
    '\t\t}\n' +
    '\t\tasync execution(args, context) {\n' +
    '\t\t\ttry {\n' +
    '\t\t\t\tthis.swarmMode.enter("tool");\n' +
    '\t\t\t\tconst kmodsResult = await this.runSwarm(args, context.signal, context.toolCallId);\n' +
    '\t\t\t\tif (typeof kmodsResult === "string" && kmodsResult.includes("task_id:")) return { output: kmodsResult, stopTurn: true };\n' +
    '\t\t\t\treturn { output: kmodsResult };');
}

return out;

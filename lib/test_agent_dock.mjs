// What 82-agent-dock.js splices in, run for real.
//
// The fixture below is not the bundle — it is the smallest thing that carries
// the seven anchors the patch reaches for, in the shape the bundle spells
// them. That is deliberate on both counts: the patch runs unmodified, so a
// drifted anchor fails here as loudly as it would during a patch run, and the
// spliced code then executes against stand-ins for the three globals it
// touches (`currentTheme`, `truncateToWidth`, `SubagentActivityStore`), so the
// row it draws can be compared character for character.
//
// Run: node lib/test_agent_dock.mjs

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PATCH = readFileSync(join(HERE, '..', 'patches', '82-agent-dock.js'), 'utf8');

// The anchors, spelled the way the bundle spells them — tabs and all.
const FIXTURE = `var SubagentActivityStore = class {
	records = /* @__PURE__ */ new Map();
	ensureRecord(spawn) {
		const existing = this.records.get(spawn.agentId);
		if (existing !== void 0) {
			existing.status = "running";
			existing.resultSummary = void 0;
			existing.error = void 0;
			return existing;
		}
		const record = {
			agentId: spawn.agentId,
			agentName: spawn.agentName,
			description: spawn.description,
			parentToolCallId: spawn.parentToolCallId,
			model: spawn.model,
			effort: spawn.effort,
			steps: [],
			totalSteps: 0,
			status: "running",
			version: 0
		};
		this.records.set(spawn.agentId, record);
		return record;
	}
	get(agentId) {
		return this.records.get(agentId);
	}
	agentIds() {
		return [...this.records.keys()];
	}
	drop(agentId) {
		this.records.delete(agentId);
	}
	recordFor(agentId) {
		return this.records.get(agentId) ?? this.ensureRecord({
			agentId,
			agentName: agentId,
			parentToolCallId: ""
		});
	}
	findToolCall(record, toolCallId) {
		for (const step of record.steps) {
			const hit = step.toolCalls.find((c) => c.id === toolCallId);
			if (hit !== void 0) return hit;
		}
	}
	currentStep(record) {
		let step = record.steps.at(-1);
		if (step === void 0) {
			step = { step: 1, textTail: "", toolCalls: [] };
			record.steps.push(step);
		}
		return step;
	}
	dropStreamingBuffers() {}
	clear() {
		this.records.clear();
	}
	bump(record) {
		record.version += 1;
	}
	markCompleted(agentId, resultSummary) {
		const record = this.records.get(agentId);
		if (record === void 0) return;
		record.status = "completed";
		record.resultSummary = resultSummary;
		this.dropStreamingBuffers(agentId);
		this.bump(record);
	}
	markFailed(agentId, error) {
		const record = this.records.get(agentId);
		if (record === void 0) return;
		record.status = "failed";
		record.error = error;
		this.dropStreamingBuffers(agentId);
		this.bump(record);
	}
	applyEvent(event) {
		switch (event.type) {
			case "turn.step.started": {
				const record = this.recordFor(event.agentId);
				record.steps.push({ step: event.step, textTail: "", toolCalls: [] });
				record.totalSteps += 1;
				this.bump(record);
				return;
			}
			case "tool.call.started": {
				const record = this.recordFor(event.agentId);
				const existing = this.findToolCall(record, event.toolCallId);
				const args = capArgStrings(argsRecord(event.args));
				if (existing === void 0) this.currentStep(record).toolCalls.push({
					id: event.toolCallId,
					name: event.name,
					args,
					status: "running",
					startedAt: Date.now()
				});
				else {
					existing.name = event.name;
					existing.args = args;
				}
				this.bump(record);
				return;
			}
			case "tool.result": {
				const record = this.records.get(event.agentId);
				const call = record === void 0 ? void 0 : this.findToolCall(record, event.toolCallId);
				if (record === void 0 || call === void 0) return;
				call.status = event.isError === true ? "error" : "done";
				this.bump(record);
				return;
			}
			case "tool.call.delta": {
				const record = this.recordFor(event.agentId);
				let call = this.findToolCall(record, event.toolCallId);
				if (call === void 0) {
					call = {
						id: event.toolCallId,
						name: event.name ?? "",
						args: {},
						status: "running",
						startedAt: Date.now()
					};
					this.currentStep(record).toolCalls.push(call);
				}
				if (call.name.length === 0 && event.name !== void 0) call.name = event.name;
				this.bump(record);
				return;
			}
		}
	}
};
var SubagentEventHandler = class {
	activityStore = new SubagentActivityStore();
	backgroundAgentMetadata = /* @__PURE__ */ new Map();
	subagentInfo = /* @__PURE__ */ new Map();
	agentSwarmProgress = /* @__PURE__ */ new Map();
	deps = { backgroundTasks: /* @__PURE__ */ new Map() };
	clearAgentSwarmProgress() {
		for (const progress of this.agentSwarmProgress.values()) progress.dispose();
		this.agentSwarmProgress.clear();
	}
	resetRuntimeState() {
		this.subagentInfo.clear();
		this.backgroundAgentMetadata.clear();
		this.activityStore.clear();
		this.clearAgentSwarmProgress();
	}
	pruneForegroundOnlyRecord(subagentId) {
		if (this.backgroundAgentMetadata.has(subagentId)) return;
		this.activityStore.drop(subagentId);
	}
	dropForegroundOnlyActivityRecords() {
		for (const agentId of this.activityStore.agentIds()) this.pruneForegroundOnlyRecord(agentId);
	}
};
var FooterComponent = class {
	render(width) {
		const line1 = "yolo  K3";
		const line2 = "context: 14%";
		return [truncateToWidth(line1, width), truncateToWidth(line2, width)];
	}
};
var EditorKeyboard = class {
	constructor(host, editor) {
		this.host = host;
		this.editor = editor;
	}
	install() {
		const host = this.host;
		const editor = this.editor;
		editor.onSubmit = (text) => {
			host.handleUserInput(text);
		};
		editor.onEscape = () => {
			host.escaped = true;
		};
		editor.onUpArrowEmpty = () => {
			if (host.btwPanelController.scroll("up")) return true;
			return false;
		};
		editor.onDownArrowEmpty = () => host.btwPanelController.scroll("down");
	}
};
// The editor in the real bundle is a class with handleInput as a method —
// the patch anchors on that shape, so the fixture keeps it too.
var FixtureEditor = class {
	constructor(host) {
		this.host = host;
	}
	getText() {
		return this.host.editorText ?? '';
	}
	handleInput(data) {
		const normalized = normalizeCapsLockedCtrl(data);
		this.host.lastInput = normalized;
	}
};
// The footer agent badge, copied the way the real bundle writes it — the
// patch removes exactly this block and fails loudly when it is absent, so
// the fixture has to carry it (backticks escaped for the template).
var FixtureFooter = class {
	buildSlots() {
		const taskBadges = [];
		if (this.backgroundAgentCount > 0) {
			const noun = this.backgroundAgentCount === 1 ? "agent" : "agents";
			taskBadges.push(chalk.hex(colors.primary)(\`[\${String(this.backgroundAgentCount)} \${noun} running]\`));
		}
		return taskBadges;
	}
};
`;

// Two globals the fixture's own code mentions but never exercises here.
const PRELUDE = 'const capArgStrings = (a) => a;\nconst argsRecord = (a) => a ?? {};\nconst normalizeCapsLockedCtrl = (d) => d;\nconst Key = { ctrl: (c) => String.fromCharCode(c.charCodeAt(0) - 96) };\nconst matchesKey = (d, k) => d === k;\n';
// The same byte in the test's own scope: ctrl+k.
const CTRL_K = '\x0b';

function applyPatch(mode) {
  const settings = { get: (key, fallback = '') => (key === 'agent_dock' ? mode : fallback) };
  const out = new Function('js', 'settings', PATCH)(FIXTURE, settings);
  if (typeof out !== 'string') throw new Error(`the patch returned ${typeof out}`);
  return out;
}

const strip = (s) => s.replace(/\x1b\[[0-9;]*m/g, '');

function load(patched) {
  const currentTheme = { dim: (s) => s, fg: (_c, s) => s };
  const visibleWidth = (s) => strip(s).length;
  const truncateToWidth = (s, w) =>
    strip(s).length <= w ? s : strip(s).slice(0, Math.max(0, w - 1)) + '…';
  return new Function(
    'currentTheme', 'truncateToWidth', 'visibleWidth',
    `${PRELUDE}${patched}\nreturn { dock: kmodsAgentDock, Store: SubagentActivityStore, Handler: SubagentEventHandler, Footer: FooterComponent };`
  )(currentTheme, truncateToWidth, visibleWidth);
}

let failures = 0;
const check = (label, cond) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}`);
  if (!cond) failures++;
};

const NOW = 1700000000000;

function suite(mode) {
  console.log(`\nagent_dock = ${mode}:`);
  const { dock, Store, Handler, Footer } = load(applyPatch(mode));

  // The bundle builds exactly one store, as a field of the event handler, and
  // the footer finds it through the static `current`. Building one directly
  // here would leave `current` pointing at whichever was constructed last —
  // so the test takes the same route the bundle does.
  const handler = new Handler();
  const store = handler.activityStore;
  check('the footer finds the handler\'s store', Store.current === store);

  check('an empty dock costs no lines', dock.lines(120).length === 0);
  check('the footer still returns its own two lines',
    new Footer().render(80).length === 2);

  const a1 = store.ensureRecord({
    agentId: 'a1', agentName: 'explore', description: 'Bus-Repo analysieren',
    model: 'K3', effort: 'high',
  });
  check('a spawned record carries a start time', typeof a1.startedAt === 'number');
  check('a spawned record starts at zero tools', a1.toolCount === 0);

  // Freeze the clock so the elapsed field is comparable.
  a1.startedAt = NOW - 196_000;
  const realNow = Date.now;
  Date.now = () => NOW;
  try {
    store.applyEvent({ type: 'agent.status.updated', agentId: 'a1', contextTokens: 68_000 });
    check('a status event lands the context size', a1.contextTokens === 68_000);

    for (let i = 0; i < 27; i++) {
      store.applyEvent({ type: 'tool.call.started', agentId: 'a1', toolCallId: `t${i}`, args: {} });
    }
    store.applyEvent({ type: 'tool.call.started', agentId: 'a1', toolCallId: 't3', args: {} });
    check('tool calls are counted once each', a1.toolCount === 27);

    // A call whose arguments stream in is created by `tool.call.delta`, and
    // `tool.call.started` then finds it already there. Counting only in the
    // latter read `0 tools` on screen next to a live `Read benutzer-alltag.md`.
    store.applyEvent({ type: 'tool.call.delta', agentId: 'a1', toolCallId: 's1', name: 'Read' });
    check('a streamed call is counted too', a1.toolCount === 28);
    store.applyEvent({ type: 'tool.call.started', agentId: 'a1', toolCallId: 's1', name: 'Read', args: { file_path: '/x/benutzer-alltag.md' } });
    check('and not a second time when it starts', a1.toolCount === 28);
    check('the row names what it is doing',
      dock.task(a1) === 'Read /x/benutzer-alltag.md');

    // A call whose arguments are still streaming carries a name and nothing
    // else. Showing it would read `Write` — a tool with no target, which says
    // where nothing is happening. The last complete call stands in until the
    // arguments land.
    store.applyEvent({ type: 'tool.call.delta', agentId: 'a1', toolCallId: 's2', name: 'Write' });
    check('a target-less call does not blank the field',
      dock.task(a1) === 'Read /x/benutzer-alltag.md');
    store.applyEvent({ type: 'tool.call.started', agentId: 'a1', toolCallId: 's2', name: 'Write', args: { file_path: '/x/audit-evidenz.md' } });
    check('and gives way once the target arrives',
      dock.task(a1) === 'Write /x/audit-evidenz.md');

    // The bullet is a state light with four states, no timers: empty when
    // idle, grey while a call is out, green on the last result coming back
    // clean, red on it coming back bad. The state persists until the next
    // event changes it.
    // Earlier checks left calls open on purpose; start from a clean slate.
    a1.openCalls = 0;
    delete a1.lastResultAt;
    delete a1.lastResultError;
    const bullet = (r) => strip(dock.line(r, 200)).trimStart()[0];
    check('an idle agent shows the empty circle', bullet(a1) === '◯');
    store.applyEvent({ type: 'tool.call.started', agentId: 'a1', toolCallId: 'c1', name: 'Bash', args: {} });
    check('a call in flight shows the grey filled circle', bullet(a1) === '●' && a1.openCalls === 1);
    store.applyEvent({ type: 'tool.call.started', agentId: 'a1', toolCallId: 'c2', name: 'Read', args: {} });
    check('two at once are counted', a1.openCalls === 2);
    check('still grey with two calls out', bullet(a1) === '●');
    store.applyEvent({ type: 'tool.result', agentId: 'a1', toolCallId: 'c1', output: 'ok' });
    check('a result turns it green even with one still out', bullet(a1) === '●' && a1.openCalls === 1);
    store.applyEvent({ type: 'tool.result', agentId: 'a1', toolCallId: 'c2', output: 'ok' });
    check('green after the last result returns', bullet(a1) === '●' && a1.openCalls === 0);

    // The blink is anchored at each record's own event, not a global clock:
    // two agents whose calls started a different moment ago sit in different
    // phases of the same 1700 ms cycle.
    const ph1 = store.ensureRecord({ agentId: 'ph1', agentName: 'p1' });
    const ph2 = store.ensureRecord({ agentId: 'ph2', agentName: 'p2' });
    ph1.openCalls = 1; ph1.lastCallAt = Date.now();
    ph2.openCalls = 1; ph2.lastCallAt = Date.now() - 1300;
    check('rows blink on their own phase', bullet(ph1) === '●' && bullet(ph2) === '◯');
    store.drop('ph1');
    store.drop('ph2');

    // A new call starting resets the indicator back to grey.
    store.applyEvent({ type: 'tool.call.started', agentId: 'a1', toolCallId: 'c3', name: 'Bash', args: {} });
    check('a new call resets to grey', bullet(a1) === '●' && a1.openCalls === 1);
    store.applyEvent({ type: 'tool.result', agentId: 'a1', toolCallId: 'c3', output: 'boom', isError: true });
    check('a failure turns it red', bullet(a1) === '●');
    check('and stamps the error flag', a1.lastResultError === true);
    // A new call starting clears the error state back to grey.
    store.applyEvent({ type: 'tool.call.started', agentId: 'a1', toolCallId: 'c4', name: 'Read', args: {} });
    check('a new call after failure resets to grey', bullet(a1) === '●' && a1.openCalls === 1);
    store.applyEvent({ type: 'tool.result', agentId: 'a1', toolCallId: 'c4', output: 'ok' });
    check('green after it returns ok', bullet(a1) === '●');

    // Terminal states: completed shows ✓, failed shows ✗.
    a1.status = 'completed';
    check('a completed agent shows the tick', bullet(a1) === '✓');
    a1.status = 'failed';
    check('a failed agent shows the cross', bullet(a1) === '✗');
    a1.status = 'running';
    a1.toolCount = 27;
    a1.steps.length = 0;
    delete a1.lastResultAt;
    delete a1.lastResultError;
    a1.openCalls = 0;

    // A shell command stays whole while it fits; only length shortens it now.
    store.applyEvent({ type: 'tool.call.started', agentId: 'a1', toolCallId: 's3', name: 'Bash', args: { command: 'git status --porcelain' } });
    check('a shell command stays whole', dock.task(a1) === 'Bash git status --porcelain');

    // Bars of several agents have to share a left edge to be comparable.
    const other = store.ensureRecord({ agentId: 'a1b', agentName: 'x', description: 'kurz' });
    other.startedAt = NOW;
    const bars = dock.lines(100).map(strip).filter((l) => l.includes('['));
    check('every row fits the width', bars.every((l) => l.length <= 100));
    check('the bars line up',
      new Set(bars.map((l) => l.indexOf('['))).size === 1);
    check('every name gets a number', bars.some((l) => l.includes('x #1')));
    store.drop('a1b');

    // Agents launched together leave together: a finished one waits for its
    // siblings, and the ten seconds start when the last of them is done.
    if (mode === 'all') {
      store.records.clear();
      const cohort = ['c1', 'c2', 'c3'].map((id) => {
        const r = store.ensureRecord({ agentId: id, agentName: id });
        r.startedAt = NOW;
        return r;
      });
      check('agents started together share a cohort',
        new Set(cohort.map((r) => r.dockGroup)).size === 1);

      store.markCompleted('c1');
      cohort[0].endedAt = NOW - 60_000;
      check('a finished agent waits for its siblings',
        dock.records().length === 3);

      store.markCompleted('c2');
      store.markCompleted('c3');
      cohort[1].endedAt = NOW - 60_000;
      cohort[2].endedAt = NOW - 5_000;
      check('the cohort stays until the last one is ten seconds done',
        dock.records().length === 3);
      cohort[2].endedAt = NOW - 11_000;
      check('then all of them go at once', dock.records().length === 0);

      // An agent starting alone opens its own cohort and keeps its own clock.
      store.records.clear();
      const lone = store.ensureRecord({ agentId: 'l1', agentName: 'lone' });
      lone.startedAt = NOW;
      const later = store.ensureRecord({ agentId: 'l2', agentName: 'later' });
      check('a second agent joins the running one', later.dockGroup === lone.dockGroup);
      store.markCompleted('l1');
      store.markCompleted('l2');
      lone.endedAt = later.endedAt = NOW - 11_000;
      store.records.clear();
      const solo = store.ensureRecord({ agentId: 's1', agentName: 'solo' });
      solo.startedAt = NOW;
      check('after everyone left, the next agent opens a fresh cohort',
        solo.dockGroup !== lone.dockGroup);

      // No room to spare: finished agents step aside so working ones show.
      store.records.clear();
      const busy = [];
      for (let i = 0; i < 5; i++) {
        const r = store.ensureRecord({ agentId: `w${i}`, agentName: `w${i}` });
        r.startedAt = NOW;
        busy.push(r);
      }
      const done = store.ensureRecord({ agentId: 'd1', agentName: 'done' });
      done.startedAt = NOW;
      store.markCompleted('d1');
      done.endedAt = NOW - 1_000;
      check('a full dock drops the finished one at once',
        dock.records().length === 5 && !dock.records().includes(done));
      check('and its cohort is dissolved', done.dockAlone === true);
      store.markCompleted('w0');
      busy[0].endedAt = NOW - 5_000;
      check('a detached agent then keeps its own ten seconds',
        dock.records().includes(done));
      done.endedAt = NOW - 11_000;
      check('and goes when they are up', !dock.records().includes(done));
      store.records.clear();
      store.records.set('a1', a1);
    }

    // A background agent outlives the turn it was started in. The reset that
    // runs at the start of every turn must not take its record with it, or the
    // row loses its name and model mid-flight while its tool count keeps
    // climbing — the elapsed time jumping back to zero was how that showed.
    store.records.clear();
    const survivor = store.ensureRecord({
      agentId: 'bg1', agentName: 'coder', description: 'laeuft weiter',
      model: 'K3', effort: 'high',
    });
    survivor.startedAt = NOW - 90_000;
    survivor.toolCount = 7;
    handler.subagentInfo.set('bg1', { name: 'coder' });
    handler.backgroundAgentMetadata.set('bg1', { agentId: 'bg1' });
    const gone = store.ensureRecord({ agentId: 'fg1', agentName: 'explore' });
    store.markCompleted('fg1');
    handler.subagentInfo.set('fg1', { name: 'explore' });

    handler.resetRuntimeState();
    check('a running agent survives the turn reset', store.get('bg1') === survivor);
    check('with its name and model intact',
      store.get('bg1').agentName === 'coder' && store.get('bg1').model === 'K3');
    check('and its elapsed time unbroken', store.get('bg1').startedAt === NOW - 90_000);
    check('its routing info is kept too', handler.subagentInfo.has('bg1'));
    check('a finished one with an end time is preserved', store.get('fg1') !== void 0);
    check('and its routing info with it', handler.subagentInfo.has('fg1'));
    store.records.clear();
    handler.subagentInfo.clear();
    handler.backgroundAgentMetadata.clear();
    store.records.set('a1', a1);
    void gone;

    // A swarm spawns its members from one profile, so the rows would read
    // `coder`, `coder`, `coder` with the same description — indistinguishable.
    for (const id of ['t1', 't2', 't3']) {
      const r = store.ensureRecord({ agentId: id, agentName: 'coder', description: 'docs schreiben' });
      r.startedAt = NOW;
    }
    const twins = dock.lines(100).map(strip);
    check('same-named agents are numbered',
      twins.filter((l) => l.includes('coder #')).length === 3);
    check('the numbers are distinct',
      ['#1', '#2', '#3'].every((n) => twins.some((l) => l.includes(`coder ${n}`))));
    // The description rides in the row again, capped at two words — enough to
    // tell "docs schreiben" apart from "code lesen" without buying the sentence.
    check('descriptions show as two words',
      twins.filter((l) => l.includes('coder #')).every((l) => l.includes('docs schreiben')));

    // With only the three swarm members left, the description is the same on
    // every row — it still shows; telling them apart is the number's job.
    // The key legend is a standing line now and is filtered out of row
    // counts everywhere below.
    store.drop('a1');
    const swarm = dock.lines(100).map(strip).filter((l) => !l.includes('enter view'));
    check('a shared description still shows',
      swarm.length === 3 && swarm.every((l) => l.includes('docs schreiben')));
    check('the name and number survive',
      swarm.every((l) => /coder #\d/.test(l)));

    // A number must not move when its neighbours finish. Deriving it from the
    // current list made `coder #1` become plain `coder` the moment it was the
    // last one standing — which reads as a different agent entirely.
    store.drop('t2');
    store.drop('t3');
    const alone = dock.lines(100).map(strip).filter((l) => !l.includes('enter view'));
    check('the last one standing keeps its number',
      alone.length === 1 && alone[0].includes('coder #1'));
    for (const id of ['t1']) store.drop(id);
    store.records.set('a1', a1);

    // Put a1 back the way the row checks below expect it: the checks above
    // deliberately took its context size away and left calls open.
    a1.toolCount = 27;
    a1.totalSteps = 27;
    a1.steps.length = 0;
    a1.contextTokens = 68_000;
    a1.openCalls = 0;
    delete a1.usageTokens;
    delete a1.failedCallAt;
    delete a1.lastCallStartedAt;
    delete a1.lastResultAt;
    delete a1.lastResultError;
    delete a1.failUntil;
    delete a1.failSolo;
    delete a1.description;

    const lines = dock.lines(200).map(strip).filter((l) => !l.includes('enter view'));
    check('a running agent adds exactly one row', lines.length === 1);
    check('there is no main row', !lines.some((l) => l.includes('main')));
    const row = strip(dock.line(a1, 100));
    check('the row carries every field',
      row.trimStart().startsWith('◯ 3:16 [⣿⣿⣿⣿⣿⣿⣿⣀] explore #1 · K3 · high · 27 tools · 68k'));
    check('the bar sits left, after indicator and elapsed',
      row.trimStart().indexOf('[') === 7 && row.length <= 100);

    // The bar is drawn frame by frame rather than computed, so the frames are
    // the specification and belong here character for character.
    const FRAMES = {
      0: '[⣀⣀⣀⣀⣀⣀⣀⣀]',
      2: '[⣿⣀⣀⣀⣀⣀⣀⣀]',
      4: '[⣿⣿⣀⣀⣀⣀⣀⣀]',
      6: '[⣿⣿⣿⣀⣀⣀⣀⣀]',
      8: '[⣿⣿⣿⣿⣀⣀⣀⣀]',
      10: '[⣿⣿⣿⣿⣇⣀⣀⣀]',
      13: '[⣿⣿⣿⣿⣿⣀⣀⣀]',
      16: '[⣿⣿⣿⣿⣿⣇⣀⣀]',
      21: '[⣿⣿⣿⣿⣿⣿⣀⣀]',
      24: '[⣿⣿⣿⣿⣿⣿⣇⣀]',
      27: '[⣿⣿⣿⣿⣿⣿⣿⣀]',
      30: '[⣿⣿⣿⣿⣿⣿⣿⣇]',
    };
    const probe = store.ensureRecord({ agentId: 'bar', agentName: 'b' });
    const barAt = (n) => {
      probe.totalSteps = n;
      return strip(dock.bar(probe));
    };
    const wrong = Object.entries(FRAMES).filter(([n, want]) => barAt(Number(n)) !== want);
    for (const [n, want] of wrong) console.log(`       ${n}: ${barAt(Number(n))} statt ${want}`);
    check('every frame is drawn as specified', wrong.length === 0);
    // A count between two frames holds the lower one until the next is reached.
    check('a count between frames holds the lower one',
      barAt(9) === FRAMES[8] && barAt(12) === FRAMES[10] && barAt(19) === FRAMES[16]);
    check('beyond the last frame nothing changes further',
      barAt(40) === FRAMES[30] && barAt(500) === FRAMES[30]);
    check('every frame is eight cells wide',
      [0, 2, 9, 19, 30, 99].every((n) => barAt(n).length === 10));
    store.drop('bar');
    check('a narrow terminal truncates rather than wraps',
      dock.lines(40).every((l) => strip(l).length <= 40));
    // The separators give up their spacing from the right before anything
    // is cut off, so the numbers pack together while the words stay legible.
    check('separators tighten from the right under pressure',
      strip(dock.line(a1, 56)).includes('tools·68k'));
    check('the leftmost separators are the last to go',
      strip(dock.line(a1, 50)).trimStart().startsWith('◯ 3:16 [') && strip(dock.line(a1, 50)).includes('explore #1·'));
    // Under pressure the description gives way, never the bar: it is the one
    // field that answers "how far along is this".
    const squeezed = strip(dock.line(a1, 46));
    check('the bar survives a squeeze', squeezed.includes('[') && squeezed.includes(']'));
    check('the description is what gives way', squeezed.includes('…'));

    a1.usageTokens = 5;
    check('the context size beats the usage sum', strip(dock.line(a1, 200)).includes('68k'));
    delete a1.contextTokens;
    check('the usage sum is used when no context size arrived',
      strip(dock.line(a1, 200)).includes('0k'));

    // Child events routinely reach the store before `subagent.spawned` does.
    // The placeholder `recordFor` invents must not survive the real spawn, or
    // the row reads `agent-9 · 0 tools` with no description and no model —
    // which is exactly what the first live run showed.
    store.applyEvent({ type: 'agent.status.updated', agentId: 'a9', contextTokens: 100 });
    const early = store.get('a9');
    check('an unheralded event leaves a placeholder', early.agentName === 'a9');
    store.ensureRecord({
      agentId: 'a9', agentName: 'explore', description: 'README lesen',
      model: 'K3', effort: 'high', parentToolCallId: 'tc-1',
    });
    check('the real spawn fills the name in', early.agentName === 'explore');
    check('the real spawn fills the description in', early.description === 'README lesen');
    check('the real spawn fills model and effort in',
      early.model === 'K3' && early.effort === 'high');
    const spawned = strip(dock.line(early, 100));
    check('the row is complete after the spawn',
      spawned.trimStart().startsWith('◯ 0:00 [⣀⣀⣀⣀⣀⣀⣀⣀] explore #1 · K3 · high · 0 tools · 0k · README lesen'));
    // A placeholder name must never overwrite a real one on a later pass.
    store.ensureRecord({ agentId: 'a9', agentName: 'a9' });
    check('a placeholder cannot overwrite a real name', early.agentName === 'explore');
    store.drop('a9');

    // A finished foreground agent: kept on `all`, dropped on `running`.
    const a2 = store.ensureRecord({ agentId: 'a2', agentName: 'coder' });
    a2.status = 'completed';
    a2.startedAt = NOW - 60_000;
    a2.toolCount = 1;
    handler.pruneForegroundOnlyRecord('a2');

    // A swarm member never passes through the pruning, so its record has to
    // be dated where it is marked done — otherwise it counts as stale on the
    // spot and vanishes while the swarm header still reads `✓ Fertig`.
    const a4 = store.ensureRecord({ agentId: 'a4', agentName: 'swarm-1' });
    store.markCompleted('a4', 'fertig');
    check('a completed record carries an end time', typeof a4.endedAt === 'number');
    if (mode === 'all') {
      check('and is therefore still listed',
        dock.lines(200).map(strip).some((l) => l.includes('swarm-1')));
    }
    const a5 = store.ensureRecord({ agentId: 'a5', agentName: 'swarm-2' });
    store.markFailed('a5', 'kaputt');
    check('a failed record carries one too', typeof a5.endedAt === 'number');
    store.drop('a4');
    store.drop('a5');

    if (mode === 'all') {
      check('a finished agent survives pruning', store.get('a2') !== void 0);
      check('it is stamped with an end time', typeof a2.endedAt === 'number');
      const rows = dock.lines(200).map(strip);
      check('a finished agent reads [Finished], not a bar',
        rows.some((l) => l.includes('coder') && l.includes('[Finished]') && !l.includes('⣿')));
      check('one tool reads as singular', rows.some((l) => l.includes('1 tool ·')));
      a2.status = 'failed';
      check('a failed one says so',
        dock.lines(200).map(strip).some((l) => l.includes('[Failed]')));
      a2.status = 'completed';
      // Ten seconds after the last agent finished, the whole dock goes —
      // main row included, because an empty list draws nothing at all.
      a2.endedAt = NOW - 11_000;
      a1.status = 'completed';
      a1.endedAt = NOW - 11_000;
      check('the dock empties ten seconds after the last agent',
        dock.lines(200).length === 0);
      a1.status = 'running';
      delete a1.endedAt;
      store.drop('a2');
    } else {
      check('pruning is left alone', store.get('a2') === void 0);
    }

    // An agent still marked running at turn end was interrupted: it must not
    // be kept, or it would sit in the dock forever pretending to work.
    const a3 = store.ensureRecord({ agentId: 'a3', agentName: 'stuck' });
    handler.pruneForegroundOnlyRecord('a3');
    check('an interrupted agent is still pruned', store.get('a3') === void 0);

    // The turn-end sweep itself never touches a running record: a detached
    // swarm's members are spawned asynchronously and their `subagent.spawned`
    // events can land after the turn has already ended — dropping them there
    // is what brought the dock back as agent-N placeholders.
    const sw = store.ensureRecord({ agentId: 'sw1', agentName: 'coder', parentToolCallId: 'tc-swarm' });
    const swDone = store.ensureRecord({ agentId: 'sw2', agentName: 'coder', parentToolCallId: 'tc-swarm' });
    swDone.status = 'completed';
    swDone.endedAt = NOW;
    handler.dropForegroundOnlyActivityRecords();
    check('the sweep keeps a running record', store.get('sw1') !== void 0);
    if (mode === 'all') {
      check('and still keeps a finished one', store.get('sw2') !== void 0);
    } else {
      check('and still prunes a finished one', store.get('sw2') === void 0);
    }
    store.drop('sw2');

    // A running swarm member is foreground-shaped but belongs to a registered
    // background task through the shared parentToolCallId — a direct prune
    // must keep it too.
    handler.deps.backgroundTasks.set('swarm-1', { kind: 'agent', parentToolCallId: 'tc-swarm' });
    handler.pruneForegroundOnlyRecord('sw1');
    check('a running swarm member survives a direct prune', store.get('sw1') !== void 0);
    handler.deps.backgroundTasks.clear();
    handler.pruneForegroundOnlyRecord('sw1');
    check('and is pruned once no task claims its parent call', store.get('sw1') === void 0);

    // More agents than fit are cycled, never silently dropped. Without a
    // cursor the window is derived from the clock, so it advances on its own
    // as the footer repaints. At the bottom of the list the window is pinned
    // to the end — the note then says "↑ … more" would be wrong, it shows
    // nothing above the window, so it disappears instead of reading 0.
    store.records.clear();
    for (let i = 0; i < 9; i++) {
      const r = store.ensureRecord({ agentId: `r${i}`, agentName: `agent${i}` });
      r.startedAt = NOW;
    }
    const many = dock.lines(200).map(strip);
    check('five agents plus a footer line', many.length === 6);
    check('a footer line says what is off screen', many.at(-1).includes('more') && !many.at(-1).includes('/'));
    check('every clock step keeps the window full', [0, 1].every((p) => {
      Date.now = () => NOW - (NOW % 3000) + p * 3000;
      dock.selected = -1;
      const rows = dock.lines(200);
      // Five agent rows always; the footer line is there only while it has
      // something to say — at the bottom of the list it is not.
      return rows.length >= 5;
    }));
    Date.now = () => NOW;
    dock.selected = -1;

    const pageOf = (t) => {
      Date.now = () => t;
      dock.selected = -1;
      return dock.lines(200).map(strip);
    };
    const first = pageOf(NOW - (NOW % 3000));
    const second = pageOf(NOW - (NOW % 3000) + 3000);
    check('the window advances with the clock', first[0] !== second[0]);
    const seen = new Set();
    for (let p = 0; p < 2; p++) {
      for (const l of pageOf(NOW - (NOW % 3000) + p * 3000)) {
        const trimmed = l.trimStart();
        if (!/^[◯✓✗❯]/.test(trimmed)) continue;
        seen.add(trimmed.replace(/^[^a-z]*/, '').split(' ')[0]);
      }
    }
    check('cycling reaches every agent', seen.size === 9);
    // The last clock page is pinned to the end: five rows show indexes 4-8,
    // nothing is hidden below, and the "↓ N more" note is gone rather than
    // reading "0 more".
    const last = pageOf(NOW - (NOW % 3000) + 3000);
    check('at the bottom the more-note disappears', !last.at(-1).includes('more'));
    Date.now = () => NOW;
    dock.selected = -1;

    // The sliding window with a cursor: one keypress moves the highlight one
    // row and scrolls the list by one — the arrow must not jump up because a
    // whole page flipped under it. Nine agents, five rows: walking the
    // selection from 0 to 5 keeps it on the bottom row from index 4 on.
    store.records.clear();
    for (let i = 0; i < 9; i++) {
      const r = store.ensureRecord({ agentId: `w${i}`, agentName: `walker${i}` });
      r.startedAt = NOW;
    }
    dock.selected = 0;
    dock.windowStart = 0;
    const rowOf = () => {
      const rows = dock.lines(200).map(strip);
      return rows.findIndex((l) => l.includes('❯'));
    };
    dock.lines(200); // settle the window on the selection
    check('the cursor starts on the first row', rowOf() === 0);
    dock.selected = 4;
    check('at the window edge the cursor sits on the last row', rowOf() === 4);
    dock.selected = 5;
    check('one step past the edge scrolls by one, cursor stays put', rowOf() === 4);
    check('and the window moved by exactly one', dock.windowStart === 1);
    dock.selected = 8;
    check('at the end of the list the cursor is still on the last row', rowOf() === 4);
    check('and the window is pinned to the end', dock.windowStart === 4);
    dock.selected = 2;
    check('walking back up scrolls the window up with it', rowOf() === 0 && dock.windowStart === 2);
    dock.selected = -1;
    dock.windowStart = 0;
    // A repaint without a keypress must not snap the window back: the clock
    // path is only taken with no cursor at all.
    dock.selected = 6;
    dock.lines(200);
    const before = dock.windowStart;
    dock.lines(200);
    check('a bare repaint leaves the window alone', dock.windowStart === before);
    dock.selected = -1;
    dock.windowStart = 0;

    // trimFinished keeps the newest and drops the oldest.
    store.records.clear();
    for (let i = 0; i < 12; i++) {
      const r = store.ensureRecord({ agentId: `f${i}` });
      r.status = 'completed';
      r.endedAt = NOW + i;
    }
    store.trimFinished(8);
    check('trimFinished holds its cap', store.records.size === 8);
    check('trimFinished keeps the newest',
      store.records.has('f11') && !store.records.has('f0'));
  } finally {
    Date.now = realNow;
  }
}

console.log('agent dock:');
try {
  new Function('js', 'settings', PATCH)(FIXTURE, { get: () => 'off' });
  check('agent_dock=off is a no-op', false);
} catch (e) {
  check('agent_dock=off is a no-op', e.message === 'already patched');
}
try {
  new Function('js', 'settings', PATCH)(FIXTURE, { get: () => 'sideways' });
  check('an unknown value is refused', false);
} catch (e) {
  check('an unknown value is refused', e.message.includes('must be one of'));
}
try {
  new Function('js', 'settings', PATCH)('var FooterComponent = class {};',
    { get: (k, d = '') => (k === 'agent_dock' ? 'running' : d) });
  check('a missing anchor fails loudly', false);
} catch (e) {
  check('a missing anchor fails loudly', e.message.includes('not found'));
}

suite('running');
suite('all');

// ------------------------------------------------------------- navigation
//
// The navigation splices are part of 82-agent-dock.js, so the same patch
// output that the dock suite ran on is loaded again with the nav globals.

function loadNav(mode) {
  const settings = { get: (key, fallback = '') => (key === 'agent_dock' ? mode : fallback) };
  const patched = new Function('js', 'settings', PATCH)(FIXTURE, settings);

  const currentTheme = { dim: (s) => s, fg: (_c, s) => s };
  const visibleWidth = (s) => strip(s).length;
  const truncateToWidth = (s, w) =>
    strip(s).length <= w ? s : strip(s).slice(0, Math.max(0, w - 1)) + '…';

  const opened = [];
  class AgentActivityViewer {
    constructor(props) { this.props = props; opened.push(props); }
  }
  const takeovers = [];
  const beginScreenTakeover = (_ui, viewer) => { takeovers.push(viewer); return { kind: 'children' }; };
  const endScreenTakeover = () => { takeovers.pop(); };

  const loaded = new Function(
    'currentTheme', 'truncateToWidth', 'visibleWidth',
    'AgentActivityViewer', 'beginScreenTakeover', 'endScreenTakeover',
    `${PRELUDE}${patched}\nreturn { dock: kmodsAgentDock, nav: kmodsAgentDockNav, Store: SubagentActivityStore, Handler: SubagentEventHandler, EditorKeyboard, FixtureEditor };`
  )(currentTheme, truncateToWidth, visibleWidth,
    AgentActivityViewer, beginScreenTakeover, endScreenTakeover);

  return { ...loaded, opened, takeovers };
}

async function navSuite() {
  console.log('\nnavigation:');
  const { dock, nav, Store, Handler, EditorKeyboard, FixtureEditor, opened, takeovers } = loadNav('running');

  const sent = [];
  const scrolled = [];
  const host = {
    handleUserInput: (t) => sent.push(t),
    btwPanelController: { scroll: (dir) => { scrolled.push(dir); return false; } },
    state: { ui: { requestRender() {}, setFocus() {} }, editor: null, terminal: {} },
    escaped: false,
  };
  const editor = new FixtureEditor(host);
  host.state.editor = editor;
  new EditorKeyboard(host, editor).install();

  const handler = new Handler();
  const store = handler.activityStore;

  // With no agents the arrows must behave exactly as before.
  check('down with an empty dock falls through', editor.onDownArrowEmpty() === false);
  check('and reaches the btw panels', scrolled.at(-1) === 'down');
  check('up with an empty dock falls through', editor.onUpArrowEmpty() === false);

  for (const name of ['explore', 'coder', 'plan']) {
    store.ensureRecord({ agentId: `x-${name}`, agentName: name });
  }

  check('down selects the first agent',
    editor.onDownArrowEmpty() === true && dock.selected === 0);
  check('down walks the list',
    editor.onDownArrowEmpty() === true && dock.selected === 1);
  editor.onDownArrowEmpty();
  check('down stops at the last agent',
    dock.selected === 2 && editor.onDownArrowEmpty() === false);
  check('past the end the key falls through', scrolled.at(-1) === 'down');

  check('the selected row is marked', strip(dock.lines(200)[2]).trimStart().startsWith('❯ '));
  check('the others keep their bullet', strip(dock.lines(200)[0]).trimStart().startsWith('◯ '));

  check('up walks back', editor.onUpArrowEmpty() === true && dock.selected === 1);
  editor.onUpArrowEmpty();
  editor.onUpArrowEmpty();
  check('up returns the focus to the composer', dock.selected === -1);
  check('above the list the key falls through', editor.onUpArrowEmpty() === false);

  // Enter sends a prompt while nothing is selected.
  editor.onSubmit('hallo');
  check('enter still sends when nothing is selected', sent.at(-1) === 'hallo');
  check('nothing was opened', opened.length === 0);

  // Enter opens the highlighted agent instead, and does not send.
  editor.onDownArrowEmpty();
  editor.onDownArrowEmpty();
  editor.onSubmit('darf nicht gesendet werden');
  check('enter opens the selected agent', opened.length === 1);
  check('it hands over the live record', opened[0].record === store.get('x-coder'));
  check('the screen was taken over', takeovers.length === 1);
  check('and the prompt was not sent', sent.at(-1) === 'hallo');
  check('the selection is released', dock.selected === -1);

  opened[0].onClose();
  check('closing gives the screen back', takeovers.length === 0);

  // Escape releases a selection and otherwise does what it always did.
  editor.onDownArrowEmpty();
  editor.onEscape();
  check('escape releases the selection', dock.selected === -1 && host.escaped === false);
  editor.onEscape();
  check('escape without a selection reaches Kimi', host.escaped === true);

  // An agent that disappears must not leave a dangling selection.
  editor.onDownArrowEmpty();
  store.records.clear();
  check('an emptied dock clears the selection',
    dock.lines(200).length === 0 && dock.selected === -1);

  // `ctrl+k` stops the highlighted agent: the task registry first
  // (background), the interactive-agent cancel as the fallback (foreground).
  // The row turns failed on the spot and leaves on the short three-second
  // clock.
  const stopped = [];
  const cancelled = [];
  store.records.clear();
  const running = store.ensureRecord({ agentId: 'stop-me', agentName: 'coder', parentToolCallId: 'tc-stop' });
  running.startedAt = Date.now();
  host.session = { stopBackgroundTask: async (id, opts) => stopped.push([id, opts]) };
  host.backgroundTasks = new Map([['task-9', { kind: 'agent', taskId: 'task-9', agentId: 'stop-me' }]]);
  host.harness = { withInteractiveAgent: async (id, fn) => { cancelled.push(id); await fn(); } };
  dock.selected = 0;
  dock.lines(200);
  editor.handleInput(CTRL_K);
  await new Promise((r) => setTimeout(r, 0));
  check('ctrl+k stops the selected agent through its task',
    stopped.length === 1 && stopped[0][0] === 'task-9');
  check('the row turns failed immediately', store.get('stop-me').status === 'failed');
  check('and carries the short clock', store.get('stop-me').dockStopped === true);
  check('the selection stays on the stopped row', dock.selected === 0);

  // Foreground path: no task claims the agent, so the cancel goes through
  // the harness's interactive agent lane.
  store.records.clear();
  const fg = store.ensureRecord({ agentId: 'stop-fg', agentName: 'coder' });
  fg.startedAt = Date.now();
  dock.selected = 0;
  editor.handleInput(CTRL_K);
  await new Promise((r) => setTimeout(r, 0));
  check('without a task the cancel walks the interactive lane', cancelled.at(-1) === 'stop-fg');

  // With text in the composer or no selection the key falls through to the
  // editor's own handling.
  host.editorText = 'soweit';
  const before = stopped.length + cancelled.length;
  editor.handleInput(CTRL_K);
  check('ctrl+k with text in the composer falls through',
    stopped.length + cancelled.length === before && host.lastInput === CTRL_K);
  host.editorText = '';
  dock.selected = -1;
  editor.handleInput(CTRL_K);
  check('ctrl+k without a selection falls through too',
    stopped.length + cancelled.length === before);
  // And a plain letter never stops anything.
  dock.selected = 0;
  if (store.records.size === 0) {
    store.ensureRecord({ agentId: 'keep-me', agentName: 'coder' }).startedAt = Date.now();
  }
  editor.handleInput('s');
  check('a plain s stops nothing', stopped.length + cancelled.length === before);
}

await navSuite();

console.log(failures === 0 ? '\nall checks passed.' : `\n${failures} failed.`);
process.exit(failures === 0 ? 0 : 1);

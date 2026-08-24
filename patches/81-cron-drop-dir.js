// Adopt external "drop files" as native one-shot cron fires.
//
// An external bus daemon drops a JSON file into `<sessionDir>/cron/` and the
// idle session fires it as a real user turn within about a second — in any
// terminal, without anything being typed. The file looks like a v1 cron task:
//
//   {"id": "deadbeef", "prompt": "Reply with exactly: DROP_FIRE_OK"}
//
// `id` is optional (an 8-hex id is stamped when missing or malformed);
// `cron`, `createdAt` and `recurring` are ignored — every adopted drop is
// treated as a one-shot that is due now.
//
// HOW IT WORKS
//
// The v2 cron service (`SessionCronServiceImpl`) is purely in-memory: its
// tasks live in the event-sourced `cronKey` state and nothing ever reads the
// `cron/` directory. This patch adds a `scanDropDir()` method and calls it at
// the top of `tick()` — before the `tasks.size === 0` early return, because
// the drop case *is* the empty store. The scan adopts each well-formed
// `*.json` drop by dispatching a native `CronAdd`, so state, restore and
// telemetry stay exactly what Kimi already does; delivery then goes through
// the untouched `processDue`/`deliverFire` path, which injects a real user
// turn via `IAgentPromptService` and auto-deletes the one-shot after firing.
//
// Why the drop fires on the first idle tick: the adopted task is stamped
// `cron: "* * * * *"`, `recurring: false`, and `createdAt` 120 s in the past.
// `processDue` computes the next occurrence *after* `createdAt`, which is a
// minute boundary that is already in the past, so `now < nextFireAt` is false
// and the task is due immediately. One-shot jitter only ever shifts a fire
// *earlier* (`oneShotJitteredNextCronRunMs`), never later, so it cannot delay
// the drop. Measured latency is drop→fire within one 1 s tick of the session
// going idle (see FINDINGS or the patch report for the headless proof).
//
// Bad drops are quarantined by renaming to `<name>.bad` rather than deleted:
// the file is the only copy of whatever the bus daemon tried to say, and the
// daemon (or a human) can inspect the `.bad` file to see what was rejected.
// A malformed drop must never break `tick()`, so everything is caught.
//
// The session directory comes from a fifth constructor parameter,
// `ISessionContext`, whose `sessionDir` is seeded into the session scope
// (`sessionContextSeed`); `init_sessionContext()` is added to the module's
// init list so the decorator never captures an uninitialised identifier.
//
// ------------------------------------------------------------------ settings
//
// Off by default. Set `cron_drop_dir = on` in `patch-settings.conf`, or pick
// it in the menu (Miscellaneous). The default must match lib/patch_settings.py.

const enabled = /^(on|true|1|yes)$/i.test(settings.get('cron_drop_dir', 'off'));

if (!enabled) {
  throw new Error('already patched');
}

// Build-detection marker: `grep -c agentbus-cron-drop-v1 <binary>` is 1 on a
// patched build, 0 on a pristine one. It lives in a comment inside the
// spliced method, so it survives verbatim into the binary.
const MARKER = 'agentbus-cron-drop-v1';
if (js.includes(MARKER)) {
  throw new Error('already patched');
}

// Every anchor is counted before anything is replaced: a release that moves
// one of them gets a loud failure, not a half-patched scheduler.
function once(anchor, what) {
  const n = js.split(anchor).length - 1;
  if (n === 0) throw new Error(`${what} not found - shape changed this release`);
  if (n !== 1) throw new Error(`${what} is not unique (${n}) - refusing to guess`);
}

// --------------------------------------------------- 1. module init ordering
// `__decorateParam(4, ISessionContext)` below is evaluated when
// `init_sessionCronServiceImpl()` runs; the identifier is only initialised if
// `init_sessionContext()` ran first (every `__esmMin` module is lazy).
const INIT_ANCHOR = '\tinit_configSection$5();\n\tinit_cron_expr();';
once(INIT_ANCHOR, 'sessionCronServiceImpl init list');

// ------------------------------------------------------- 2. class field slot
const FIELD_ANCHOR = '\t\tconfig;\n\t\ttimer = this._register(new IntervalTimer({ unref: true }));';
once(FIELD_ANCHOR, 'cron service field declarations');

// ------------------------------------------------------------ 3. constructor
const CTOR_ANCHOR = 'constructor(states, agentLifecycle, telemetry, config) {\n\t\t\tsuper();';
once(CTOR_ANCHOR, 'cron service constructor');

// --------------------------------------------------------- 4. DI registration
const DEC_ANCHOR = '__decorateParam(3, IConfigService)\n\t], SessionCronServiceImpl);';
once(DEC_ANCHOR, 'cron service DI decorator');

// -------------------------------------------------------- 5. scanDropDir body
const ADD_ANCHOR = 'addTask(init) {\n\t\t\tconst task = {\n\t\t\t\t...init,';
once(ADD_ANCHOR, 'addTask insertion point');

const SCAN_METHOD = `\t\tasync scanDropDir() {
\t\t\t// ${MARKER} — adopt external drop files from <sessionDir>/cron/*.json
\t\t\t// as native one-shot cron fires. Called at the top of tick(), before
\t\t\t// the empty-store return: the drop case IS the empty store.
\t\t\ttry {
\t\t\t\tif (this.sessionContext === void 0 || this.sessionContext.sessionDir === void 0) return;
\t\t\t\tconst dir = node_path.join(this.sessionContext.sessionDir, "cron");
\t\t\t\tlet names;
\t\t\t\ttry {
\t\t\t\t\tnames = await node_fs_promises.readdir(dir);
\t\t\t\t} catch {
\t\t\t\t\treturn;
\t\t\t\t}
\t\t\t\tif (this.dropAdopted === void 0) this.dropAdopted = new Set();
\t\t\t\tfor (const name of names) {
\t\t\t\t\tif (!name.endsWith(".json")) continue;
\t\t\t\t\tconst file = node_path.join(dir, name);
\t\t\t\t\ttry {
\t\t\t\t\t\tconst drop = JSON.parse(await node_fs_promises.readFile(file, "utf8"));
\t\t\t\t\t\tconst prompt = typeof drop.prompt === "string" ? drop.prompt.trim() : "";
\t\t\t\t\t\tif (prompt.length === 0 || prompt.length > 8000) throw new Error("drop prompt missing or over 8000 chars");
\t\t\t\t\t\tlet id = typeof drop.id === "string" ? drop.id : "";
\t\t\t\t\t\tif (!CRON_ID_REGEX.test(id)) id = node_crypto.randomBytes(4).toString("hex");
\t\t\t\t\t\tif (this.tasks.has(id) || this.dropAdopted.has(id)) {
\t\t\t\t\t\t\tawait node_fs_promises.unlink(file).catch(() => {});
\t\t\t\t\t\t\tcontinue;
\t\t\t\t\t\t}
\t\t\t\t\t\tthis.dropAdopted.add(id);
\t\t\t\t\t\tconst task = {
\t\t\t\t\t\t\tid,
\t\t\t\t\t\t\tcron: "* * * * *",
\t\t\t\t\t\t\tprompt,
\t\t\t\t\t\t\tcreatedAt: this.clocks.wallNow() - 120000,
\t\t\t\t\t\t\trecurring: false
\t\t\t\t\t\t};
\t\t\t\t\t\tthis.dispatchCron(new CronAdd({ task }));
\t\t\t\t\t\tawait node_fs_promises.unlink(file).catch(() => {});
\t\t\t\t\t} catch (error) {
\t\t\t\t\t\tawait node_fs_promises.rename(file, file + ".bad").catch(() => {});
\t\t\t\t\t\tthis.debugLog(\`cron-drop: quarantined \${name}: \${error instanceof Error ? error.message : String(error)}\`);
\t\t\t\t\t}
\t\t\t\t}
\t\t\t} catch (error) {
\t\t\t\tthis.debugLog(\`cron-drop scan failed: \${error instanceof Error ? error.message : String(error)}\`);
\t\t\t}
\t\t}
\t\t`;

// ------------------------------------------------------------- 6. tick() call
// The scan runs on every tick, even while a turn is running — adoption is
// state-only, and delivery is still gated by the idle check further down.
const TICK_ANCHOR = '\t\t\tif (this.tasks.size === 0) return;\n\t\t\tconst mainHandle = this.agentLifecycle.findAgentHandle("main");';
once(TICK_ANCHOR, 'tick() empty-store return');

let out = js;
out = out.replace(INIT_ANCHOR, () => '\tinit_configSection$5();\n\tinit_sessionContext();\n\tinit_cron_expr();');
out = out.replace(FIELD_ANCHOR, () => '\t\tconfig;\n\t\tsessionContext;\n\t\ttimer = this._register(new IntervalTimer({ unref: true }));');
out = out.replace(CTOR_ANCHOR, () => 'constructor(states, agentLifecycle, telemetry, config, sessionContext) {\n\t\t\tsuper();\n\t\t\tthis.sessionContext = sessionContext;');
out = out.replace(DEC_ANCHOR, () => '__decorateParam(3, IConfigService),\n\t\t__decorateParam(4, ISessionContext)\n\t], SessionCronServiceImpl);');
out = out.replace(ADD_ANCHOR, () => SCAN_METHOD + ADD_ANCHOR);
out = out.replace(TICK_ANCHOR, () => '\t\t\tawait this.scanDropDir();\n' + TICK_ANCHOR);

return out;

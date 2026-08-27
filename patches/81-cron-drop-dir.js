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
// The v3 cron runtime is an XState actor (`cronActorLogic`) whose state lives
// in an event-sourced `tasks` Map. Nothing ever reads the `cron/` directory.
// This patch adds a `scanCronDropDir()` function and calls it at the top of
// `tickCron()` — before the `getState().size === 0` early return, because the
// drop case *is* the empty store. The scan adopts each well-formed `*.json`
// drop by dispatching a native `CronAdd`, so state, restore and telemetry
// stay exactly what Kimi already does; delivery then goes through the
// untouched `processDue`/`deliverFire` path, which injects a real user turn
// via `IAgentPromptService` and auto-deletes the one-shot after firing.
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
// A malformed drop must never break `tickCron()`, so everything is caught.
//
// The session directory comes from `runtime.get(ISessionContext)` — the same
// accessor the date-change actor uses. `init_sessionContext()` is added to
// the module's init list so the decorator is initialised before it is called.
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
// spliced function, so it survives verbatim into the binary.
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
// `ISessionContext` is referenced inside `scanCronDropDir` below; the
// identifier is only initialised if `init_sessionContext()` ran first (every
// `__esmMin` module is lazy).
const INIT_ANCHOR = '\tinit_configSection$5();\n\tinit_cron_expr();';
once(INIT_ANCHOR, 'cronAgentRuntime init list');

// ------------------------------------------------------- 2. scanCronDropDir
// Inserted as a standalone async function right before `tickCron`. It needs
// no class, no DI, no instance state — just the runtime handle that
// `tickCron` already receives.
const TICK_FN_ANCHOR = 'async function tickCron(runtime, state) {';
once(TICK_FN_ANCHOR, 'tickCron function declaration');

const SCAN_FN = `async function scanCronDropDir(runtime) {
\t// ${MARKER} — adopt external drop files from <sessionDir>/cron/*.json
\t// as native one-shot cron fires. Called at the top of tickCron(), before
\t// the empty-store return: the drop case IS the empty store.
\ttry {
\t\tconst sessionContext = runtime.get(ISessionContext);
\t\tif (sessionContext === void 0 || sessionContext.sessionDir === void 0) return;
\t\tconst dir = node_path.join(sessionContext.sessionDir, "cron");
\t\tlet names;
\t\ttry {
\t\t\tnames = await node_fs_promises.readdir(dir);
\t\t} catch {
\t\t\treturn;
\t\t}
\t\tif (runtime._dropAdopted === void 0) runtime._dropAdopted = new Set();
\t\tfor (const name of names) {
\t\t\tif (!name.endsWith(".json")) continue;
\t\t\tconst file = node_path.join(dir, name);
\t\t\ttry {
\t\t\t\tconst drop = JSON.parse(await node_fs_promises.readFile(file, "utf8"));
\t\t\t\tconst prompt = typeof drop.prompt === "string" ? drop.prompt.trim() : "";
\t\t\t\tif (prompt.length === 0 || prompt.length > 8000) throw new Error("drop prompt missing or over 8000 chars");
\t\t\t\tlet id = typeof drop.id === "string" ? drop.id : "";
\t\t\t\tif (!CRON_ID_REGEX.test(id)) id = node_crypto.randomBytes(4).toString("hex");
\t\t\t\tif (runtime.getState().has(id) || runtime._dropAdopted.has(id)) {
\t\t\t\t\tawait node_fs_promises.unlink(file).catch(() => {});
\t\t\t\t\tcontinue;
\t\t\t\t}
\t\t\t\truntime._dropAdopted.add(id);
\t\t\t\tconst task = {
\t\t\t\t\tid,
\t\t\t\t\tcron: "* * * * *",
\t\t\t\t\tprompt,
\t\t\t\t\tcreatedAt: clocksOf(runtime).wallNow() - 120000,
\t\t\t\t\trecurring: false
\t\t\t\t};
\t\t\t\truntime.dispatch(new CronAdd({ task }));
\t\t\t\tawait node_fs_promises.unlink(file).catch(() => {});
\t\t\t} catch (error) {
\t\t\t\tawait node_fs_promises.rename(file, file + ".bad").catch(() => {});
\t\t\t\tdebugLog(runtime, \`cron-drop: quarantined \${name}: \${error instanceof Error ? error.message : String(error)}\`);
\t\t\t}
\t\t}
\t} catch (error) {
\t\tdebugLog(runtime, \`cron-drop scan failed: \${error instanceof Error ? error.message : String(error)}\`);
\t}
}
`;

// ------------------------------------------------------------- 3. tick() call
// The scan runs on every tick, even while a turn is running — adoption is
// state-only, and delivery is still gated by the idle check further down.
const TICK_BODY_ANCHOR = '\tawait configOf(runtime).ready;\n\tif (cronConfigOf(runtime).disabled || runtime.getState().size === 0) return;';
once(TICK_BODY_ANCHOR, 'tickCron empty-store return');

let out = js;
out = out.replace(INIT_ANCHOR, () => '\tinit_configSection$5();\n\tinit_sessionContext();\n\tinit_cron_expr();');
out = out.replace(TICK_FN_ANCHOR, () => SCAN_FN + TICK_FN_ANCHOR);
out = out.replace(TICK_BODY_ANCHOR, () => '\tawait configOf(runtime).ready;\n\tawait scanCronDropDir(runtime);\n\tif (cronConfigOf(runtime).disabled || runtime.getState().size === 0) return;');

return out;

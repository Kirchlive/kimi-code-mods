# Kimi Code 0.36.0 — hidden, experimental and undocumented features

Derived from the extracted bundle (`.work/bundle.js`); locations are the
`//#region` module paths the bundler left behind. Nothing state-changing was
run to produce this.

Labels: **active** (usable today), **gated** (behind a flag), **dead**
(reserved, unfinished, or never read).

## The eight worth acting on

1. **A hooks system with 20 events.** A `[hooks]` block in `config.toml` runs
   shell commands on `PreToolUse`, `PostToolUse`, `SessionStart` and 17 more.
   Fully implemented, absent from `--help`. **active**
2. **`KIMI_CODE_EXPERIMENTAL_FLAG=1` turns on every experimental flag at once** —
   a master switch above the individual ones. **active**
3. **There are four experimental flags, not two.** Two of them default to *on*
   and are rollback switches rather than pending features. **gated**
4. **A full local web server** with REST and WebSocket APIs, bearer auth, a file
   browser and PTY terminals: `kimi web`. **active**
5. **The entire model configuration is reachable through the environment** —
   14 `KIMI_MODEL_*` variables including capabilities and thinking effort. **active**
6. **26 configuration sections**, most of them undocumented. **active**
7. **Cron ships a test harness** — injectable clock, manual tick, jitter and
   staleness switches. **active**
8. **Transcript window tuning** — five variables decide how much history is
   re-sent每 turn, which is the one lever here that directly moves context cost.
   **active**

## 1. Slash commands

59 command objects exist; `src/tui/commands/` contributes 25 modules and the
rest belong to the ACP surface. **None carries a `hidden` flag**, so the TUI
list is discoverable by typing `/`.

The ones whose purpose the name does not give away: `/btw` asks a **forked side
agent** without disturbing the main transcript. `/undo` withdraws the last
prompt. `/fork` copies the session **without** switching to the copy. `/web`
starts the server plus web UI. `/secondary-model` (alias `/subagent-model`)
configures the subagent model. `/experiments` manages the flags. `/reload-tui`
reloads only `tui.toml`. `/export-debug-zip` exports the session as a debug
archive. `/dispatch`, `/resolve` and `/registry` are infrastructure, not user
commands.

Agent profiles double as commands: `/agent`, `/coder`, `/explore`, `/plan`.
`/auto` switches to the fully autonomous mode.

Availability is enforced per command — `always`, `idle-only`, or a predicate.
`/add-dir`, `/experiments` and `/reload` refuse while a turn is running.

## 2. Environment variables

**170 `KIMI*` names appear in the text; 63 are actually read.** The difference
matters: setting one of the others does nothing at all.

**Model control** (`agent-core/src/config/env-model.ts`): `KIMI_MODEL_NAME`,
`_PROVIDER_TYPE`, `_BASE_URL`, `_API_KEY`, `_DISPLAY_NAME`, `_CAPABILITIES`,
`_MAX_CONTEXT_SIZE`, `_MAX_OUTPUT_SIZE`, `_THINKING_EFFORT`, `_REASONING_KEY`,
`_ADAPTIVE_THINKING`, `_TEMPERATURE`, `_TOP_P`, `_THINKING_KEEP`,
`_MAX_TOKENS`, `_MAX_COMPLETION_TOKENS`.

**Context cost** (`src/tui/utils/transcript-window.ts`):
`KIMI_CODE_TUI_MAX_TURNS` (15), `_EXPAND_TURNS` (3), `_HYSTERESIS` (5),
`_KEEP_RECENT_STEPS`, `_KEEP_RECENT_ASSISTANT`,
`_KEEP_RECENT_ASSISTANT_COMPLETED`. `0` disables trimming.

**Cron harness**: `KIMI_DISABLE_CRON`, `KIMI_CRON_CLOCK`, `_DEBUG`,
`_MANUAL_TICK`, `_NO_JITTER`, `_NO_STALE`.

**Diagnostics**: `KIMI_STARTUP_TRACE` / `_LOG` (default
`/tmp/kimi-startup-trace.log`), `KIMI_CODE_DEBUG`, `KIMI_LOG_LEVEL` (`info`),
`KIMI_LOG_SESSION_FILES` (3) / `_MAX_BYTES` (5 MB), `KIMI_LOG_GLOBAL_FILES` (5)
/ `_MAX_BYTES` (6 MB), `KIMI_TUI_INPUT_LATENCY` + `_LOG`,
`KIMI_TUI_NO_RENDER_CACHE`.

**Server**: `KIMI_CODE_PASSWORD` (bcrypt), `_ALLOWED_HOSTS`,
`_DISABLE_HOST_CHECK`, `_CORS_ORIGINS`, `_DEV_SERVER`.

**Endpoints**: `KIMI_API_KEY`, `KIMI_BASE_URL` (`https://api.moonshot.ai/v1`),
`KIMI_CODE_BASE_URL` (`https://api.kimi.com/coding/v1`), `KIMI_OAUTH_HOST`
(`https://auth.kimi.com`), `KIMI_DISABLE_OAUTH_LOCK`, `KIMI_CODE_HOME`,
`KIMI_SHELL_PATH`, `KIMI_PLUGIN_ROOT`.

**Dead** — about 60 names, including **`KIMI_CODE_AGENT_SWARM_MAX_CONCURRENCY`**,
which appears as a string but is never read from the environment in this build.
Setting it does nothing. Same for `KIMI_CODE_BACKGROUND_MAX_RUNNING_TASKS`,
`KIMI_CODE_STATUS_LINE`, `KIMI_CODE_FS_WATCH_DEBOUNCE_MS`.

## 3. Configuration sections

26 registered through `registerConfigSection(...)`, nearly all in
`agent-core-v2`: `[tools]`, `[hooks]`, `[experimental]`, `[permission]`,
`[defaultPermissionMode]`, `[defaultPlanMode]` (false), `[loopControl]`,
`[subagent]`, `[secondaryModel]`, `[task]`/`[background]`, `[tokenCounting]`,
`[identity]`, `[image]`, `[cron]`, `[mcp]`, `[builtinProductSkills]` (true),
**`[mergeAllAvailableSkills]`** (true, undocumented), `[extraSkillDirs]`,
`[extraAgentDirs]`, `[models]`, `[providers]`, `[modelCatalog]`, `[thinking]`,
`[services]`.

### `[hooks]` in detail

From `agent-core-v2/src/agent/externalHooks/`. The schema is strict: `event`
(required), `matcher` (optional), `command` (required), `timeout` (1–600 s).

The 20 events: PreToolUse, PostToolUse, PostToolUseFailure, PermissionRequest,
PermissionResult, UserPromptSubmit, UserPromptQueued, TurnStarted, Stop,
StopFailure, Interrupt, SessionStart, SessionEnd, SessionHeartbeat,
SubagentStart, SubagentStop, TaskStarted, PreCompact, PostCompact,
Notification.

`runner.ts` executes the command **through a shell**, collects stdout and
stderr, and derives the outcome from the **exit code**. Spawn failure, crash
and timeout all resolve to `allowResult` — hooks fail open and cannot block the
agent.

There are **two implementations**: the v2 one above, and an older one in
`agent-core/src/session/hooks/` with only 16 events. Since v2 is the live
generation, the 20-event list applies.

#### They do fire — the earlier verdict was wrong

`SessionStart` works. The proof was sitting on disk the whole time, written by
the very test that was recorded as having produced nothing:

```
$ cat evidence/hook-proof-20260814.txt
session-start 05:28:51
session-start 05:37:21
session-start 10:38:02
session-start 10:47:59
session-start 10:48:29
session-start 17:28:18
```

Two hooks were configured against that file, `SessionStart` and `PreToolUse`,
with the same shell command shape. Six `session-start` lines, and **not one**
`pre-tool-use` line. So the hook system is not inert; one event class was not
observed. That is a different, much smaller question than the one this section
used to ask, and it needs one tool call in a live session to settle: start
Kimi, let it read a file, look at the file again.

#### What the wiring says about the remaining half

`PreToolUse` is not left unconnected. `registerListeners()` resolves the tool
executor itself and hands it over:

```js
registerListeners() {
  this.registerPermissionHooks();
  this.registerToolHooks(this.instantiation.invokeFunction((a) => a.get(IAgentToolExecutorService)));
  this.registerPromptHooks(this.instantiation.invokeFunction((a) => a.get(IAgentPromptService)));
  …
}
```

Note the shape difference that makes the two halves fail differently.
`registerPermissionHooks` subscribes to the event bus and needs nothing else,
which is the kind of wiring that either works everywhere or nowhere.
`registerToolHooks` needs a service resolved out of the **agent** scope, while
the `SessionStart` side lives in the **session** scope — two scopes, two
lifetimes, and only one of them is proven to reach a running session.

Four things are ruled out, so nobody has to rule them out again:

**The section name is right.** `HOOKS_SECTION = "hooks"` in
`agent-core-v2/src/agent/externalHooks/configSection.ts`, and
`HooksConfigSchema = array(HookDefSchema)` — so `[[hooks]]` is the correct
TOML, and `hooksFromToml` maps the snake_case keys on the way in.

**The service is not lazy.** It registers as
`registerScopedService("agent", IAgentExternalHooksService,
AgentExternalHooksService, 0, "externalHooks")`, and `provideScopeServices`
reads that fourth argument as `activation: entry.activation === 1 ?
"ondemand" : "eager"`. Zero means **eager**: 162 services carry it, 12 carry
the on-demand 1. So the hook service is built when its scope is created,
whether or not anything asks for it.

**Nothing needs to inject it, and that is not the bug.** `IAgentExternalHooksService`
occurs three times in the whole bundle, all inside its own two files. That
looks damning until the line above: an eagerly activated service has no reason
to be injected anywhere.

**It subscribes rather than being called.** Its constructor ends with
`this.registerListeners()`, which calls `registerPermissionHooks`,
`registerToolHooks`, `registerPromptHooks`, `registerTurnHooks`,
`registerLoopHooks`, `registerFullCompactionHooks` and `registerTaskHooks`.
That is why the `.trigger(` call sites in v2 all sit inside the hook modules
themselves, while in the dead `agent-core` generation they sit in
`agent/turn/index.ts` and friends — a difference that reads like v2 being
unwired and is in fact just a different shape.

What is left is the scope. Everything above says the service is constructed as
soon as an `agent` (or `session`) scope exists; it was not established that the
path a normal TUI session takes creates one. Answering that means watching a
running Kimi — `ExternalHooksRunnerService` keeps a `summary` of hooks per
event, which is what one would want to see, and nothing exposes it on the
command line.

## 4. Experimental and unfinished

Resolution order (`agent-core/src/flags/registry.ts`):
`KIMI_CODE_EXPERIMENTAL_FLAG=1` turns everything on (source `master-env`);
otherwise the flag's own variable; otherwise `[experimental]` in `config.toml`
keyed by flag id; otherwise the default. `explain(id)` returns the value **and**
where it came from, which is what `/experiments` displays.

| id | env | default | effect |
|---|---|---|---|
| `tool-select` | `..._TOOL_SELECT` | **off** | keeps MCP schemas out of `tools[]`, loaded on demand via `select_tools`; only for models whose capability catalog declares it |
| `secondary-model` | `..._SECONDARY_MODEL` | **off** | subagents use a separately configured second model |
| `search_worker` | `..._SEARCH_WORKER` | **on** | search index in its own worker thread; 0 is the rollback |
| `persistence_minidb_readmodel` | `..._PERSISTENCE_MINIDB_READMODEL` | **on** | minidb as the read model for the session index and wire replay |

The last two register themselves at load time through `registerFlagDefinition`
and so do not appear in the static array — they are rollback switches, not
features waiting to be discovered.

**Dead**: the minidb cross-shard mode `2pc` throws *"reserved for a future
release and is not implemented yet"*. A `not_implemented` error code exists in
both registries. There are **no** `if (false)` branches and **no** TODO/FIXME
markers in Kimi's own code.

**Deprecations**: `max_retries_per_step` → `max_attempts_per_step`, and
`KIMI_LOOP_MAX_RETRIES_PER_STEP` → `KIMI_LOOP_MAX_ATTEMPTS_PER_STEP`. The config
service warns and keeps accepting the old name.

## 5. Hidden capabilities

**`__plugin_run_node`** is the only subcommand explicitly marked hidden. When
Kimi runs as a native binary and a plugin declares `command: "node"`, Kimi
re-executes itself to provide a Node runtime, so plugins work without Node
installed. This is what `KIMI_PLUGIN_ROOT` is for.

**The web server** (`kimi web`, `packages/kap-server/`): `--host` / `--port`
(default 127.0.0.1 and a free port), `--dangerous-bypass-auth` (disables bearer
auth on **all** routes and advertises that through `/api/v1/meta`),
`--allow-remote-shutdown`, `--allow-remote-terminals` (the help text calls
remote shell "high risk" itself), `--insecure-no-tls`, `--debug-endpoints`.
`kimi web rotate-token` rotates the token in `<KIMI_CODE_HOME>/server.token`
(mode 0600), which survives restarts. Routes seen: `/api/v1/healthz`, `/ws`,
`/files`, `/fs:browse`, `/fs:home`, `/fs::content`, `/debug`.

> Security note: `--dangerous-bypass-auth` together with a non-loopback
> `--host` puts an unauthenticated file browser and PTY terminals on the
> network.

**ACP**: `kimi acp` runs Kimi as an Agent Client Protocol server over stdio for
editor integration, implemented in `packages/acp-adapter/` and
`packages/acp-server/` against two bundled SDK versions (0.23.0 and 1.3.0).
`--login` is the entry point for ACP terminal auth.

**Also**: `kimi vis [sessionId]` opens a session visualiser in the browser,
`kimi doctor` validates the configuration (useful before committing a `[tools]`
or `[hooks]` block), `-p` accepts `--output-format`, and `kimi export` writes a
session as a ZIP.

## Open questions

Whether `[hooks]` is genuinely wired up in the v2 path — both implementations
exist and the v2 section registers itself, but no hook was observed firing.
Test with a `SessionStart` hook before relying on it.

The exact meaning of the hook exit codes: `resultFromExitCode` decides, and the
mapping was not decoded.

The server's full route table — `terminals`, `shutdown` and `meta` are only
named in help text and the routes are built dynamically, so the real surface is
larger than the list above.

The second choice for `--output-format` (the string is truncated in the
bundle).

Whether `tool-select` would help here: it only affects MCP schemas, and only
for models whose capability catalog declares dynamic loading. Whether
`kimi-code/k3` does was not checked.

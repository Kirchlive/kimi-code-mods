// Adds a `/wd` slash command: start a session in a different working directory.
//
// WHY THIS IS "NEW SESSION" AND NOT "CHANGE DIRECTORY"
//
// Kimi's core can genuinely relocate a running agent. `ConfigState.applyUpdate`
// reacts to `changed.cwd` by re-scoping kaos and calling
// `initializeBuiltinTools()` again — necessary because `BashTool` captures its
// `cwd` in the constructor. So the engine supports it.
//
// The TUI cannot reach that path. Verified against this bundle:
//
//   * `.config.update(` appears in `src/tui` exactly 0 times
//   * `config.update({cwd` exists only in agent-core's `subagent-host.ts`
//   * the session facade the TUI holds exposes `setModel`, `setPermission`,
//     `setPlanMode`, `setApprovalHandler`, `setQuestionHandler` — no cwd setter
//
// Reaching it would mean adding a method across the agent-core package
// boundary and then re-pointing every consumer that captured `workDir` at
// construction time: the `@`-mention provider, the input-history path, the
// plugin update notifier, and the path permission set. Six stitches in
// minified code, and a single missed one leaves the status line pointing at
// one directory while the tools write to another — the user creates files in
// the wrong place and nothing warns them.
//
// So this takes the honest route instead. `createSessionFromCurrentState()`
// reads `workDir` straight from `appState`, so setting that and starting a new
// session rebuilds everything consistently, because nothing old survives. The
// cost is the conversation, which is why the command says so and asks first.
// The command is described as starting a new session, not as changing
// directory, so nobody expects their history to come along.
//
// Three insertion points, each anchored on the neighbouring `add-dir` command,
// which is the closest existing analogue (it also takes a path and also
// confirms through a picker).

// ------------------------------------------------------------------ settings
//
// Off by default. Set `wd_command = on` in `patch-settings.conf`, or pick it in
// the menu. The default has to match `lib/patch_settings.py`, which registers
// the same key — otherwise the menu reports a state the patch does not honour,
// which is exactly what happened before this block existed: the entry read
// `off` while the command was being compiled in regardless.

let enabled = false;
const getModule = typeof process !== 'undefined' && process.getBuiltinModule;
if (getModule) {
  try {
    const fs = process.getBuiltinModule('fs');
    const path = process.getBuiltinModule('path');
    const patchDir = process.argv[4];
    if (patchDir) {
      const conf = path.join(path.dirname(path.resolve(patchDir)), 'patch-settings.conf');
      if (fs.existsSync(conf)) {
        for (const line of fs.readFileSync(conf, 'utf8').split('\n')) {
          const m = /^\s*wd_command\s*=\s*([^#\s]+)/.exec(line.replace(/#.*/, ''));
          if (m) enabled = /^(on|true|1|yes)$/i.test(m[1].trim());
        }
      }
    }
  } catch {
    // An unreadable settings file must not fail the run, and must not add a
    // command the user never asked for.
    enabled = false;
  }
}

if (!enabled) {
  throw new Error('already patched');
}

if (js.includes('handleWdCommand')) {
  throw new Error('already patched');
}

// ---------------------------------------------------------------- 1. handler
// Injected into the add-dir region so `ChoicePickerComponent`,
// `slashCommandBusyReason` and `slashBusyMessage` are already in scope —
// `init_dispatch` calls `init_add_dir()`, so those bindings are initialised
// before any command runs.
const HANDLER_ANCHOR = 'async function handleAddDirCommand(host, args) {';

if (js.split(HANDLER_ANCHOR).length - 1 !== 1) {
  throw new Error('handleAddDirCommand declaration is not unique - minified shape changed');
}

const HANDLER = `async function handleWdCommand(host, args) {
	const input = args.trim();
	const current = host.state.appState.workDir;
	if (input.length === 0) {
		host.showStatus(\`Working directory:\\n  \${current}\`);
		return;
	}
	let target = input;
	if (target === "~") target = node_os.homedir();
	else if (target.startsWith("~/")) target = node_path.join(node_os.homedir(), target.slice(2));
	target = node_path.resolve(current, target);
	let isDir = false;
	try { isDir = node_fs.statSync(target).isDirectory(); } catch {}
	if (!isDir) {
		host.showError(\`Not a directory: \${target}\`);
		return;
	}
	if (target === current) {
		host.showStatus(\`Already working in:\\n  \${target}\`);
		return;
	}
	const busyReason = slashCommandBusyReason({
		isStreaming: host.state.appState.streamingPhase !== "idle",
		isCompacting: host.state.appState.isCompacting
	});
	if (busyReason !== void 0) {
		host.showError(slashBusyMessage("wd", busyReason));
		return;
	}
	host.mountEditorReplacement(new ChoicePickerComponent({
		title: \`Start a new session in \${target}? This conversation will be discarded.\`,
		options: [
			{ value: "go", label: "Yes, start a new session there" },
			{ value: "cancel", label: "No, stay here" }
		],
		onSelect: (value) => { handleWdChoice(host, target, value); },
		onCancel: () => {
			host.restoreEditor();
			host.showStatus(\`Stayed in:\\n  \${current}\`);
		}
	}));
}
async function handleWdChoice(host, target, choice) {
	host.restoreEditor();
	if (choice !== "go") {
		host.showStatus(\`Stayed in:\\n  \${host.state.appState.workDir}\`);
		return;
	}
	try {
		host.setAppState({ workDir: target });
		await host.createNewSession();
		host.state.ui.requestRender();
		host.showStatus(\`New session in:\\n  \${target}\`, "success");
	} catch (error) {
		host.showError(error instanceof Error ? error.message : String(error));
	}
}
`;

let out = js.replace(HANDLER_ANCHOR, () => HANDLER + HANDLER_ANCHOR);

// --------------------------------------------------------------- 2. registry
// `availability: "idle-only"` matches add-dir: starting a session mid-stream
// would race the running turn. The handler checks again anyway.
const REG_ANCHOR = '{\n\t\t\tname: "add-dir",';
if (out.split(REG_ANCHOR).length - 1 !== 1) {
  throw new Error('add-dir registry entry is not unique - minified shape changed');
}

const REG_ENTRY = `{
			name: "wd",
			aliases: [],
			description: "<path> — Start a new session in another working directory",
			priority: 60,
			availability: "idle-only",
			argumentHint: "<path>"
		},
		`;

out = out.replace(REG_ANCHOR, () => REG_ENTRY + REG_ANCHOR);

// --------------------------------------------------------------- 3. dispatch
const DISPATCH_ANCHOR = 'case "add-dir":\n\t\t\tawait handleAddDirCommand(host, args);\n\t\t\treturn;';
if (out.split(DISPATCH_ANCHOR).length - 1 !== 1) {
  throw new Error('add-dir dispatch case is not unique - minified shape changed');
}

const DISPATCH_CASE = 'case "wd":\n\t\t\tawait handleWdCommand(host, args);\n\t\t\treturn;\n\t\t';

out = out.replace(DISPATCH_ANCHOR, () => DISPATCH_CASE + DISPATCH_ANCHOR);

return out;

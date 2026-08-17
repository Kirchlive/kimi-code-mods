// Let Kimi read the project-instruction files other agents write.
//
// Kimi looks for exactly two names, and the list is a plain array literal:
//
//   AGENTS_MD_PLAIN_NAMES = ["AGENTS.md", "agents.md"];
//
//   async function findAgentsMdInDir(deps, dir) {
//     const found = [];
//     const dotKimi = dotKimiAgentsMdPath(dir);
//     if (await isNonEmptyFile(deps, dotKimi)) found.push(dotKimi);
//     for (const fileName of AGENTS_MD_PLAIN_NAMES) {
//       const candidate = join(dir, fileName);
//       if (await isNonEmptyFile(deps, candidate)) { found.push(candidate); break; }
//     }
//     return found;
//   }
//
// Two properties of that loop decide what this patch may do. It walks the
// array in order and `break`s on the first hit, so **array order is priority**
// and at most one plain file per directory is ever read — adding names cannot
// make Kimi read two instruction files at once and double the prompt. And the
// `.kimi` variant is consulted before the loop, so it keeps precedence over
// everything added here.
//
// Kimi's own names therefore stay at the front. A repository that has both an
// AGENTS.md and a CLAUDE.md behaves exactly as it does today; the alternatives
// only matter where Kimi would otherwise have found nothing.
//
// This is the counterpart to tweakcc's `claudeMdAltNames`, and the cheaper one:
// there the CLAUDE.md reader has to be re-pointed, here a literal grows.
//
// ------------------------------------------------------------------ settings
//
// `agents_md_names` in patch-settings.conf:
//   off     Kimi's own two names, unchanged
//   claude  also CLAUDE.md and claude.md
//   all     also the names the other agent CLIs use
// The default matches lib/patch_settings.py, which registers the same key.

const MODE = String(settings.get('agents_md_names', 'off')).toLowerCase();

const EXTRA = {
  off: [],
  claude: ['CLAUDE.md', 'claude.md'],
  all: ['CLAUDE.md', 'claude.md', 'GEMINI.md', 'QWEN.md', 'CRUSH.md',
        'IFLOW.md', 'WARP.md', 'copilot-instructions.md'],
};

if (!Object.prototype.hasOwnProperty.call(EXTRA, MODE)) {
  throw new Error(
    `agents_md_names must be one of ${Object.keys(EXTRA).join(', ')} - got "${MODE}"`);
}

if (MODE === 'off') {
  throw new Error('already patched');
}

const ANCHOR = 'AGENTS_MD_PLAIN_NAMES = ["AGENTS.md", "agents.md"];';
const REPLACEMENT = 'AGENTS_MD_PLAIN_NAMES = ['
  + ['AGENTS.md', 'agents.md'].concat(EXTRA[MODE]).map(n => JSON.stringify(n)).join(', ')
  + '];';

if (js.includes(REPLACEMENT)) {
  throw new Error('already patched');
}

const count = js.split(ANCHOR).length - 1;
if (count === 0) {
  throw new Error('AGENTS_MD_PLAIN_NAMES not found - the shape changed this release');
}
if (count !== 1) {
  throw new Error(`AGENTS_MD_PLAIN_NAMES is not unique (${count}) - refusing to guess`);
}

return js.replace(ANCHOR, () => REPLACEMENT);

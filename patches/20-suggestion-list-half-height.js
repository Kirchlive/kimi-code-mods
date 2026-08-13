// Gives the slash-command popup more than five rows, in three selectable steps.
//
// This is the Kimi counterpart to tweakcc's `fullscreen-suggestion-height.js`.
// The list that appears when you type `/` is a `WrappingSelectList`, and its
// row budget comes from `SelectList.maxVisible`, seeded in `editor.ts`:
//
//   const maxVisible = options.autocompleteMaxVisible ?? 5;
//   this.autocompleteMaxVisible = Number.isFinite(maxVisible)
//     ? Math.max(3, Math.min(20, Math.floor(maxVisible))) : 5;
//
// Two things follow. The default is five, which is what you see. And even a
// caller that wanted more would be clamped to twenty — so raising the seed
// alone is not enough on a tall terminal.
//
// Rather than fight both, the budget is recomputed where the list is actually
// drawn. `WrappingSelectList.render(width)` destructures `maxVisible` out of
// `internals()`; that value is replaced there. Evaluating at render time also
// means the list follows window resizes, which a constructor-time value could
// not.
//
// ---------------------------------------------------------------- the levels
//
// Set `suggestion_height` in `patch-settings.conf` next to `patches/`:
//
//   default  no-op — Kimi's own five entries
//   half     floor(rows / 2) entries          (the fallback when unset)
//   full     rows - 5 entries
//
// The 5 subtracted by `full` is the chrome that must survive: the composer
// contributes three lines at minimum (top border, one line of text, bottom
// border — `editor.ts` pushes the list *after* that border), and two status
// lines sit below it.
//
// ------------------------------------------- why `full` is not a line budget
//
// `maxVisible` counts *entries*, not screen lines. `renderItemLines` wraps a
// long description onto a second line (`DESCRIPTION_MAX_LINES = 2`), and a
// scrolled list adds its `(n/total)` line, so N entries render as anything
// from N to 2N+1 lines. An exact line budget is therefore not expressible
// here without rewriting `render`, and even `half` can exceed the window when
// most descriptions wrap.
//
// That is tolerable because nothing clips: the list is flow content appended
// to the editor's own lines — no absolute positioning, no `overflow` anywhere
// in `editor.ts` — so an over-long list scrolls rather than painting over the
// composer, which is what the Claude Code patch had to guard against with its
// `rows - 3` ceiling. Overflowing is a readability cost, not corruption.
//
// Both levels keep `Math.max(__tkVisible, …)`: whatever Kimi configured stays
// the floor, so the list is never shorter than stock.

// ------------------------------------------------------------------ settings

// A patch is invoked as `new Function('js', src)` from an ESM module, so there
// is no `require` and no `__dirname` — but `process` is a global. Node 22's
// `process.getBuiltinModule` gives us `fs` without either. The settings file
// sits next to the patch directory, which the runner passes as argv[4]
// (`node run-patches.mjs <in> <out> <patchDir>`); deriving the path from that
// rather than from `process.cwd()` keeps the patch correct when the caller
// runs from elsewhere, and follows `TWEAKKIMI_DATA` into a test sandbox.
const LEVELS = ['default', 'half', 'full'];
let level = 'half';

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
          const m = /^\s*suggestion_height\s*=\s*([^#\s]+)/.exec(line.replace(/#.*/, ''));
          if (m) level = m[1].trim().toLowerCase();
        }
      }
    }
  } catch {
    // An unreadable settings file must not fail the run; `half` stands in.
    level = 'half';
  }
}

if (!LEVELS.includes(level)) {
  throw new Error(`suggestion_height must be one of ${LEVELS.join(', ')} - got "${level}"`);
}

// `default` means Kimi's own behaviour, so the patch declines to act. It
// throws rather than returning `js` untouched because the runner recognises
// exactly one message as a no-op and reports it as such; returning the input
// would be logged as a successful application that changed nothing, which
// reads like a broken anchor.
if (level === 'default') {
  throw new Error('already patched');
}

// -------------------------------------------------------------------- anchor

const ANCHOR = /const\s*\{\s*filteredItems\s*:?\s*[\w$]*\s*,\s*selectedIndex\s*:?\s*[\w$]*\s*,\s*maxVisible\s*:?\s*[\w$]*\s*,\s*theme\s*:?\s*[\w$]*\s*\}\s*=\s*this\.internals\(\)/;

// `kimi-patch.sh` always extracts a fresh bundle from the pristine baseline,
// so a level change needs no restore — this guard only catches a bundle that
// was patched out of band.
if (js.includes('__tkVisible')) {
  throw new Error('already patched');
}

const hit = ANCHOR.exec(js);
if (!hit) {
  throw new Error('WrappingSelectList.render destructuring not found - minified shape changed');
}

const original = hit[0];
const count = js.split(original).length - 1;
if (count !== 1) {
  throw new Error(`render destructuring is not unique (${count} occurrences) - refusing to guess`);
}

// `rows` is read through the same chain pi-tui's own terminal.ts uses, so a
// piped stdout falls back to 24 exactly as it does everywhere else.
const BUDGET = {
  half: 'Math.max(__tkVisible,Math.min(Math.floor(__tkRows/2),Math.max(1,__tkRows-5)))',
  full: 'Math.max(__tkVisible,Math.max(1,__tkRows-5))',
};

const replacement =
  original.replace('maxVisible', 'maxVisible: __tkVisible') +
  ';const __tkRows=(typeof process!=="undefined"&&process.stdout&&process.stdout.rows)||24' +
  `;const maxVisible=${BUDGET[level]}`;

return js.replace(original, () => replacement);

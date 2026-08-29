// How a transcript selection reaches the clipboard: on the mouse release that
// ends the drag, and — always — on the copy key.
//
// WHY THERE IS A KEY AT ALL
// Kimi captures the mouse (SGR 1000/1002/1006), so the terminal never sees the
// drag and its own copy shortcut has nothing to work with — the internal
// highlight is the only selection there is. Kimi does register a keybinding for
// it, `tui.input.copy` on ctrl+c, but the editor's input handler swallows the
// key (`if (kb.matches(data, "tui.input.copy")) return;`) and nothing else ever
// matches it: a documented, dead feature. Splice 2 wires it up.
//
// That used to happen only when `copy_on_mark` was `off`, on the reasoning that
// removing the release-copy left no way to copy at all. It is unconditional
// now: with `on` there was no key copy either, which is what "cmd+c does
// nothing in Kimi" turned out to mean. TuiAltScreen's input listener runs
// *before* the focused editor (inputListeners precede focus dispatch in
// handleTerminalInput), so the branch fires ahead of the swallow.
//
// It consumes the key only when there is a selection to copy. Without one the
// key falls through untouched, which is what keeps ctrl+c meaning interrupt.
//
// WHY CMD+C TOO (splice 1)
// `matchesKey` already understands the super modifier and kitty CSI-u
// sequences — a terminal that forwards Cmd+C as `CSI 99;9u` (cmux with the
// Kitty keyboard protocol does) arrives as `super+c`. Nothing was listening
// for it, because `tui.input.copy` is bound to ctrl+c alone. Adding `super+c`
// to that binding is the whole fix; terminals that swallow Cmd+C themselves
// (Terminal.app, iTerm2 without the protocol) are unaffected either way.
//
// WHAT SPLICE 3 TOUCHES
// In TuiAltScreen (bundled from `packages/pi-tui/src/tui-alt-screen.ts`) the
// mouse-release handler ends a drag selection with three statements: copy,
// repaint, return. `off` removes the first one. `copySelectionToClipboard`
// writes the selection to the clipboard over OSC 52 and flashes "Copied!".
//
// The selection highlight is *not* cleared by that handler, so with the copy
// gone the marking stays on screen until the next click — which is the point
// of the setting: mark without clobbering the clipboard.
//
// THE MARKER COMMENT
// Splice 3's replacement (`requestRender(); return;`) is a suffix of several
// other event-handler exits in the same class, so it cannot identify this patch
// on re-application. The comment it carries can, and that is all it is there
// for. It is kept ASCII on purpose: it lands in the bundle.
//
// ------------------------------------------------------------------ settings
//
// `copy_on_mark` — `on` (Kimi's own behaviour) | `off`. The copy key is wired
// up either way; this only decides whether releasing the drag copies too.

const MODE = String(settings.get('copy_on_mark', 'on')).toLowerCase();

if (!['on', 'off'].includes(MODE)) {
  throw new Error('copy_on_mark must be one of on, off'
    + ` - got "${MODE}"`);
}

let out = js;

const once = (anchor, what) => {
  const n = out.split(anchor).length - 1;
  if (n === 0) throw new Error(`${what} not found - the shape changed this release`);
  if (n !== 1) throw new Error(`${what} is not unique (${n}) - refusing to guess`);
};

// ----------------------------------------------- 1. cmd+c as well as ctrl+c

const KEYDEF_DONE = 'defaultKeys: ["ctrl+c", "super+c"]';
if (!out.includes(KEYDEF_DONE)) {
  const KEYDEF_ANCHOR = '\t\t"tui.input.copy": {\n'
    + '\t\t\tdefaultKeys: "ctrl+c",\n';

  const KEYDEF_REPLACEMENT = '\t\t"tui.input.copy": {\n'
    + `\t\t\t${KEYDEF_DONE},\n`;

  once(KEYDEF_ANCHOR, 'the tui.input.copy keybinding');
  out = out.replace(KEYDEF_ANCHOR, () => KEYDEF_REPLACEMENT);
}

// -------------------------------------------- 2. the key copies a selection

if (!out.includes('keybindings.matches(data, "tui.input.copy")')) {
  const KEY_ANCHOR = '\t\t\tconst keybindings = getKeybindings();\n'
    + '\t\t\tconst isRelease = isKeyRelease(data);\n'
    + '\t\t\tconst primaryScrollable = this.getPrimaryScrollView().canScroll;';

  const KEY_REPLACEMENT = '\t\t\tconst keybindings = getKeybindings();\n'
    + '\t\t\tconst isRelease = isKeyRelease(data);\n'
    + '\t\t\tif (!isRelease && keybindings.matches(data, "tui.input.copy")\n'
    + '\t\t\t\t&& this.getSelectionBounds()) {\n'
    + '\t\t\t\tthis.copySelectionToClipboard();\n'
    + '\t\t\t\treturn { consume: true };\n'
    + '\t\t\t}\n'
    + '\t\t\tconst primaryScrollable = this.getPrimaryScrollView().canScroll;';

  once(KEY_ANCHOR, 'the handleViewportInput keybinding block');
  out = out.replace(KEY_ANCHOR, () => KEY_REPLACEMENT);
}

// ------------------------------------------------ 3. the copy on release

if (MODE === 'off' && !out.includes('copy_on_mark: off')) {
  const ANCHOR = '\t\t\t\tthis.copySelectionToClipboard();\n'
    + '\t\t\t\tthis.requestRender();\n'
    + '\t\t\t\treturn;';

  const REPLACEMENT = '\t\t\t\t// copy_on_mark: off - selection stays, clipboard untouched\n'
    + '\t\t\t\tthis.requestRender();\n'
    + '\t\t\t\treturn;';

  once(ANCHOR, 'the copySelectionToClipboard call');
  out = out.replace(ANCHOR, () => REPLACEMENT);
}

if (out === js) {
  throw new Error('already patched');
}

return out;

// Click into the composer to put the cursor there (fullscreen renderer).
//
// An earlier investigation declined to build this, on the grounds that two
// layout questions could not be settled statically. Both can — by comparing
// the two implementations rather than assuming they differ. The findings are
// written out below, because they are the whole justification for the
// arithmetic further down.
//
// ------------------------------------------------------------- what exists
//
// Mouse tracking is already on in the alt screen (`this.mouseEnabled =
// options.mouse ?? true`), SGR encoding included, and `parseSgrMouseEvent`
// hands the dispatcher `{button, x, y, release}` in absolute, zero-based
// terminal coordinates. What is missing is any route from an event to a
// component: `componentAt`, `getComponentsAt` and `hitTest` do not exist, and
// components have `handleInput` but no `handleMouse`.
//
// The tree walk is nevertheless a few lines, because every layout box already
// carries what is needed:
//
//   return { component, rect: {x, y, width, height}, clip, children, ... }
//
// `component` is populated on every box and read by nobody. `getScrollViewsAt`
// in layout.ts already walks the tree looking for `scrollView`; this patch
// does the same walk looking for the editor.
//
// -------------------------------------------- question 1: do rows line up?
//
// `Editor.render` slices `layoutText(layoutWidth)` by `this.scrollOffset`,
// while cursor motion uses `buildVisualLineMap(this.lastWidth)`. Two separate
// functions — but not two separate wrapping rules. Both iterate
// `this.state.lines`, both branch on `visibleWidth(line) <= width`, and both
// wrap with the identical call `wordWrapLine(line, width, [...this.segment(
// line, "grapheme")])`, pushing one entry per chunk. Index i therefore denotes
// the same visual line in both. The widths agree too: `render` assigns
// `this.lastWidth = layoutWidth` immediately before calling
// `layoutText(layoutWidth)`, which is why `moveCursor` can pass `lastWidth`.
//
// The one divergence is an empty editor: `layoutText` returns early with a
// single blank line, and `buildVisualLineMap` on `lines === [""]` also yields
// one entry. Same count, so the mapping survives.
//
// ------------------------------------------ question 2: rows above the text
//
// Exactly one, the top border. `CustomEditor.render` states it outright with
// `const firstContentIdx = 1`, and `Editor.render` pushes that border before
// the loop over `visibleLines`. The bottom border and the autocomplete list
// come after the text and so cannot shift it.
//
// Horizontally nothing shifts either, which is what makes a fixed column
// offset safe: `wrapWithSideBorders` is a `lines.map` that overlays column 0
// and the last column in place, and `injectPromptSymbol` swaps four leading
// spaces for `"  > "` — same length. So the text of every content row starts
// at `rect.x + paddingX`, with `paddingX` clamped exactly as `Editor.render`
// clamps it.
//
// ------------------------------------------------------------- the hook
//
// `handleSelectionMouseEvent` already separates a click from a drag, because
// it needs that distinction for hyperlinks: on release it tests
// `!this.selectionDragged` plus an unmoved anchor before treating the gesture
// as a click on a URL. Riding on that test means text selection keeps working
// unchanged — a drag never reaches this code, and a click outside the composer
// returns false and falls through to the normal selection path.
//
// --------------------------------------------------------------- limits
//
// Fullscreen only. `tui-main-screen.ts` contains no mouse code whatsoever — no
// sequences, no parser, no dispatch — so the normal renderer would need that
// machinery built first, which is a feature rather than a patch.
//
// Off by default. Set `click_cursor = on` in `patch-settings.conf`, or pick it
// in the menu. The default matches `lib/patch_settings.py`, which registers
// the same key — the two must agree, or the menu would report a state the
// patch does not honour.

// ------------------------------------------------------------------ settings

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
          const m = /^\s*click_cursor\s*=\s*([^#\s]+)/.exec(line.replace(/#.*/, ''));
          if (m) enabled = /^(on|true|1|yes)$/i.test(m[1].trim());
        }
      }
    }
  } catch {
    // An unreadable settings file must not fail the run, and must not turn a
    // patch on that the user never asked for.
    enabled = false;
  }
}

if (!enabled) {
  throw new Error('already patched');
}

if (js.includes('__tkClickCursor')) {
  throw new Error('already patched');
}

// ------------------------------------------------- 1. the helper method
//
// Injected as a class member so `this` is the alt screen without any binding
// games. Everything is wrapped in try/catch: a click that cannot be resolved
// must fall through to selection, never throw inside the input handler.

const CLASS_ANCHOR = /(TuiAltScreen = class extends TuiBase \{\s*mode = "fullscreen";)/;

const classHit = CLASS_ANCHOR.exec(js);
if (!classHit) {
  throw new Error('TuiAltScreen class head not found - minified shape changed');
}
if (js.split(classHit[1]).length - 1 !== 1) {
  throw new Error('TuiAltScreen class head is not unique - refusing to guess');
}

const METHOD = `
\t\t__tkClickCursor(event) {
\t\t\t// Bail reasons are always recorded, successes only with
\t\t\t// TWEAKKIMI_CLICK_DEBUG=1. Gating the failures behind the variable made
\t\t\t// an empty log ambiguous — it meant either "never reached" or "you
\t\t\t// forgot the variable", and we lost a round trip to exactly that.
\t\t\tconst __tkDbg = typeof process !== "undefined" && process.env && process.env.TWEAKKIMI_CLICK_DEBUG === "1";
\t\t\tconst __tkLog = (o) => { if (!__tkDbg) return; try {
\t\t\t\tprocess.getBuiltinModule("fs").appendFileSync("/tmp/tweakkimi-click.log", JSON.stringify(o) + "\\n");
\t\t\t} catch {} };
\t\t\ttry {
\t\t\t\tif (!this.currentLayout || (typeof this.hasOverlay === "function" && this.hasOverlay())) {
\t\t\t\t\t__tkLog({ bail: "no layout or overlay open", hasLayout: !!this.currentLayout });
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\t// The editor gets no layout box of its own: GutterContainer renders
\t\t\t\t// its children itself, so the deepest box under the pointer is the
\t\t\t\t// container. Walk the component's own children to reach the editor.
\t\t\t\tconst findEditor = (c) => {
\t\t\t\t\tif (!c) return void 0;
\t\t\t\t\tif (typeof c.buildVisualLineMap === "function" && typeof c.layoutText === "function"
\t\t\t\t\t\t&& c.state && Array.isArray(c.state.lines)) return c;
\t\t\t\t\tconst kids = c.children;
\t\t\t\t\tif (Array.isArray(kids)) for (let i = 0; i < kids.length; i++) {
\t\t\t\t\t\tconst f = findEditor(kids[i]);
\t\t\t\t\t\tif (f) return f;
\t\t\t\t\t}
\t\t\t\t\treturn void 0;
\t\t\t\t};
\t\t\t\tlet box, ed, bestDepth = -1;
\t\t\t\tconst __tkSeen = [];
\t\t\t\tconst visit = (b, depth) => {
\t\t\t\t\tif (!b) return;
\t\t\t\t\tconst c = b.component, r = b.rect;
\t\t\t\t\tconst inside = r && event.x >= r.x && event.x < r.x + r.width
\t\t\t\t\t\t&& event.y >= r.y && event.y < r.y + r.height;
\t\t\t\t\tif (inside) {
\t\t\t\t\t\tconst found = findEditor(c);
\t\t\t\t\t\tif (__tkDbg && __tkSeen.length < 12) __tkSeen.push({
\t\t\t\t\t\t\tctor: c && c.constructor ? c.constructor.name : String(c),
\t\t\t\t\t\t\teditor: found && found.constructor ? found.constructor.name : null,
\t\t\t\t\t\t\tkeys: c ? Object.keys(c).slice(0, 14) : void 0,
\t\t\t\t\t\t\trect: r, depth: depth
\t\t\t\t\t\t});
\t\t\t\t\t\t// Ancestors match too - keep the deepest, which is the container.
\t\t\t\t\t\tif (found && depth > bestDepth) { box = b; ed = found; bestDepth = depth; }
\t\t\t\t\t}
\t\t\t\t\tconst kids = b.children || [];
\t\t\t\t\tfor (let i = 0; i < kids.length; i++) visit(kids[i], depth + 1);
\t\t\t\t};
\t\t\t\tvisit(this.currentLayout.root, 0);
\t\t\t\tif (!box) {
\t\t\t\t\t__tkLog({ bail: "no editor under the pointer", click: { x: event.x, y: event.y }, candidates: __tkSeen });
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\tconst holder = box.component;
\t\t\t\tconst leftPad = holder && typeof holder.leftPad === "number" ? holder.leftPad : 0;
\t\t\t\tconst rightPad = holder && typeof holder.rightPad === "number" ? holder.rightPad : 0;
\t\t\t\tconst inner = Math.max(1, box.rect.width - leftPad - rightPad);
\t\t\t\t// Children are stacked vertically inside the container, so anything
\t\t\t\t// rendered above the editor shifts its rows down.
\t\t\t\tlet before = 0;
\t\t\t\tif (holder !== ed) {
\t\t\t\t\tconst sibs = Array.isArray(holder.children) ? holder.children : [];
\t\t\t\t\tlet reached = false;
\t\t\t\t\tfor (let i = 0; i < sibs.length; i++) {
\t\t\t\t\t\tif (sibs[i] === ed || findEditor(sibs[i]) === ed) { reached = true; break; }
\t\t\t\t\t\ttry { before += sibs[i].render(inner).length; } catch {}
\t\t\t\t\t}
\t\t\t\t\tif (!reached) {
\t\t\t\t\t\t__tkLog({ bail: "editor is nested deeper than a direct child", rect: box.rect,
\t\t\t\t\t\t\tholder: holder && holder.constructor ? holder.constructor.name : null, siblings: sibs.length });
\t\t\t\t\t\treturn false;
\t\t\t\t\t}
\t\t\t\t}
\t\t\t\tconst row = event.y - box.rect.y - before;
\t\t\t\t// Row 0 is the editor's own top border; content starts at row 1.
\t\t\t\tif (row < 1) {
\t\t\t\t\t__tkLog({ bail: "click on the top border row", row: row, before: before, rect: box.rect, click: { x: event.x, y: event.y } });
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\tconst vis = ed.buildVisualLineMap(ed.lastWidth);
\t\t\t\tconst vl = vis[(ed.scrollOffset || 0) + (row - 1)];
\t\t\t\tif (!vl) {
\t\t\t\t\t__tkLog({ bail: "no visual line at that row", row: row, before: before, scrollOffset: ed.scrollOffset,
\t\t\t\t\t\tlastWidth: ed.lastWidth, visualLines: vis.length, rect: box.rect });
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\t// injectPromptSymbol overwrites the first four cells and
\t\t\t\t// wrapWithSideBorders only overlays column 0, so neither shifts the
\t\t\t\t// text: it starts at the container's leftPad plus the editor padding.
\t\t\t\tconst pad = typeof ed.paddingX === "number" ? ed.paddingX : 4;
\t\t\t\tconst textX = box.rect.x + leftPad + pad;
\t\t\t\tconst col = Math.max(0, Math.min(event.x - textX, vl.length));
\t\t\t\tconst logical = ed.state.lines[vl.logicalLine] || "";
\t\t\t\ted.state.cursorLine = vl.logicalLine;
\t\t\t\ted.state.cursorCol = Math.min(vl.startCol + col, logical.length);
\t\t\t\tif (ed.snappedFromCursorCol !== undefined) ed.snappedFromCursorCol = null;
\t\t\t\tif (ed.lastAction !== undefined) ed.lastAction = null;
\t\t\t\t__tkLog({
\t\t\t\t\tok: true, click: { x: event.x, y: event.y }, rect: box.rect,
\t\t\t\t\tholder: holder && holder.constructor ? holder.constructor.name : null,
\t\t\t\t\tleftPad: leftPad, before: before, row: row, pad: pad, textX: textX,
\t\t\t\t\tscrollOffset: ed.scrollOffset, lastWidth: ed.lastWidth, paddingX: ed.paddingX,
\t\t\t\t\tvisualLines: vis.length, vl: vl, col: col,
\t\t\t\t\tcursor: { line: ed.state.cursorLine, col: ed.state.cursorCol }, text: logical
\t\t\t\t});
\t\t\t\treturn true;
\t\t\t} catch { return false; }
\t\t}`;

let out = js.replace(CLASS_ANCHOR, (m0, head) => head + METHOD);

// ------------------------------------------------- 2. the call site
//
// Spliced in after the existing click-versus-drag test in the release branch.
// `clickedUrl` is checked first so a click on a hyperlink keeps opening it.

const HOOK_ANCHOR = /const clickedUrl = !this\.selectionDragged[\s\S]{0,360}?this\.pressedUrl = void 0;/;

const hookHit = HOOK_ANCHOR.exec(out);
if (!hookHit) {
  throw new Error('release-branch click test not found - minified shape changed');
}

const hookText = hookHit[0];
if (out.split(hookText).length - 1 !== 1) {
  throw new Error('release-branch click test is not unique - refusing to guess');
}

// The gate is logged before it is evaluated, but only under the debug
// variable. This line earned its place: `__tkClickCursor` never runs when the
// `&&` chain short-circuits, so an empty log was ambiguous between "release
// branch never reached" and "one of the flags was set". Logging the flags here
// is what finally told the two apart.
const CALL =
  '\n\t\t\t\tif (typeof process !== "undefined" && process.env && process.env.TWEAKKIMI_CLICK_DEBUG === "1")' +
  ' try{process.getBuiltinModule("fs").appendFileSync("/tmp/tweakkimi-click.log",' +
  'JSON.stringify({at:"release",dragged:!!this.selectionDragged,url:!!clickedUrl,' +
  'x:event.x,y:event.y,anchor:this.selectionAnchor?{row:this.selectionAnchor.row,col:this.selectionAnchor.col}:null})' +
  '+"\\n")}catch{}' +
  '\n\t\t\t\tif (!clickedUrl && !this.selectionDragged && this.__tkClickCursor(event)) ' +
  '{ this.selectionAnchor = void 0; this.selectionFocus = void 0; this.requestRender(); return; }';

out = out.replace(hookText, () => hookText + CALL);

return out;

# Mausklick setzt den Cursor — wie es funktioniert

Bezieht sich auf Kimi Code 0.36.0 und `patches/40-click-to-position-cursor.js`.
Alle Angaben sind am extrahierten Bundle belegt; die Modulpfade stammen aus den
`//#region`-Kommentaren, die der Bundler stehen lässt.

**Nur im Vollbildmodus.** `packages/pi-tui/src/tui-main-screen.ts` enthält
keinerlei Maus-Code — im normalen Renderer gibt es nichts, woran ein Patch
ansetzen könnte. Wer den Klick will, braucht `KIMI_CODE_TUI_FULL_SCREEN=1`.

---

## Die Kette, von der Maustaste bis zum Cursor

Fünf Stufen. Die ersten vier gehören Kimi, nur die fünfte ist unser Patch.

```
Terminal  ──1──▶  Escape-Sequenz  ──2──▶  parseSgrMouseEvent
                                              │
                                              3
                                              ▼
                                    handleSelectionMouseEvent
                                              │
                                              4  (Release-Zweig)
                                              ▼
                                    __tkClickCursor(event)   ◀── 5, unser Code
```

### 1. Kimi schaltet das Maus-Tracking ein

`packages/pi-tui/src/tui-alt-screen.ts`, beim Start des Alt-Screens:

```js
this.mouseEnabled = options.mouse ?? true;
`${ENTER_ALT_SCREEN}${DISABLE_AUTOWRAP}${this.mouseEnabled ? mouseSequence : ""}…`
```

Das ist **standardmäßig an**, ohne Konfigurationsschalter — die Option `mouse`
setzt niemand. Welche Sequenz geschrieben wird, hängt vom Terminal ab:

| Konstante | Sequenz | wann |
|---|---|---|
| `ENABLE_BUTTON_MOTION_MOUSE` | `?1000h ?1002h ?1004h ?1006h` | unter `STY`, `tmux`, `screen` |
| `ENABLE_ALL_MOTION_MOUSE` | zusätzlich `?1003h` | sonst |

Entscheidend ist `?1006h`: das SGR-Format. Ohne dieses meldet ein Terminal
Spalten jenseits von 223 nicht mehr korrekt. Beim Beenden schreibt Kimi
`DISABLE_MOUSE`.

### 2. Kimi parst die Meldung selbst

```js
parseSgrMouseEvent(data)   //  /^\x1b\[<(\d+);(\d+);(\d+)([Mm])$/
```

Ergebnis ist `{button, x, y, release}` mit **absoluten, nullbasierten**
Terminalkoordinaten. `M` ist Drücken, `m` Loslassen.

### 3. Kimis eigene Verteilung

```js
const mouseEvent = this.parseSgrMouseEvent(data);
if (mouseEvent) {
  if (this.handleRightClickPaste(mouseEvent)) return { consume: true };
  const handled = this.handleScrollbarMouseEvent(mouseEvent);
  if (!this.scrollbarDrag) this.updateScrollbarHover(mouseEvent.x, mouseEvent.y);
  if (!handled) this.handleSelectionMouseEvent(mouseEvent);
  return { consume: true };
}
```

Die Kette ist **geschlossen**: Rechtsklick-Einfügen, Scrollbar, Hover,
Textauswahl — danach `consume: true`. Es gibt keinen Weg zu Komponenten;
`componentAt`, `getComponentsAt` und `hitTest` haben je null Treffer, und ein
`handleMouse` als Gegenstück zu `handleInput` existiert nicht. Deshalb muss ein
Patch sich in diese Kette einhängen, statt einen vorgesehenen Steckplatz zu
benutzen.

### 4. Der Release-Zweig — hier greift der Patch

In `handleSelectionMouseEvent`, beim Loslassen:

```js
const clickedUrl = !this.selectionDragged
  && this.selectionAnchor.scrollView === point.scrollView
  && this.selectionAnchor.row === point.row
  && this.selectionAnchor.col === point.col
  ? this.pressedUrl : void 0;
this.pressedUrl = void 0;
if (clickedUrl && this.openUrl) { … return; }
this.copySelectionToClipboard()          // ← das Kopieren beim Klick
```

Der Patch fügt **zwischen** `this.pressedUrl = void 0;` und dem `if` ein:

```js
if (!clickedUrl && !this.selectionDragged && this.__tkClickCursor(event))
  { this.selectionAnchor = void 0; this.selectionFocus = void 0;
    this.requestRender(); return; }
```

Warum genau dort:

- **Nach `clickedUrl`**, damit ein Klick auf einen Link weiterhin den Link öffnet.
- **Hinter `!this.selectionDragged`**, damit Ziehen weiterhin Text markiert.
  Kimi hat diesen Test ohnehin schon, für die Hyperlink-Erkennung.
- **Vor `copySelectionToClipboard()`**, damit ein erfolgreicher Klick nicht
  zusätzlich die Zwischenablage überschreibt.

Das frühe `return` überspringt Kopieren und Selektion. Liefert
`__tkClickCursor` dagegen `false`, läuft alles wie zuvor weiter.

### 5. `__tkClickCursor(event)` — die eingefügte Methode

Vier Schritte, jeder mit einem eigenen Abbruchgrund.

---

## Den Editor finden — der eigentliche Stolperstein

**Der `CustomEditor` hat keine eigene Layout-Box.** `GutterContainer` rendert
seine Kinder selbst und verkettet die Zeilenarrays:

```js
GutterContainer = class extends Container {
  render(width) {
    const inner = Math.max(1, width - this.leftPad - this.rightPad);
    for (const child of this.children) {
      const lines = child.render(inner);
      …
```

Damit entsteht für den Editor **kein** Knoten im Layoutbaum. Eine Suche über
`box.component` findet immer nur den Container. Genau daran ist der erste
Anlauf gescheitert — das Protokoll zeigte drei Kandidaten unter dem Zeiger
(`VStack`, `VStack`, `GutterContainer`), keiner mit `buildVisualLineMap`.

Die Lösung ist zweistufig:

```js
// 1. Boxen unter dem Zeiger durchgehen (Rechteck-Test)
visit(this.currentLayout.root, 0)

// 2. in jeder Treffer-Box durch die Komponenten-Kinder absteigen
const findEditor = (c) =>
  (typeof c.buildVisualLineMap === "function"
   && typeof c.layoutText === "function"
   && c.state && Array.isArray(c.state.lines))  ? c
  : c.children?.map(findEditor).find(Boolean);
```

Erkannt wird der Editor also an **drei Merkmalen** statt am Klassennamen —
robuster gegen Umbenennungen in der Minifizierung.

Wichtig: Es wird die **tiefste** passende Box genommen, nicht die erste. Die
Vorfahren enthalten den Editor ja ebenfalls, ihr Rechteck ist aber das ganze
Fenster; mit der ersten Box wäre jede Koordinatenrechnung falsch.

---

## Von Bildschirmkoordinaten zum Textindex

### Zeile

```js
before = Summe der render(inner).length aller Geschwister ÜBER dem Editor
row    = event.y - box.rect.y - before
if (row < 1) → Klick auf die obere Rahmenzeile, abbrechen
vl     = ed.buildVisualLineMap(ed.lastWidth)[ed.scrollOffset + (row - 1)]
```

Zwei Feinheiten. Der Container stapelt Kinder untereinander, also verschiebt
alles über dem Editor dessen Zeilen nach unten — deshalb `before`. Und Zeile 0
ist der obere Rahmen, der Inhalt beginnt bei 1; `CustomEditor.render` sagt das
selbst mit `const firstContentIdx = 1`.

`buildVisualLineMap` liefert Einträge `{logicalLine, startCol, length}`, also
die Zuordnung von umgebrochenen Bildschirmzeilen zu logischen Textzeilen.

### Spalte

```js
pad   = ed.paddingX ?? 4
textX = box.rect.x + leftPad + pad
col   = clamp(event.x - textX, 0, vl.length)
```

Dass keine weiteren Zuschläge nötig sind, folgt aus dem Renderpfad:
`injectPromptSymbol` **überschreibt** die ersten vier Zellen
(`"  " + symbol + " " + line.slice(4)`), und `wrapWithSideBorders` überlagert
nur Spalte 0 und die letzte Spalte, ausdrücklich nur dort, wo Leerzeichen
stehen. Beide verschieben den Text also nicht.

Gegenprobe an einem echten Bildschirm: Spalte 1 ist `│`, Spalte 3 das `>`, ab
Spalte 5 beginnt der Text — genau `rect.x + leftPad + paddingX`.

### Setzen

```js
ed.state.cursorLine = vl.logicalLine;
ed.state.cursorCol  = Math.min(vl.startCol + col, logical.length);
ed.snappedFromCursorCol = null;   // vertikale Spaltenerinnerung verwerfen
ed.lastAction = null;
```

Die beiden letzten Zeilen sind nicht kosmetisch: `snappedFromCursorCol` merkt
sich die Wunschspalte beim Auf- und Abwandern, `lastAction` steuert das
Zusammenfassen von Rückgängig-Schritten. Beide müssen nach einem Sprung
zurückgesetzt werden, sonst springt der Cursor bei der nächsten Pfeiltaste an
die alte Spalte.

---

## Diagnose

```
TWEAKKIMI_CLICK_DEBUG=1 kimi
```

schreibt nach `/tmp/tweakkimi-click.log`, eine JSON-Zeile je Klick. Im
Erfolgsfall alles von `rect` über `before`, `scrollOffset`, `textX` bis zum
gesetzten `cursor`. Im Fehlerfall einer von fünf Abbruchgründen:

| `bail` | Bedeutung |
|---|---|
| `no layout or overlay open` | kein `currentLayout`, oder ein Overlay liegt darüber |
| `no editor under the pointer` | keine Box mit Editor darin; listet alle Kandidaten samt `keys` |
| `editor is nested deeper than a direct child` | Editor ist kein direktes Kind des Containers |
| `click on the top border row` | Klick auf die obere Rahmenzeile |
| `no visual line at that row` | Zeilenindex außerhalb der Zeilenzuordnung |

Zusätzlich wird die **Bedingung selbst** protokolliert, bevor sie ausgewertet
wird (`{"at":"release","dragged":…,"url":…}`). Das ist die Lehre aus dem
teuersten Fehlschlag: Bei einem kurzschließenden `&&` läuft die Methode gar
nicht erst an und kann deshalb auch ihr eigenes Scheitern nicht melden. Ein
leeres Protokoll war dadurch doppeldeutig — „Zweig nie erreicht" oder „Flag
blockiert". Der Eintrag vor der Bedingung trennt beides.

---

## Was bei einem Kimi-Update bricht

Der Patch hängt an vier Ankern. Jeder bricht **laut**, nicht still:

1. `TuiAltScreen`-Klassenkopf — hier wird die Methode eingehängt.
2. Der Release-Zweig, erkannt an `const clickedUrl = !this.selectionDragged…`.
3. Die drei Merkmale des Editors: `buildVisualLineMap`, `layoutText`,
   `state.lines`.
4. Die Feldnamen `leftPad`, `paddingX`, `scrollOffset`, `lastWidth`,
   `state.cursorLine`, `state.cursorCol`.

Punkt 3 und 4 sind die wackligsten, weil sie unminifizierte Feldnamen
voraussetzen. Bricht etwas, ist der erste Griff das Debug-Protokoll: Der
`candidates`-Eintrag listet zu jeder Box den Konstruktornamen und die ersten
14 Feldnamen der Komponente — damit ist ohne Raten sichtbar, wie der Editor
jetzt heißt und woran er zu erkennen wäre.

---

## Was Kimi von Haus aus mit der Maus tut

Zur Abgrenzung, damit man nicht Kimis Verhalten für einen Patch-Effekt hält:

- **Textauswahl** durch Ziehen, mit `copySelectionToClipboard()` beim
  Loslassen — **auch ohne Ziehen**. Das Kopieren beim einfachen Klick ist also
  Kimis eigener Code.
- **Rechtsklick fügt ein** (`handleRightClickPaste`).
- **Scrollbar** lässt sich ziehen, mit Hover-Hervorhebung.
- **Hyperlinks** öffnen sich bei einem Klick ohne Ziehen.

Alles davon bleibt unberührt: Der Patch greift nur, wenn nicht gezogen wurde,
kein Link getroffen ist und der Zeiger über dem Eingabefeld steht.

---

## Und Claude Code?

Der Anlass für diesen Patch war die Annahme, Claude Code könne das und man
müsse es nur übertragen. **Das trifft nicht zu.** Im Bundle von Claude Code
2.1.231 gibt es null Treffer für jede Maus-Aktivierungssequenz — kein
`?1000h`, `?1002h`, `?1003h`, `?1006h` —, kein SGR-Parsing und kein
`enableMouse`. Die zahlreichen `onMouse`-Fundstellen sind Handler-Namen der
Renderer-Bibliothek, also definierte Steckplätze ohne aktiviertes Reporting.

Was Claude Code im Vollbildmodus anbietet, sind zwei Einstellungen, beide
wörtlich „(fullscreen mode only)": `autoScrollEnabled` und
`wheelScrollAccelerationEnabled` — Mausrad-Scrollen, das vom Terminal kommt.
Passend dazu der eingebaute Rat, `set -g mouse on` in die tmux-Konfiguration zu
schreiben.

Kimi ist an dieser Stelle also weiter als das Vorbild.

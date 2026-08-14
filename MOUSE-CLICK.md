# Maus im Terminal — Grundlagen und Umsetzung

Referenz für alles, was mit Mausereignissen in einer Terminal-Anwendung zu tun
hat. Entstanden aus der Arbeit an Kimi und am tweakkimi-Menü.

Der Sonderfall „Klick setzt den Textcursor in Kimis Eingabefeld" hat eine
eigene Datei: **`CURSOR-CLICK.md`**. Hier steht das Fundament darunter.

---

## Das Grundprinzip

Ein Terminal meldet Mausereignisse **nicht von sich aus**. Die Anwendung muss
das Melden erst einschalten, indem sie eine Escape-Sequenz auf stdout schreibt.
Danach kommen Klicks als Escape-Sequenzen auf **stdin** zurück — im selben
Strom wie Tastatureingaben. Wer schon Pfeiltasten liest, liest Mausereignisse
mit derselben Maschinerie.

```
Anwendung ──"\x1b[?1000h"──▶ Terminal          Melden einschalten
Anwendung ◀──"\x1b[<0;27;5M"── Terminal        Klick auf Spalte 27, Zeile 5
Anwendung ──"\x1b[?1000l"──▶ Terminal          Melden ausschalten
```

Das `h` am Ende schaltet ein, das `l` aus. Diese Konvention gilt für alle
Modi — `?25h` zeigt den Cursor, `?25l` verbirgt ihn, und so weiter.

---

## Die Modi

| Sequenz | Name | meldet |
|---|---|---|
| `?1000h` | Normal tracking | Drücken und Loslassen von Tasten |
| `?1002h` | Button-event tracking | zusätzlich Bewegung **mit gedrückter Taste** |
| `?1003h` | Any-event tracking | zusätzlich **jede** Bewegung |
| `?1004h` | Focus tracking | Fenster bekommt oder verliert den Fokus |
| `?1006h` | SGR-Kodierung | ändert das **Format** der Meldungen |
| `?1015h` | urxvt-Kodierung | Alternative zu 1006, kaum gebraucht |
| `?1049h` | Alternate screen | eigener Bildschirmpuffer, nicht maus-spezifisch |

Zwei Dinge sind wichtig zu verstehen.

**`?1006` ist kein Tracking-Modus, sondern ein Format.** Es wird zusätzlich zu
1000, 1002 oder 1003 gesetzt und ändert nur, wie die Meldungen aussehen. Ohne
es kommt die alte X10-Kodierung, die Koordinaten als einzelne Bytes mit einem
Versatz von 32 überträgt — jenseits von Spalte 223 bricht das zusammen. Auf
einem breiten Terminal ist `?1006h` also Pflicht.

**Mehr Tracking heißt mehr Datenverkehr.** `?1003h` meldet jede
Mausbewegung, auch ohne gedrückte Taste. Wer nur Klicks braucht, nimmt `?1000h`
und spart sich den Strom an Bewegungsmeldungen.

---

## Das SGR-Format

```
\x1b[<{button};{col};{row}{M|m}
```

- **`button`** — welche Taste, plus Zusatzbits, siehe unten
- **`col`, `row`** — Spalte und Zeile, **einsbasiert** (links oben ist `1;1`)
- **`M`** — Taste gedrückt, **`m`** — Taste losgelassen

Beispiel: `\x1b[<0;27;5M` heißt linke Taste gedrückt auf Spalte 27, Zeile 5.

Ein passender regulärer Ausdruck, so macht es auch Kimi:

```python
re.compile(r'\x1b\[<(\d+);(\d+);(\d+)([Mm])')
```

### Die Button-Codes

Der Wert ist eine Bitmaske. Die unteren zwei Bits nennen die Taste, darüber
liegen Zusatzbits:

| Wert | Bedeutung |
|---|---|
| `0` | linke Taste |
| `1` | mittlere Taste |
| `2` | rechte Taste |
| `+4` | Shift gehalten |
| `+8` | Meta/Alt gehalten |
| `+16` | Ctrl gehalten |
| `+32` | Bewegung mit gedrückter Taste (Ziehen) |
| `64` | Mausrad hoch |
| `65` | Mausrad runter |

Ein `ctrl`-Linksklick meldet also `16`, ein Ziehen mit der linken Taste `32`.
Für einfache Anwendungen genügt meist `button & 3` für die Taste und ein Test
auf `64`/`65` für das Rad.

---

## Die Aufräumpflicht

**Das Ausschalten gehört in ein `finally`.** Bleibt Tracking an, nachdem die
Anwendung endet, schreibt das Terminal bei jeder Mausbewegung Escape-Sequenzen
in die Shell — sichtbar als Zeichenmüll, und zwar dauerhaft, bis die Shell neu
startet oder jemand `printf '\033[?1000l'` von Hand eingibt.

Dasselbe gilt für den Rohmodus des Terminals. Beides zusammen:

```python
import sys, termios, tty

fd = sys.stdin.fileno()
saved = termios.tcgetattr(fd)
try:
    sys.stdout.write('\x1b[?1000h\x1b[?1006h')
    sys.stdout.flush()
    tty.setcbreak(fd)
    ...
finally:
    sys.stdout.write('\x1b[?1000l\x1b[?1006l')
    sys.stdout.flush()
    termios.tcsetattr(fd, termios.TCSADRAIN, saved)
```

Der `finally`-Block muss auch bei Strg-C laufen, also `KeyboardInterrupt`
mitdenken. Ein Absturz ohne Aufräumen hinterlässt eine unbrauchbare Shell —
das ist der einzige Fehler in diesem Bereich, der dem Nutzer wirklich wehtut.

---

## Kein TTY, kein Tracking

Läuft die Anwendung mit umgeleitetem stdin oder stdout, gibt es keine Maus.
Das ist kein Fehlerfall, sondern der Normalfall in Skripten und Tests:

```python
if not sys.stdin.isatty() or not sys.stdout.isatty():
    ...  # Tastaturpfad, kein Tracking einschalten
```

Ebenso meldet nicht jedes Terminal Mausereignisse, auch wenn man sie
einschaltet. Die Anwendung muss ohne sie vollständig bedienbar bleiben — Maus
ist eine Zugabe, nie der einzige Weg.

Unter **tmux** und **screen** ist zusätzlich `set -g mouse on` in der
Konfiguration nötig, sonst fängt der Multiplexer die Ereignisse ab. Kimi trägt
dem Rechnung, indem es unter `STY`, `tmux` oder `screen` die sparsamere
Sequenz ohne `?1003h` schreibt.

---

## Wie Kimi es macht

Zum Vergleich, weil es ein vollständiges Beispiel ist. In
`packages/pi-tui/src/tui-alt-screen.ts`:

```js
this.mouseEnabled = options.mouse ?? true;
ENABLE_BUTTON_MOTION_MOUSE = "\x1b[?1000h\x1b[?1002h\x1b[?1004h\x1b[?1006h"
ENABLE_ALL_MOTION_MOUSE    = "\x1b[?1000h\x1b[?1002h\x1b[?1003h\x1b[?1004h\x1b[?1006h"
```

Standardmäßig an, ohne Konfigurationsschalter. Geparst wird mit
`parseSgrMouseEvent`, verteilt in dieser Reihenfolge:

1. `handleRightClickPaste` — Rechtsklick fügt ein
2. `handleScrollbarMouseEvent` — Scrollbar ziehen
3. `updateScrollbarHover` — Hervorhebung unter dem Zeiger
4. `handleSelectionMouseEvent` — Textauswahl, mit
   `copySelectionToClipboard()` beim Loslassen
5. `return { consume: true }` — die Kette endet hier

Bemerkenswert: Es gibt **keinen** Weg zu einzelnen Komponenten.
`componentAt`, `getComponentsAt`, `hitTest` haben je null Treffer, und ein
`handleMouse` als Gegenstück zu `handleInput` existiert nicht. Wer in Kimi
Klick-Interaktion nachrüsten will, muss sich in diese Kette einhängen — genau
das beschreibt `CURSOR-CLICK.md`.

Ein Detail, das leicht für einen Patch-Effekt gehalten wird: Das Kopieren beim
Loslassen passiert **auch ohne Ziehen**. Wer klickt, hat danach die vorherige
Auswahl in der Zwischenablage. Das ist Kimis eigener Code.

## Und Claude Code

Gar nicht. Im Bundle von 2.1.231 gibt es null Treffer für `?1000h`, `?1002h`,
`?1003h`, `?1006h`, kein SGR-Parsing, kein `enableMouse`. Die vielen
`onMouse`-Fundstellen sind Handler-Namen der Renderer-Bibliothek — definierte
Steckplätze ohne aktiviertes Reporting.

Was Claude Code im Vollbildmodus bietet, sind `autoScrollEnabled` und
`wheelScrollAccelerationEnabled`, beide wörtlich „(fullscreen mode only)".
Das ist Mausrad-Scrollen, das vom Terminal kommt — passend zum eingebauten Rat,
`set -g mouse on` in die tmux-Konfiguration zu schreiben.

---

## Im eigenen Code: das tweakkimi-Menü

Hier ist es ungleich einfacher als in fremdem, minifiziertem Code: Wir zeichnen
das Menü selbst und kennen jede Bildschirmzeile.

**Umsetzung** in `lib/keyreader.py` und `lib/main-menu.py`:

- Tracking wird beim Betreten des Menüs eingeschaltet und im selben
  `finally` wieder aus, in dem auch die Terminalattribute zurückgesetzt werden.
- `?1000h` genügt — Bewegungsmeldungen brauchen wir nicht.
- Der Klick wird beim **Loslassen** ausgewertet, nicht beim Drücken. Das
  entspricht der Erwartung und schluckt versehentliches Ziehen.
- Beim Zeichnen merkt sich das Menü, welcher Eintrag in welcher Zeile steht.
  Ein Klick schlägt in dieser Zuordnung nach — keine Rückrechnung nötig.
- Ein Klick auf eine Eintragszeile wählt **und** öffnet in einem Schritt. Auf
  einer `‹›`-Zeile schaltet er den Wert weiter. Kopf, Banner und Trennlinien
  sind tot.

Die Tastaturbedienung bleibt unverändert; die Maus kommt dazu.

---

## Fehlersuche

**Zeichenmüll in der Shell nach dem Beenden.** Tracking wurde nicht
ausgeschaltet. Sofortlösung:

```
printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l'
```

**Nichts passiert beim Klicken.** In dieser Reihenfolge prüfen: Ist stdin ein
TTY? Wurde die Einschaltsequenz wirklich geschrieben und geflusht? Läuft ein
Multiplexer ohne `set -g mouse on`? Frisst ein Terminal-Emulator die Klicks für
eigene Zwecke — iTerm2 und Terminal.app tun das bei gedrückter Alt-Taste?

**Koordinaten stimmen nicht.** SGR ist einsbasiert, viele Layoutmodelle sind
nullbasiert. Und ohne `?1006h` gilt die X10-Kodierung mit Versatz 32, die
jenseits von Spalte 223 unbrauchbar ist.

**Zum Mitlesen der rohen Sequenzen** genügt:

```
cat -v
```

Dann Tracking von Hand einschalten (`printf '\033[?1000h\033[?1006h'`) und
klicken — die Sequenzen erscheinen im Klartext. `\033[?1000l` schaltet wieder
ab.

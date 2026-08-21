# Was Kimi selbst über seine Funktionen verrät

Quelle: `src/tui/constant/tips.ts` im extrahierten Bundle — die Liste der
Hinweise, die in der Statuszeile rotieren. Sie ist die verlässlichste Spur zu
Funktionen, die in keiner Hilfe stehen, weil die Entwickler sie genau dafür
geschrieben haben. Einträge tragen teils ein `priority`-Feld.

## Die 22 Tipps, wörtlich

| Tipp | verrät |
|---|---|
| `Try /dance for a hidden Easter egg` | **ein verstecktes Kommando** |
| `/auto when you want Kimi to handle approvals and keep going unattended` | vollautonomer Modus |
| `/yolo to skip most approvals for trusted batch work, only use it in repos you trust` | Freigabemodus samt Warnung |
| `/goal for multi-step work with a clear finish line` | Zielverwaltung |
| `/goal next to queue follow-up work while the current goal keeps running` | Folgearbeit einreihen, während ein Ziel läuft |
| `/tasks to check progress and status for background tasks` | Hintergrundaufgaben |
| `/sessions to browse and resume earlier sessions` | Sitzungswechsel |
| `/compact compresses context when it gets long` | Kontextverdichtung |
| `/init: generate AGENTS.md` | Projektdatei erzeugen |
| `/web: use the Web UI for a better experience` | Weboberfläche |
| `/theme to switch the terminal UI theme` | Themenwechsel |
| `/model: switch model` | Modellwechsel |
| `/plugins: manage plugins — try the "Kimi Datasource" …` | ein empfohlenes Datenquellen-Plugin |
| `/help: show commands` | Hilfe |
| `ctrl-s to add guidance without waiting for the turn to finish` | **Hinweis nachreichen, ohne zu unterbrechen** |
| `ctrl-o to hide or reveal tool output …` | Werkzeugausgabe ein- und ausblenden |
| `shift-tab to Plan mode to review the approach before Kimi edits files.` | Planmodus per Tastenkürzel |
| `shift+enter: newline` | mehrzeilige Eingabe |
| `ctrl+c: cancel` | Abbruch |
| `@: mention files` | Dateierwähnung |
| `! to run a shell command` | Shell-Präfix |
| `ask Kimi to schedule tasks, e.g. "remind me at 5pm"` | Cron in natürlicher Sprache |

## Die eigene Statuszeile — ein früherer Befund war irreführend

Der erste Erkundungsbericht führte `KIMI_CODE_STATUS_LINE` unter „wird nie
gelesen". Das stimmt wörtlich, führt aber in die Irre: **Kimi liest die
Variable nicht, es setzt sie.** In `runStatusLineCommand(command, payload,
timeoutMs = 300)` startet Kimi ein Shell-Kommando und übergibt ihm
`KIMI_CODE_STATUS_LINE: "1"` in der Umgebung, damit das Skript erkennt, in
welchem Kontext es läuft.

Damit gibt es eine **frei programmierbare Statuszeile**, wie man sie von
Claude Code kennt:

- Das Kommando läuft über `sh -c` (unter Windows über `ComSpec`).
- Verwendet wird die **erste Zeile** der Ausgabe.
- Zeitlimit **300 ms**, danach wird der Prozessbaum abgeräumt.
- Höchstens **65536 Bytes** werden eingelesen (`STATUS_LINE_MAX_CAPTURE_BYTES`).
- Neu ausgeführt alle **1000 ms** (`STATUS_LINE_RERUN_INTERVAL_MS`).
- Das Kommando bekommt eine `payload` — deren Struktur ist noch nicht geklärt.

Der Konfigurationsschlüssel dafür ist mit hoher Wahrscheinlichkeit `command`
in `tui.toml`, einer der Schlüssel, die dort ohne erkennbaren Zweck standen.
**Nicht verifiziert** — der Zusammenhang ist plausibel, aber nicht am Code
belegt.

## Was daraus für kimi-code-mods folgt

`/dance` ist ein Fund ohne Nutzwert, aber ein Beleg dafür, dass die Tipp-Liste
Dinge enthält, die sonst nirgends stehen.

Praktisch interessant sind zwei: `/auto` als Stufe zwischen manuell und
`yolo`, und die programmierbare Statuszeile. Letztere wäre ein natürlicher
Menüpunkt — mit dem Hinweis auf das 300-ms-Zeitlimit, an dem ein zu
langsames Skript scheitert.

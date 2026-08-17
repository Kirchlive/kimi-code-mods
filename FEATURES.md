# tweakkimi — Funktionsliste

Eine Zeile je Funktion: `Name | Mechanismus | Status`. Daraus lässt sich das
Menü eines CLI bauen, deshalb die Reihenfolge, in der man den Funktionen
begegnet.

Aufgenommen wird, was tweakkimi patcht oder freischaltet. Kimis eigene
Oberfläche steht in `FINDINGS.md` und taucht hier nur auf, wo der Gewinn groß
genug für einen Menüeintrag ist — diese Zeilen sind mit `built-in` markiert.

Status: `done` im Betrieb bestätigt · `ungetestet` gebaut, aber nicht live
beobachtet · `offen` noch nicht gebaut.

```
 1. System-Prompts auslesen     | lib/extract-prompts.py                    | done
 2. System-Prompts ersetzen     | lib/apply-prompt-overrides.py             | done
 3. JS-Bundle extrahieren       | lib/sea.py extract                        | done
 4. Binary packen + signieren   | lib/sea.py repack/sign, install_binary()  | done
 5. Baseline einfrieren         | baseline/kimi-<version>                   | done
 6. Original wiederherstellen   | kimi-patch.sh --restore                   | done
 7. JavaScript-Patches anwenden | lib/run-patches.mjs, patches/*.js         | done
 8. Patch-Zustand anzeigen      | kimi-patch.sh --status                    | done
 9. Prompt-Kosten berichten     | lib/prompt-cost.py                        | done
10. Werkzeug-Kosten berichten   | lib/list-tools.py                         | done
11. Overrides mitmigrieren      | lib/migrate-prompts.py                    | done
12. Nach Update neu patchen     | lib/kimi-guard.sh + launchd               | ungetestet
13. Systemdateien fernhalten    | lib/os-cruft.txt                          | done
14. Testsuite                   | test.sh, test.sh --full                   | done
15. Beispiel-Patch (Banner)     | patches/00-banner.js                      | done

16. Eingebaute Tools abschalten | built-in: [tools] disabled in config.toml | done
17. Vollbild-Renderer           | built-in: KIMI_CODE_TUI_FULL_SCREEN=1     | done
18. Transkript-Fenster kürzen   | built-in: KIMI_CODE_TUI_MAX_TURNS u. a.   | offen
19. Shell-Hooks auf 20 Events   | built-in: [hooks] in config.toml          | wirkungslos
20. Modell je Subagent          | built-in: Flag secondary-model            | schaltbar

21. Konfigurations-Untermenü    | kimi-patch.sh --config-menu               | done
29. Haupt-CLI (Dach über allem) | ./tweakkimi.sh bzw. --menu                | done
30. Cursor per Klick setzen     | patches/40-…, click_cursor in patch-settings.conf | done
31. Arbeitsverzeichnis wechseln | patches/30-wd-command.js (neue Sitzung)   | done
26. Launcher für Env-Schalter   | bin/kimi + env-profile.conf, --env        | done
27. Kommando-Vorschau 50 %      | patches/10-command-preview-half-height.js | done
32. Vorschlagsliste-Höhe        | patches/20-…, suggestion_height in patch-settings.conf | done
28. Zusätzliche Skill-Verzeichn.| built-in: extra_skill_dirs                | done
22. System-Prompt kürzen        | Override system.plain.md, braucht Presets | offen
23. Eingebaute Skills abschalten| built-in: builtinProductSkills=false      | done
24. Profil-Presets              | Overrides für agent/coder/explore/plan    | offen
25. Preset teilen               | Prompt-Baum als Diff-Bündel exportieren   | offen

33. Pfeilnavigation überall     | lib/menu.py, jeder Bildschirm ein Screen  | done
34. Einstellungskanal für Patches| lib/run-patches.mjs reicht `settings` durch | done
35. Patch-Testsuite             | lib/test_patches.mjs, auch gegen das Bundle | done
36. Projektdateien: CLAUDE.md &c| patches/50-agents-md-names.js             | done
37. Zeilennummern beim Read     | patches/55-read-line-numbers.js           | ungetestet
38. Ausgeklappt statt gefaltet  | patches/74-expanded-by-default.js         | ungetestet
39. Plan ohne Rückfrage         | patches/77-auto-accept-plan.js            | ungetestet
40. Read-Grenzen anheben        | patches/79-read-limits.js                 | ungetestet
41. Effort je Turn (Router)     | patches/80-effort-router.js               | ungetestet
42. Spinner-Zeichen und -Tempo  | patches/70-spinner-style.js               | ungetestet
43. Denk-Verben rotieren        | patches/71-thinking-verbs.js              | ungetestet
44. Eigene Nachricht gestalten  | patches/72-user-message.js                | ungetestet
45. Composer-Rahmen             | patches/73-input-box-border.js            | ungetestet
46. Theme-Editor                | lib/theme-menu.py, ~/.kimi-code/themes/   | ungetestet
47. Reasoning per Umgebung      | built-in: KIMI_MODEL_THINKING_EFFORT      | ungetestet
48. Reasoning per config.toml   | built-in: [thinking], config-menu Punkt 7 | ungetestet
49. Werkzeug-Presets            | toolsets.conf, config-menu Punkt 8        | ungetestet
```

Zeile 36 ist eingeschaltet, angewandt und im installierten Binary
nachgewiesen: `AGENTS_MD_PLAIN_NAMES = ["AGENTS.md", "agents.md", "CLAUDE.md",
"claude.md"]`, ad-hoc signiert, startet und meldet 0.36.0.

`ungetestet` heißt bei den übrigen genau eine Sache: der Patch findet seine Anker im
echten Bundle, verändert es, weigert sich beim zweiten Anwenden und das Ganze
ergibt zusammen noch gültiges JavaScript — das prüft `lib/test_patches.mjs`
gegen `.work/bundle.js`. Was noch aussteht, ist die Beobachtung in einer
laufenden Sitzung. Bei den Zeilen 36 bis 45 ist das ein Patchlauf und ein
Blick; bei 41 ist es mehr, siehe unten.

## Bewusst nicht gebaut

Drei Punkte aus der tweakcc-Liste sind geprüft und verworfen, statt halb
umgesetzt zu werden.

**Per-Skill-Schalter.** Kimis einziger Hebel dafür ist der Frontmatter-Schlüssel
`disable-model-invocation` in der Skill-Datei selbst. Ein Menü, das den setzt,
bearbeitet fremde Inhalte statt tweakkimis eigene Konfiguration — eine andere
Art von Eingriff als alles andere hier. Global geht es weiter über
`builtin_product_skills` und `extra_skill_dirs`.

**Better Claude in Chrome.** Belegt ist nur, dass Kimi `mcpServers` liest. Dass
die Brücke daran funktioniert, ist nicht geprüft, und ein Installer, der ein
fremdes Repository holt und verdrahtet, ohne dass jemand das Ergebnis gesehen
hat, wäre genau die Art Arbeit, die hier nichts zu suchen hat.

**Klassifikator-Modell für den Effort-Router.** tweakcc fragt dafür Haiku in
einem Seitenaufruf. Kimi hat keinen solchen Helfer zum Ausleihen, also wäre das
ein zweiter Anfrageweg innerhalb eines Patches — ein Feature, kein Patch. Der
Router in Zeile 41 entscheidet stattdessen nach einer Regel, die man in zehn
Sekunden liest; sie ist am Rand schlechter und sagt das im Kopfkommentar.

## Anmerkungen zu den nicht offensichtlichen Zeilen

**12** — Der Wächter ist gebaut und hat 16 grüne Tests, aber der launchd-Agent
wurde nie installiert. Ein echtes Auto-Update hat er also noch nicht überstanden.

**16** — Live bestätigt am 2026-08-13: mit
`disabled = ["CronCreate","CronList","CronDelete"]` antwortet Kimi auf die
Frage nach diesen Werkzeugen mit `NO` und zählt **23 statt 26** Werkzeuge. Die
Sektion erreicht also den Katalog, den das Modell sieht. Cron und Goal zusammen
sind rund 4.900 Token pro Turn.

**17** — Live bestätigt: `KIMI_CODE_TUI_FULL_SCREEN=1 kimi` übernimmt den
Bildschirm vollständig (Alternate-Screen-Buffer), die Shell-Historie darüber
verschwindet für die Dauer der Sitzung.

**19** — **Implementiert, aber wirkungslos.** Die Sektion ist ein Array
(`HooksConfigSchema = array(HookDefSchema)`), also ist `[[hooks]]` das richtige
TOML, das Schema ist `.strict()` und `kimi doctor` akzeptiert die Einträge; der
Service liest sie in `load()` und indiziert nach Event. Trotzdem feuerte in
0.36.0 weder `SessionStart` noch `PermissionRequest` noch `PreToolUse` — das
Testkommando schrieb keine einzige Zeile. In den Logs steht dazu nichts.
Warum, ist offen; bis dahin nicht darauf verlassen.

**20** — `/experiments` listet alle vier Flags mit Beschreibung, Quelle
(`default`) und Env-Namen und lässt sie umschalten. Dass ein zweites Modell
für Subagenten dann tatsächlich verwendet wird, ist damit noch nicht gezeigt —
dafür müsste ein Zweitmodell konfiguriert und ein Subagent beobachtet werden.

**18** — Die fünf `KIMI_CODE_TUI_*`-Variablen entscheiden, wie viel Historie je
Turn erneut gesendet wird. Das ist der einzige Hebel, der die **laufenden**
Kosten senkt statt der Startkosten — deshalb trotz `built-in` ein Menüeintrag.

**22** — Der aktive System-Prompt hat 52.386 Zeichen. Ihn zu kürzen ist echtes
Redigieren mit Verhaltensfolgen und braucht kuratierte Presets, keinen Schalter.

**23** — Bestätigt, indem Kimi mit und ohne das Flag nach seinen Skills gefragt
wurde: aus drei wird einer.

**30** — **Funktioniert**, live bestätigt am 2026-08-14 im Vollbildmodus: Ein
Klick in den Composer setzt den Cursor an die geklickte Stelle. Nur Vollbild —
`tui-main-screen.ts` enthält keinerlei Maus-Code, dort wäre es ein Feature statt
eines Patches.

Der Weg dahin über drei Fehlschläge, jeder mit eigener Lehre. Erstens: Der
`CustomEditor` taucht im Layoutbaum **nicht als eigene Box** auf, weil
`GutterContainer` seine Kinder mit `child.render(inner)` selbst rendert und die
Zeilen verkettet — `box.component` konnte ihn nie liefern. Die Suche geht jetzt
rekursiv durch `component.children` und nimmt die tiefste passende Box.
Zweitens: Der Patch protokollierte nur im Erfolgsfall, ein leeres Log bedeutete
also nichts. Drittens, und das war der eigentliche Zeitfresser: Der Aufruf
hängt hinter `!clickedUrl && !this.selectionDragged`, und bei einem
kurzschließenden `&&` läuft die Methode gar nicht erst an — auch ihr
Fehler-Logging nicht. Erst ein Protokolleintrag **vor** der Bedingung trennte
„Zweig nie erreicht" von „Flag blockiert".

Diagnose bleibt eingebaut, aber still: `TWEAKKIMI_CLICK_DEBUG=1` schreibt
Flags, Klickkoordinaten und Abbruchgründe nach `/tmp/tweakkimi-click.log`.

Zum Ausgangspunkt der Recherche: **Claude Code kann das nicht.** Sein Bundle
enthält null Maus-Aktivierungssequenzen; was es im Vollbildmodus bietet, ist
Mausrad-Scrollen über das Terminal. Kimi ist hier weiter, es aktiviert echtes
SGR-Tracking. Das Kopieren beim Loslassen ist ebenfalls Kimis eigener Code
(`copySelectionToClipboard()`), kein Nebeneffekt dieses Patches.

Die ursprüngliche Absage, zur Einordnung:
inklusive SGR-Encoding, und der Parser existiert. Die Ereignisse enden aber in
einer geschlossenen Kette — Rechtsklick-Paste, Scrollbar, Hover, Textauswahl,
dann `consume: true`. Einen Weg zu Komponenten gibt es nicht: `componentAt`,
`getComponentsAt` und `hitTest` haben je null Treffer, und ein `handleMouse`
als Gegenstück zu `handleInput` existiert nicht. Der Normalmodus enthält
überhaupt keinen Maus-Code. Ein Patch müsste außerdem annehmen, dass
`scrollOffset` (indexiert über `layoutText`) und die Cursor-Umrechnung
(`buildVisualLineMap`) dieselbe Zeilenaufteilung liefern — zwei getrennte
Implementierungen, statisch nicht entscheidbar. Interessant für später: jede
Layout-Box führt bereits ein Feld `component`, das niemand liest.

**31** — Umgesetzt, aber als **neue Sitzung im Zielverzeichnis**, nicht als
Wechsel der laufenden. Der Grund steht unten: Weg A ist nicht schwierig,
sondern verschlossen — `.config.update(` hat in `src/tui` null Treffer, und die
Session-Fassade der Oberfläche bietet Setter für Modell, Berechtigung und
Planmodus, aber keinen fürs Arbeitsverzeichnis. Statt eine Paketgrenze zu
durchbrechen, setzt `/wd` `appState.workDir` und ruft `createNewSession()` —
alles wird konsistent neu aufgebaut, weil nichts Altes überlebt. Preis: Die
Unterhaltung geht verloren, deshalb fragt das Kommando vorher nach und heißt in
der Beschreibung „start a new session in another working directory".

Laufzeitbelegt sind alle drei Prüfungen: Statuszeile, `!pwd` und ein
Datei-Werkzeug landen im neuen Verzeichnis. Der dritte Punkt ist der
aussagekräftigste — eine Datei wurde **relativ** gelesen und gefunden, was nur
geht, wenn die Werkzeuge tatsächlich gegen das neue Verzeichnis aufgebaut
wurden. `/wd ~` löst auf, `/wd /nonexistent` lehnt ab, ohne die Sitzung zu
beschädigen, `/wd` ohne Argument zeigt das aktuelle Verzeichnis.

Zur ursprünglichen Absage, die weiterhin gilt:
`config.update({cwd})` setzt kaos neu und baut die Builtin-Tools neu auf, was
nötig ist, weil `BashTool` sein `cwd` im Konstruktor festhält. Die TUI erreicht
diesen Pfad aber nicht — ihre Session-API hat Setter für Modell, Thinking,
Plan- und Permission-Modus, aber keinen für das Arbeitsverzeichnis, und
`setAppState({workDir})` kommt im Bundle null mal vor. Dazu lesen über 16
Stellen `appState.workDir`, mehrere davon einmalig bei der Konstruktion
(@-Mentions, Input-History-Pfad, Plugin-Notifier). Sauber wäre nur ein Feature
über die Schichtgrenze, kein Patch. Ehrlich machbar wäre stattdessen „neue
Sitzung in einem anderen Verzeichnis" über `setAppState` plus
`createNewSession()` — das verwirft allerdings die Unterhaltung und ist damit
nicht das, was `/cd` in Claude Code tut.

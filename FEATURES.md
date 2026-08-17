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
12. Nach Update neu patchen     | lib/kimi-guard.sh + launchd               | done*
13. Systemdateien fernhalten    | lib/os-cruft.txt                          | done
14. Testsuite                   | test.sh, test.sh --full                   | done
15. Beispiel-Patch (Banner)     | patches/00-banner.js                      | done

16. Eingebaute Tools abschalten | built-in: [tools] disabled in config.toml | done
17. Vollbild-Renderer           | built-in: KIMI_CODE_TUI_FULL_SCREEN=1     | done
18. Transkript-Fenster kürzen   | built-in: KIMI_CODE_TUI_*, Menü „Launcher environment" | ungetestet
19. Shell-Hooks auf 20 Events   | built-in: [hooks] in config.toml          | ungeklaert
20. Modell je Subagent          | built-in: [secondary_model], config-menu 9 | ungetestet

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
50. Subagenten-Modellpool       | built-in: [secondary_model], config-menu 9 | ungetestet
```

Zeile 36 läuft im installierten Binary: `AGENTS_MD_PLAIN_NAMES = ["AGENTS.md",
"agents.md", "CLAUDE.md", "claude.md"]`, ad-hoc signiert, startet, meldet 0.36.0.

Die Zeilen 37 bis 45 sind bis an die Grenze geprüft, die ohne eine laufende
Sitzung erreichbar ist. Alle fünfzehn Patches wurden gemeinsam eingeschaltet,
in einer Sandbox auf eine Kopie der Baseline angewandt — **15 angewandt, kein
No-op** — und im erzeugten Binary Marker für Marker nachgewiesen: achtzehn
Stellen, alle vorhanden, Binary neu signiert, startet und meldet 0.36.0. Was
bleibt, ist die Wirkung im Betrieb: dass ein Rahmen gut aussieht, dass die
Verbrotation nicht flackert, dass der Router die Stufe trifft, die man erwartet
hätte. Das ist Anschauen, nicht Prüfen, und dafür braucht es dich.

Ein Mangel kam dabei heraus und ist behoben: `patch-settings.conf` schneidet
Leerzeichen am Wertende ab, also war `user_message_marker = > ` nicht
aufschreibbar — das Präfix klebte am Text. Der Patch hängt das Leerzeichen
jetzt selbst an, wie Kimis eigenes `"✨ "` es hat.

## Bewusst nicht gebaut

Vier Punkte aus der tweakcc-Liste sind geprüft und verworfen, statt halb
umgesetzt zu werden.

**Inline-`<system-reminder>` als Override.** Die datei-basierten Reminder
(`goal-*`, `permission-mode-*`, `compaction-*`, `SIDE_QUESTION_SYSTEM_REMINDER`)
liegen längst als `.md` unter `system-prompts/` und lassen sich bearbeiten;
ein leerer Rumpf unterdrückt sie, weil der Applier den leeren String schreibt.
Nicht erfasst sind zwei Blöcke, die inline in Template-Literalen stehen und
deshalb an `extract-prompts.py` vorbeilaufen — es nimmt nur benannte Literale
ab hundert Zeichen:

```
<system-reminder>\nThe same tool call has been repeated several times in a row. …
<system-reminder>\nWrite your final response now, without any further tool calls. …
```

Sie editierbar zu machen hieße, dem Extractor und dem Applier eine dritte
Anker-Klasse beizubringen (Literal statt Quellpfad oder Konstantenname), samt
Drift-Erkennung dafür. Das ist gebaut in etwa so groß wie der Theme-Editor —
für zwei Blöcke, die beide etwas Nützliches tun: der eine bremst
Werkzeug-Schleifen, der andere erzwingt eine Antwort statt eines weiteren
Aufrufs. Kimi hat insgesamt siebzehn `system-reminder`-Treffer gegen tweakccs
vierunddreißig kuratierte Einträge; hier ist schlicht weniger zu holen. Wenn es
doch gebraucht wird, ist die Verankerung am Renderer die richtige Bauart —
tweakcc macht das so, und `isSuppressed` ist dort nichts weiter als
`body.trim().length === 0`.

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

**12** — Der Reparaturweg ist jetzt einmal vollständig gelaufen, in einer
Sandbox auf einer Kopie der Baseline: patchen, das Binary so ersetzen wie ein
Auto-Update es tut, und prüfen, dass der Wächter es merkt und die Patches
zurückbringt. Er meldet `pristine — the patches are gone` mit rc=10, repariert,
und beide Marker stehen danach wieder im Binary, das startet. Die Gegenprobe
gehört dazu: bei einem Versionswechsel meldet er rc=11, rührt das Binary nicht
an und verweist an einen Menschen. `lib/test_guard_cycle.sh` fährt das wieder,
`./test.sh --full` ruft es auf.

Das `*` bleibt aus einem Grund: der launchd-Agent selbst wurde nie installiert.
Was geprüft ist, ist was er auslöst — nicht, dass er zur richtigen Sekunde
auslöst.

**16** — Live bestätigt am 2026-08-13: mit
`disabled = ["CronCreate","CronList","CronDelete"]` antwortet Kimi auf die
Frage nach diesen Werkzeugen mit `NO` und zählt **23 statt 26** Werkzeuge. Die
Sektion erreicht also den Katalog, den das Modell sieht. Cron und Goal zusammen
sind rund 4.900 Token pro Turn.

**17** — Live bestätigt: `KIMI_CODE_TUI_FULL_SCREEN=1 kimi` übernimmt den
Bildschirm vollständig (Alternate-Screen-Buffer), die Shell-Historie darüber
verschwindet für die Dauer der Sitzung.

**19** — **Implementiert, Wirkung ungeklärt.** Vier Verdachtsmomente sind
ausgeräumt: die Sektion heißt wirklich `hooks`, das Schema ist ein Array (also
ist `[[hooks]]` richtig), der Dienst ist **eifrig** registriert und nicht faul
— `activation = 0` heißt in `provideScopeServices` genau das —, und dass ihn
niemand injiziert, folgt daraus statt dagegen zu sprechen. Er abonniert im
Konstruktor, statt aufgerufen zu werden. Offen bleibt allein, ob der Weg einer
normalen TUI-Sitzung den Scope anlegt, in dem er registriert ist. Die
Herleitung steht in `FINDINGS.md`.

**20** — `/experiments` listet alle vier Flags mit Beschreibung, Quelle
(`default`) und Env-Namen und lässt sie umschalten. Dass ein zweites Modell
für Subagenten dann tatsächlich verwendet wird, ist damit noch nicht gezeigt —
dafür müsste ein Zweitmodell konfiguriert und ein Subagent beobachtet werden.

**18** — Die sechs `KIMI_CODE_TUI_*`-Variablen entscheiden, wie viel Historie
je Turn erneut gesendet wird. Das ist der einzige Hebel, der die **laufenden**
Kosten senkt statt der Startkosten — deshalb trotz `built-in` ein Menüeintrag.
Alle sechs stehen jetzt als Zeilen im Bildschirm „Launcher environment": enter
setzt einen Wert, ‹› gibt ihn an Kimi zurück. Was fehlt, ist die Messung, wie
viel ein niedrigerer Wert tatsächlich spart.

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

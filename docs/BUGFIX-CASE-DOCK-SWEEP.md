# Fallstudie: Dock-Placeholder-Bug — effiziente Fehleranalyse und Fix

Vollständiges Protokoll eines Bugfix-Zyklus nach dem Schema:
Analyse = Call / Ausgabe-Oneliner / Nutzung-Oneliner. Umsetzung = Call-Oneliner /
Zweck-Oneliner. Dient als Vorlage für einen generischen Bugfixing-Skill.

## Ausgangslage

Symptom (User-Report mit Screenshot): Swarm-Members erscheinen nach Dispatch
kurz im Dock, verschwinden nach 1–2 s, kommen als `agent-27 #1`-Placeholder
mit `0 tools · 0k · 0:00 · idle · [Failed]` zurück. Aktiv: 0.39.0,
`agent_background = immediate` (stopTurn am Dispatch).

## Phase 1 — Analyse

### Schritt 1: Das Swarm-Ergebnis lesen, bevor irgendetwas anderes

Call:
```
Read /Users/rob/.kimi-code/sessions/…/agents/main/tasks/swarm-l2bxi28q/output.log
```
Ausgabe: `failed: 2`, beide Members mit `state="started" outcome="failed"`, Grund 403 Usage-Limit.
Nutzung: Trennt sofort zwei Fehlerbilder — das `[Failed]` ist Quota (kein Patch-Bug),
das Verschwinden/Placeholder-Problem bleibt als eigentlicher Bug übrig.

**Prinzip: Erst die billigste Quelle lesen, die das Symptom falsifizieren kann.**

### Schritt 2: Event-Timeline der Main-Session um die Swarm-Läufe

Call:
```
Bash: python3 — wire.jsonl der Main-Session zeilenweise parsen, ab Zeile 3750
pro Zeile: index, Zeitstempel, agentId, Eventtyp, bei subagent/task/turn-Events
die Schlüsselfelder (subagentId, taskId+status, turnId, isError)
```
Ausgabe: `task.started (swarm)` → `tool.result` → 3 ms später `turn.ended` →
1,3 s später `task.terminated completed`; keine einzige Member-Event-Zeile sichtbar.
Nutzung: Belegt, dass stopTurn wirkt und der Turn-Sweep 3 ms nach der
Task-Registrierung läuft — der Kandidaten-Mechanismus (handleTurnEnd) ist damit
zeitlich eingeordnet.

### Schritt 3: Falsifizieren, ob die Wire Child-Events überhaupt enthält

Call:
```
Bash: python3 — über dieselbe wire.jsonl: zähle Events mit 'subagent' im Typ,
sammle alle agentId != 'main'
```
Ausgabe: `total subagent lifecycle events in main wire: 0`, `non-main agentIds: []`.
Nutzung: Verhindert eine Fehlinterpretation von Schritt 2 — die Main-Wire enthält
aus Prinzip keine Child-Events (Kontext-Isolation), sie sagt also nichts über den
TUI-Event-Bus aus; die Quelle ist für die Kernfrage erschöpft.

**Prinzip: Jede Quelle einmal auf ihre Reichweite prüfen, bevor man aus ihrem
Schweigen schließt.**

### Schritt 4: Die Member-Wires lesen (die Quelle wechseln, nicht aufgeben)

Call:
```
Bash: python3 — agents/agent-27..30/wire.jsonl: Zeilenzahl, Eventtyp-Histogramm,
erster/letzter Zeitstempel
```
Ausgabe: alle vier identisch, 13 Zeilen — metadata, binding, profile, permission,
turn.prompt, llm.tools_snapshot — danach Ende, kein `usage.record`, kein Tool-Call.
Nutzung: Die Members wurden real gespawnd und starben beim ersten LLM-Request
(403); sie emittierten nie Tool-Events — also stammen die Dock-Placeholder aus
Lifecycle-Events, nicht aus Tool-Events.

### Schritt 5: Zeitstempel-Vergleich Member-Spawn vs. Main-Turn-Ende

Call:
```
Bash: python3 — erste Zeitstempel aus agent-27..30/wire.jsonl gegen die beiden
turn.ended-/task.terminated-Zeiten der Main-Wire (als Konstanten aus Schritt 2)
```
Ausgabe: Member-Wires beginnen −271 ms bis −110 ms **vor** `turn.ended`.
Nutzung: Die Spawns liefen vor dem Sweep — der naive Guard (Record existiert und
hat parentToolCallId) hätte greifen müssen, **wenn** das spawned-Event beim
Handler schon angekommen wäre. Der Widerspruch zeigt: das Problem ist
Event-Timing, nicht Record-Logik.

### Schritt 6: Turn-Ende-Pfad im Bundle lesen

Call:
```
Grep .work/bundle.js für "handleTurnEnd" → Read Zeilen 524459–524484
```
Ausgabe: `handleTurnEnd` ruft bei **jedem** Turn-Ende
`dropForegroundOnlyActivityRecords()` (plus `markActiveAgentSwarmsCancelled` nur
bei `reason === "cancelled"`).
Nutzung: Identifiziert den Sweep als den Mechanismus, der bei normalem Turn-Ende
(stopTurn) genauso läuft wie bei Abbruch.

### Schritt 7: Die Prune-Logik im Bundle lesen

Call:
```
Read .work/bundle.js Zeilen 523950–523963 (pruneForegroundOnlyRecord +
dropForegroundOnlyActivityRecords)
```
Ausgabe: Drop, wenn weder `backgroundAgentMetadata` noch ein Background-Task mit
`info.agentId === subagentId` matcht; Sweep iteriert alle Store-IDs.
Nutzung: Zeigt, warum Swarm-Members durchs Raster fallen — der Swarm-Task trägt
die Member-IDs nicht einzeln (`KmodsSwarmTask.agentId` ist eine, nicht alle).

### Schritt 8: Spawn-Pfad im Bundle lesen (wo feuert das Event?)

Call:
```
Read .work/bundle.js Zeilen 283547–283572 (SessionSwarmService.spawnAttempt)
```
Ausgabe: `await this.subagents.spawn(…)` **vor** `emitAgentRunSpawned(…)` — das
Event feuert erst nach Binding, Permissions und Turn-Setup des Members.
Nutzung: Liefert die Schließung der Kette: Sweep (3 ms nach task.started) läuft,
bevor das erste spawned-Event existiert — es gibt zum Sweep-Zeitpunkt keinen
Record zu schützen; später ankommende Terminal-Events (`subagent.failed` bei 403)
erzeugen via `recordFor` die Placeholder, die der User sieht.

### Schritt 9: Gegenprobe — wird das Lifecycle-Event je nach Turn-Ende verworfen?

Calls:
```
Grep "handleLifecycleEvent|routeChildAgentEvent" → Read 524320–524415 (handleEvent-Switch)
Read 523870–523885 (handleSubagentSpawned)
```
Ausgabe: Lifecycle-Events laufen über den session-weiten `handleEvent`-Switch an
`handleLifecycleEvent` → `rememberSubagent`; kein Turn-Gate nirgends.
Nutzung: Schließt "Events werden nach Turn-Ende verworfen" als Ursache aus — die
Records entstehen korrekt, nur zu spät; der Fix muss am Sweep ansetzen, nicht am
Event-Weg.

## Analyse-Ergebnis (die komplette Kette)

```
1. AgentSwarm-Call → swarmService.run() startet async
2. Member-Spawn awaitet Binding/Permissions/Turn-Setup (~100–270 ms)
3. stopTurn → turn.ended 3 ms nach task.started
4. handleTurnEnd → Sweep: keine Member-Records vorhanden → läuft leer
5. spawned-Events kommen nach Turn-Ende → Records entstehen (zu spät für
   Nummerierung/Kohorte des ursprünglichen Batches)
6. Members sterben (403) → subagent.failed → recordFor-Placeholder (agent-N)
```

## Phase 2 — Umsetzung

### Fix-Entscheidung vor dem ersten Edit

Der parentToolCallId-Guard (bereits gebaut) kann das Timing nicht retten — er
prüft Records, die zum Sweep-Zeitpunkt nicht existieren. Stattdessen eine Ebene
höher: **der Sweep selbst lässt `running`-Records stehen.** Begründung im Patch:
Der Sweep existiert für mit dem Turn abgebrochene Foreground-Agents ohne
Terminal-Event; mit `always`/`immediate` gibt es keine Foreground-Subagents
mehr, und Swarm-Members terminieren immer über das Batch.

### Umsetzungsschritte

1. `Edit patches/82-agent-dock.js` — neuer Splice `the turn-end record sweep`:
   `dropForegroundOnlyActivityRecords` überspringt Records mit
   `status === "running"`. — Zweck: Ursache entfernen statt Symptom abfedern.
2. `Edit patches/82-agent-dock.js` — SWARM_GUARD-Kommentar um die
   Timing-Begründung ergänzt, Guard bleibt als zweite Verteidigungslinie für
   direkte Prune-Aufrufe. — Zweck: Defense in depth ohne neuen Code-Pfad.
3. `Edit lib/test_agent_dock.mjs` — Mock-Store um `agentIds()` ergänzt. —
   Zweck: gepatchter Sweep ruft sie; ohne sie wäre der Mock unvollständig.
4. `Edit lib/test_agent_dock.mjs` — Mock-Handler um
   `dropForegroundOnlyActivityRecords` (Originalform als Anker) ergänzt. —
   Zweck: der Splice braucht seinen Anker im Test-Bundle.
5. `Edit lib/test_agent_dock.mjs` — drei neue Checks: Sweep behält running /
   Sweep prunt finished je Modus / direkter Prune mit und ohne Task-Claim. —
   Zweck: den Fix in beide Richtungen belegen (behält, was laufen soll; räumt,
   was weg soll).
6. Testlauf → `SyntaxError: Identifier 'a4' has already been declared`. —
   Namenskonflikt im Test-Scope.
7. `Edit lib/test_agent_dock.mjs` — Test-IDs auf `sw1`/`sw2` umbenannt. —
   Zweck: Kollision auflösen.
8. Testlauf → `ReferenceError: MODE is not defined`. — Die Suite nennt den
   Parameter `mode`, nicht `MODE`.
9. `Grep "suite\|function" lib/test_agent_dock.mjs` + Read Funktionskopf. —
   Zweck: den echten Parameternamen aus dem Test-Code holen statt raten.
10. `Edit` — `MODE` → `mode`. — Zweck: an die Suite-Konvention anpassen.
11. `Bash node lib/test_agent_dock.mjs` — all checks passed (beide Modi). —
    Zweck: Fix-Behauptung verifizieren, bevor irgendetwas anderes läuft.
12. `Bash ./test.sh && node lib/test_patches.mjs --bundle` — 30 + 112 grün. —
    Zweck: Querschnitt (Patch-Vertrag, Anker, Idempotenz) sicherstellen.
13. `Bash ./kimi-patch.sh` — 19 applied, 0 failed, `verify: all 22 patch(es)
    present in the installed bundle`. — Zweck: installieren und per
    Re-Apply-Nachweis bestätigen, dass der Fix wirklich im Binary ist.
14. `Bash git commit` — `b2604f4`. — Zweck: analysierte Kette im Commit-Text
    festhalten, solange sie frisch ist.

## Übertragbare Prinzipien (Skill-Kerne)

1. **Billigste Falsifikation zuerst**: Die Quota-403 im Task-Log trennte
   Symptom von Bug, bevor irgendein Bundle gelesen wurde.
2. **Quellen-Reichweite prüfen**: Die Main-Wire schweigt zu Child-Events aus
   Prinzip — Schweigen als Beweis zu lesen wäre der erste Irrweg gewesen.
3. **Zeitachse schlagen**: `task.started → turn.ended = 3 ms` gegen
   `spawn = −217 ms` reichte, um "Event-Timing statt Record-Logik" zu belegen.
4. **Die Kette komplett schreiben, bevor gepatcht wird**: Jede Stufe (async
   Spawn → spätes Event → Placeholder) hat einen Beleg; der Fix adressiert die
   Stufe, die tatsächlich bricht (Sweep), nicht die, die zuerst auffiel
   (Guard).
5. **Fix eine Ebene über dem Symptom**: Der Guard reparierte den Record, der
   Sweep erzeugte das Problem.
6. **Jeder Fix kriegt seinen Test in beide Richtungen**: behält, was laufen
   soll; räumt, was weg soll.
7. **Test-Fehler sind Befunde, kein Rauschen**: Der doppelte Identifier und
   `MODE` vs. `mode` zeigten beide Stellen, an denen der neue Code von der
   Suite-Konvention abwich.
8. **Installations-Nachweis schlägt Selbstauskunft**: `--verify` wendet jeden
   Patch erneut an; was sauber durchliefe, war nie drin.

---

## Fortsetzung: Verifikationsrunde nach Fix-Einbau (gleiche Session, später)

Nach dem Einbau des Sweep-Fixes und zwei weiteren 403-gestorbenen Test-Swarms
die Frage: hätte der Guard (Fix v1) greifen müssen — und greift der Sweep-Fix
(Fix v2) an der richtigen Stelle? Diese Runde prüft das ohne einen einzigen
Modell-Call.

### Analyse

1. Call:
   ```
   Bash: Backup-Snapshot — git archive HEAD + gitignored Lokaldaten
   (FINDINGS*, state.json, Settings) + beide Binaries (baseline, patched)
   nach ~/.kimi-code-mods-backup-<stamp>/
   ```
   Ausgabe: 351 MB, 22 Patches, beide Binaries, alle lokalen Notizen.
   Nutzung: Rückbau-Option sichern, bevor weiter analysiert wird — der Vorschlag
   "alte 0.38er-Version wiederherstellen" wurde damit obsolet, ohne etwas zu
   riskieren.

2. Call:
   ```
   Bash: python3 — Member-Wires agent-27..30 zeilenweise: pro Zeile Typ und
   Zeitstempel, relativ zu tool.call und turn.ended der Main-Wire (Konstanten
   aus der ersten Runde)
   ```
   Ausgabe: Setup-Kette (binding → profile → permission → turn.prompt) endet
   −94 bis −271 ms **vor** `turn.ended`; `llm.request` startet ebenfalls davor;
   die Members sterben +830 bis +926 ms **danach** (403).
   Nutzung: Widerlegt die Arbeitsannahme aus der ersten Runde ("spawned-Events
   kommen erst nach dem Sweep") — das Spawn awaitet zwar, ist aber längst fertig,
   bevor der Turn endet. Der Sweep hätte Records vorgefunden, und der v1-Guard
   hätte greifen müssen. Die Placeholder kommen also nicht (nur) aus dem Sweep.

3. Call:
   ```
   Read .work/bundle.js:525050 (handleBackgroundTaskEvent)
   ```
   Ausgabe: `backgroundTasks.set(info.taskId, info)` — der Handler schreibt das
   `info` aus `background.task.started` ungefiltert in dieselbe Map, die der
   Guard liest.
   Nutzung: Belegt die Task-Seite des Guards: `parentToolCallId` aus
   `KmodsSwarmTask.toInfo` landet in der Map — sobald das Event läuft.

4. Call:
   ```
   Read .work/bundle.js:122872 (registerTask)
   ```
   Ausgabe: `detached: true` → `this.tasks.set(...)`, `runTaskLifecycle(entry)`,
   dann synchron `emitTaskStarted(this.toInfo(entry))`.
   Nutzung: Das Task-Started-Event feuert synchron bei der Registrierung —
   7 ms nach dem Tool-Call, lange vor dem Sweep. Map und Record lagen beide vor;
   der Guard hatte alles, was er braucht — und griff trotzdem nicht.

5. Call:
   ```
   Read .work/bundle.js:282951 (emitAgentRunSpawned)
   ```
   Ausgabe: dispatcht `SubagentSpawned` über `IEventDispatcher` des Requesters,
   mit echtem `subagentName: meta.profileName`, `parentToolCallId`, `model`,
   `thinkingEffort`; dazu Telemetrie über denselben Accessor.
   Nutzung: Belegt, dass das Event die richtigen Felder trägt — wenn es ankäme,
   gäbe es keine Placeholder-Namen. Der Fehler sitzt also im Transport, nicht im
   Inhalt.

6. Call:
   ```
   Read .work/bundle.js:524275 (session.onEvent-Subscription) und
   524320 (handleEvent-Switch)
   ```
   Ausgabe: Der SessionEventHandler abonniert `session.onEvent` einmal pro
   Session-Bindung; der Switch routet `subagent.spawned` u.a. an
   `handleLifecycleEvent` — ohne Turn-Prüfung.
   Nutzung: Kein Turn-Filter auf dieser Ebene. Die Suche verengt sich auf die
   Brücke Dispatcher → Session-Stream.

7. Call:
   ```
   Grep "\.observable" .work/bundle.js → Read 258020–258032
   ```
   Ausgabe: die Dispatch-Pipeline persistiert `durable` Events in die Wire und
   publiziert `observable` Events auf den EventBus — `if (cls.observable &&
   !this.disposed)`. `SubagentSpawned` ist `observable`, nicht `durable`.
   Nutzung: Erklärt das Wire-Schweigen aus Runde 1 vollständig (kein Bug, keine
   Isolation — schlicht nicht durable), und benennt die einzige Gate-Bedingung
   der Brücke: `disposed`. Der Main-Agent wird zwischen Turns nicht disposed —
   statisch bleibt damit kein Filter übrig, der die Events verschluckt.

### Ergebnis der Fortsetzung

Die Statik widerspricht dem beobachteten Symptom: Records, Task-Map und
Event-Felder lagen alle rechtzeitig vor, und kein Turn-Gate existiert. Damit
sind zwei Lesarten übrig:

- Das Verschwinden geschah nicht im Sweep (`turn.ended`), sondern im
  **Notification-Turn** 1–2 s später (`task.terminated` → neuer Turn →
  `resetRuntimeState`) — das Timing des User-Reports ("ca. 1–2 Sekunden")
  passt dazu besser als zum Sweep (0,3 s).
- Oder zwischen Bus-Publish und Store-Eintrag sitzt eine Schicht, die nur zur
  Laufzeit sichtbar wird.

Beide sind mit Statik nicht mehr unterscheidbar — die nächste Information muss
aus der Beobachtung kommen: verschwinden die Zeilen sofort oder erst nach
1–2 s? Genau dafür war die Unterscheidung dieser Runde da.

### Zusatz-Prinzipien

9. **Ein Widerspruch zwischen Statik und Symptom ist ein Fund, kein
   Misserfolg**: Er grenzt die verbleibenden Ursachen auf die ein, die man
   nicht lesen kann — und sagt einem, welche Beobachtung als Nächstes fehlt.
10. **Zeitangaben im User-Report sind Testdaten**: "1–2 Sekunden" reichte, um
    den Sweep (0,3 s) vom Notification-Turn (1,3 s) zu trennen — zwei
    Kandidaten, eine Zahl, eine Frage an den User statt ein weiterer Bundle-
    Tauchgang.

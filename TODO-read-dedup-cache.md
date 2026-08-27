# TODO: Read-Dedup-Cache — byte-genauer Datei-Tracker als Gate

Stand 2026-08-27, Kimi Code 0.38.0. Ziel: verhindern, dass unveränderte
Dateien mehrfach in den Kontext geladen werden, und dabei das
Zeilennummern-Kaskadenproblem (rekursives Lesen von `tool-results/*.txt`)
eliminieren.

## Befund

Kimi Code speichert große Read-Outputs als `tool-results/Read-tool_XXX.txt`.
Nach Context-Compaction liest das Modell diese Dateien statt der
Originalquelle. Jeder solche Read fügt eine neue Zeilennummern-Spalte hinzu,
weil der gespeicherte Inhalt die vorherigen Nummern bereits als Text enthält:

```
Layer 0: Original .md          → plain content
Layer 1: Read of .md           → 226\tcontent
Layer 2: Read of layer-1 .txt  → 97\t226\tcontent
Layer 3: Read of layer-2 .txt  → 97\t193\t247\t272\t272\tcontent
```

Belegt in Session `wd_clui_f6252508d68e`, Kette über 4 Tool-Calls
(`tool_C5T0cHVAdJwCzBzgnxyya6qV` → `tool_YiHdlk1lHVhy5TOeeV3ZU2AE` →
`tool_gsKXA6yvqvhVRbMkYqCEiUBZ` → `tool_KhVjzeEJo46rpJEYcf9KD4SB`).

## Konzept: Content-Addressed Read-Gate

Ein zentraler Tracker, der jede gelesene Datei byte-genau per SHA-256
identifiziert und vor jedem Read als Gate entscheidet, ob der volle Inhalt
gesendet werden muss.

### Ablauf

```
Read(path) →
  1. stat(path) → mtime + size
  2. Hash für (path, mtime, size) bekannt? → Cache-Hit, Referenz zurückgeben
  3. Sonst: Datei lesen, SHA-256 des tatsächlich gelesenen Inhalts berechnen
  4. Hash schon im Store? → Inhalt bekannt, nur Referenz nötig
  5. Hash neu? → Inhalt im Store ablegen, voller Read
```

### Was das löst

- **Zeilennummern-Kaskade**: `tool-results/*.txt` hat einen anderen Hash als
  die Originaldatei und wird als eigene Datei erkannt. Der Gate kann warnen
  oder umleiten statt blind nochmal zu nummerieren.
- **Cross-Session-Dedup**: Zwei Sessions, die dieselbe Datei lesen, teilen
  sich den Inhalt. Bei Monorepos mit vielen Agents, die dieselben
  Config-Dateien lesen, massiver Gewinn.
- **Byte-Genauigkeit**: Kein Raten über Änderungen. Entweder der Hash stimmt
  oder nicht. Kein TOCTOU-Problem auf Semantik-Ebene, weil der Hash vom
  tatsächlich gelesenen Inhalt berechnet wird, nie vom Mtime abgeleitet.

### Offene Probleme

- **Mtime-Race**: Zwischen `stat()` und `read()` kann sich die Datei ändern.
  Hash immer vom gelesenen Inhalt berechnen, Mtime nur als Hint.
- **Partial Reads**: Zeilen 500-600 haben einen anderen Hash als die ganze
  Datei. Entweder immer die ganze Datei hashen (teuer bei großen Dateien)
  oder Range-Awareness einbauen (komplex).
- **Store-Wachstum**: Jede je gelesene Version bleibt. LRU mit Größenlimit
  nötig, aber dann ist ein Hash nicht mehr garantiert auflösbar.
- **Referenz-Problem im Kontext**: "Nutze Referenz #abc123" nützt nichts,
  wenn der Inhalt aus dem Kontext compacted wurde. Retrieve-Mechanismus
  kostet selbst Tokens.

### Pragmatische 80/20-Variante

Session-lokaler Cache statt globalem CAS:

- Pro Session: Map von `path → (sha256, letzter vollständiger Inhalt)`
- Bei Read: Hash der aktuellen Datei berechnen, vergleichen
- Match: "Datei unverändert seit Turn N" — Modell entscheidet selbst,
  ob es den Inhalt noch hat oder neu braucht
- Kein Match: normaler Read, Hash aktualisieren

Fängt den häufigsten Fall ab (Agent liest dieselbe Datei mehrfach pro
Session) ohne die Komplexität eines globalen Stores. Verhindert nebenbei
das `tool-results`-Problem, weil der Hash der `.txt` nie mit dem der `.md`
übereinstimmt.

## Aufgaben

- [ ] Untersuchen, wo im Bundle der Read-Tool-Output zusammengebaut wird
      (`renderLine` in `agent-core-v2`), um den besten Eingriffspunkt für
      einen Hash-Check zu finden.
- [ ] Prüfen, ob der Read-Tool vor dem Lesen einer Datei erkennen kann, dass
      es sich um eine `tool-results/Read-*.txt` handelt, und stattdessen die
      Originaldatei vorschlagen.
- [ ] Prototyp: session-lokaler Hash-Cache als Patch, der bei unveränderten
      Dateien eine Kurzmeldung statt des vollen Inhalts ausgibt.
- [ ] Evaluieren, ob ein globaler Store (über Sessions hinweg) den
      zusaetzlichen Implementierungsaufwand rechtfertigt.

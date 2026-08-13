# Eigene Agent-Profile

Belegt am extrahierten Bundle (`.work/bundle.js`), Fundorte sind die
`//#region`-Modulpfade.

## Ja, eigene Profile sind vorgesehen

Das Validierungsschema steht in `packages/agent-core/src/profile/` und ist die
verbindliche Antwort darauf, welche Felder ein Profil tragen darf:

```js
RawAgentProfileSchema = object({
  extends:              string().optional(),
  name:                 string().min(1),          // einziges Pflichtfeld
  description:          string().optional(),
  systemPromptPath:     string().optional(),
  systemPromptTemplate: string().optional(),
  promptVars:           record(string(), string()).optional(),
  tools:                array(string()).optional(),
  whenToUse:            string().optional(),
  subagents:            record(string(), RawSubagentProfileSchema).optional(),
  modelPreference:      _enum(["primary", "secondary"]).optional()
})
```

`modelPreference` ist die Verbindung zum Experimentalflag `secondary-model`:
Ein Profil kann verlangen, auf dem Zweitmodell zu laufen.

`subagents` ist bemerkenswert — ein Profil kann eigene Subagenten-Profile
mitbringen, also eine ganze Hierarchie beschreiben.

## Wo Kimi sucht

`extraAgentDirs` aus der Konfiguration wird an den Loader durchgereicht:

```js
extraDirs: options.agents?.extraDirs ?? options.config?.extraAgentDirs,
explicitFiles: options.agents?.explicitFiles,
pluginRoots: options.agents?.pluginRoots,
```

Es gibt also drei Wege, ein Profil beizusteuern: über `extra_agent_dirs` in
`config.toml`, über explizit benannte Dateien, und über ein Plugin.

Die Standardwurzeln ermittelt `userAgentRoots()` in
`agent-core-v2/src/workspace/workspaceAgentProfileLoader/internal/agentRoots.ts`,
mit einem Gegenstück in der v1-Engine — der Kommentar dort mahnt ausdrücklich,
beide synchron zu halten. Gesucht wird in `~/.kimi-code/agents` sowie im
Projekt unter `.kimi-code/agents`.

## Format

Die eingebauten Profile sind **YAML** und liegen als
`packages/agent-core/src/profile/default/<name>.yaml` im Bundle. Beispiel
`coder`, wörtlich aus dem Bundle:

```yaml
extends: agent
name: coder
promptVars:
  roleAdditional: |
    You are now running as a subagent. …
```

`extends: agent` zeigt die Vererbung: Ein eigenes Profil kann auf einem
eingebauten aufsetzen und nur das Abweichende beschreiben.

Eine explizite Endungsliste (`AGENT_FILE_EXTENSIONS` o. ä.) war nicht zu
finden; die eingebauten Dateien tragen `.yaml`. Für ein eigenes Profil ist
`.yaml` daher die belegte Wahl, `.yml` unbestätigt.

## Was daraus folgt

Die fünf eingebauten Profile — `agent`, `coder`, `explore`, `init`, `plan` —
sind keine Sonderfälle, sondern Instanzen desselben Formats. Ein eigenes
Profil, das etwa auf `explore` aufsetzt, ein enges `tools`-Feld bekommt und
`modelPreference: secondary` setzt, wäre nach Aktenlage möglich, ohne das
Binary anzufassen.

**Nicht verifiziert:** Ob ein selbst abgelegtes Profil wirklich geladen und als
Slash-Command angeboten wird, wurde nicht zur Laufzeit geprüft. Das ist ein
Test von wenigen Minuten: eine `.yaml` mit `extends: agent` und eigenem `name`
nach `~/.kimi-code/agents/` legen, Kimi starten, `/` tippen.

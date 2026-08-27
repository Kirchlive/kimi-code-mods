# TODO: Hintergrund-Agenten zum Normalfall machen

Stand 2026-08-25, Kimi Code 0.38.0. Ziel: der Hauptagent soll weiterarbeiten,
während ein Subagent läuft — so wie es Claude Code tut.

## Befund

Die Fähigkeit ist bereits im Binary. Es fehlt kein Patch, es fehlt eine
Voreinstellung.

`Agent(run_in_background=true)` startet den Subagenten abgekoppelt vom
laufenden Turn und liefert sofort zurück. Das Ergebnis kommt später als
`<notification>` in einem eigenen Turn. Dazu gehören die Werkzeuge
`TaskList`, `TaskOutput`, `TaskStop`, `WaitFor` und das `/tasks`-Panel.

Belegt zur Laufzeit, headless in einem frischen Verzeichnis:

```
$ kimi --output-format stream-json -p '… Agent(subagent_type="explore", run_in_background=true) …'

Agent{"subagent_type":"explore","run_in_background":true,…}
  -> task_id: agent-0e0nff5d
     status: running
     automatic_notification: true
```

Der Aufruf kehrte sofort zurück, der Hauptagent arbeitete im selben Turn
weiter.

Fundorte im extrahierten Bundle (`.work/bundle.js`):

| Was | Wo |
| --- | --- |
| Freischaltbedingung | `agent-core-v2/src/agent/tools/agent/agentTool.ts:288675` |
| Werkzeugliste `agent` und `coder` | `agent-core-v2/src/session/agentLifecycle/profile/profiles.ts` |
| Rückmeldung als XML | `agent-core-v2/src/agent/task/notificationXml.ts` |
| `wait_for`-Flag, Vorgabe an | `agent-core-v2/src/agent/tools/task/task-wait/flag.ts` |

Die Bedingung lautet: `TaskList`, `TaskOutput` und `TaskStop` müssen aktiv
sein. Sie stehen in `AGENT_TOOLS` und `CODER_TOOLS`, nicht in
`EXPLORE_TOOLS` — ein Explore-Subagent kann also selbst keine
Hintergrundagenten starten. `~/.kimi-code/config.toml` schaltet nur die
`Cron*`-Werkzeuge ab und steht dem nicht im Weg.

Warum es sich trotzdem sequenziell anfühlt: der eingebaute Prompt rät ab.

> Default to a foreground subagent (omit `run_in_background`) … Reach for
> `run_in_background=true` only when you have other work to do while it runs.

Das Modell wählt daraufhin fast immer den Vordergrund.

## Aufgaben

- [ ] `system-prompts/packages/agent-core-v2/src/agent/tools/agent/agent-background-enabled.plain.md`
      umschreiben: Hintergrund als Regel, Vordergrund nur, wenn der nächste
      Schritt das Ergebnis braucht. Über die bestehende Override-Mechanik
      (`kimi-patch.sh` → `lib/apply-prompt-overrides.py`), kein neues
      Patch-Modul.
- [ ] Gegenstück in `system-prompts/packages/agent-core/…/agent-background-enabled.plain.md`
      gleich behandeln, damit die v1-Engine nicht abweicht.
- [ ] Ankertreue prüfen: `kimi-patch.sh --status` muss den Override als
      angewandt melden, ohne `anchor missing`.
- [ ] Als Schalter in `patch-settings.conf` aufnehmen, falls der neue
      Standard nicht immer erwünscht ist. Name offen, etwa
      `background_agents = default | prefer`.

## Offen, noch nicht belegt

- [ ] Nimmt die interaktive TUI Eingaben an, während ein Hintergrundagent
      läuft? Der Test lief headless. Die Bausteine sind da
      (`src/tui/components/messages/background-agent-status.ts`,
      `src/tui/utils/background-task-status.ts`), aber ein gerenderter
      Bildschirm fehlt als Beweis.
- [ ] Wie verhält sich `/tasks` bei mehreren gleichzeitigen Agenten?
- [ ] Kommt die `<notification>` auch dann an, wenn der Turn zwischenzeitlich
      auf eine Nutzereingabe wartet, oder erst beim nächsten Prompt?

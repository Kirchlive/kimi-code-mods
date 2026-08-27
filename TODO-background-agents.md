# TODO: Hintergrund-Agenten zum Normalfall machen — ERLEDIGT

Stand 2026-08-27, Kimi Code 0.39.0. Umgesetzt und in Betrieb; die Details
stehen in `FINDINGS-agent-dock.md`. Diese Datei bleibt als Vorgeschichte.

## Ergebnis gegenüber der ursprünglichen Aufgabenliste

- ~~Prompt-Override umschreiben~~ — **überholt.** Der erste Ansatz drehte den
  Ratgebertext um ("Default to background"), aber das Modell hielt sich nur
  unzuverlässig daran. Die endgültige Lösung ist technisch statt
  textuell: `agent_background = immediate` setzt `stopTurn: true` auf das
  Tool-Result — der Turn endet am Dispatch, ohne dass das Modell eine
  Wahl hat. Die Prompt-Overrides wurden wieder zurückgenommen.
- ~~Schalter in `patch-settings.conf`~~ — umgesetzt als
  `agent_background = default | always | immediate` (Patches 86+87).

## Offene Fragen von damals, jetzt belegt

- **TUI-Eingabe während ein Hintergrundagent läuft: ja.** Mehrfach in
  interaktiven Sessions beobachtet; der Composer bleibt bedienbar.
- **`/tasks` mit mehreren Agenten: funktioniert**; der Dock (Patch 82) zeigt
  sie zusätzlich stehend unter dem Composer.
- **`<notification>` bei wartendem Turn: kommt an.** Die Benachrichtigung
  eines Hintergrund-Swarms traf ein, während die Session idle auf Eingabe
  wartete, und löste einen eigenen Turn aus.

<!--
source: ../../packages/agent-core-v2/src/features/tower/tools/mission/mission.md
module: mission_default
variant: plain
chars: 345
originSha256: 3215ca37e593d8b9
trailingNewlines: 1
bundleOffset: 12766461
-->
Read or update a tower mission.

With only an id, returns the mission view (status, tasks, blockers, notes). With patch fields, applies them: workers may only update the mission they own — the store rejects anything else. Use task_done to tick checklist items, note to log decisions, blocker when stuck (the tower watches for blocked missions).

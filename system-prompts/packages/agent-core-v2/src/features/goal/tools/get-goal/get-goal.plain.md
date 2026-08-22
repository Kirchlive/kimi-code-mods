<!--
source: ../../packages/agent-core-v2/src/features/goal/tools/get-goal/get-goal.md
module: get_goal_default
variant: plain
chars: 375
originSha256: da22ffa25c95004b
trailingNewlines: 1
bundleOffset: 12611685
-->
Read the current goal: its objective, completion criterion, status, and budgets (turns, tokens,
time, and how much of each remains). When the goal has stopped, it also reports the terminal reason.

Use `GetGoal` before deciding whether to continue working, report completion, report a blocker,
or respect a pause. It returns `{ "goal": null }` when there is no current goal.

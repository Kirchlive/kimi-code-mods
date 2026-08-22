<!--
source: ../../packages/agent-core-v2/src/features/tower/tools/teardown/teardown.md
module: teardown_default
variant: plain
chars: 314
originSha256: 1ed406dedf0195ab
trailingNewlines: 1
bundleOffset: 12797684
-->
Tear down the tower workspace after all missions are merged (or abandoned).

Removes the mission worktrees — worktrees with uncommitted changes are kept and listed unless force is set. Exits tower mode. The .tower/comms/ directory (state, inbox, findings, reviews, activity log) is always kept as the audit trail.

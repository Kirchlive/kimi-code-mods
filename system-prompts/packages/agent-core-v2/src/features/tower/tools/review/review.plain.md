<!--
source: ../../packages/agent-core-v2/src/features/tower/tools/review/review.md
module: review_default
variant: plain
chars: 342
originSha256: 6c5e868fcede2d75
trailingNewlines: 1
bundleOffset: 12771916
-->
Submit a review verdict for a branch you were assigned to review (via TowerSpawn review_target).

The review is stamped with the current branch tip — if the branch moves afterwards, the tower must ask for a re-review before merging. Only reviewers assigned to the target (or the tower) may submit; the round number is assigned automatically.

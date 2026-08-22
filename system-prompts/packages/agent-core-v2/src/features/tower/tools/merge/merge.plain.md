<!--
source: ../../packages/agent-core-v2/src/features/tower/tools/merge/merge.md
module: merge_default
variant: plain
chars: 629
originSha256: f650c0263c0efa23
trailingNewlines: 1
bundleOffset: 12763844
-->
Merge a tower mission branch into the base branch (--no-ff).

Hard gate, enforced by the store — the merge is refused unless: the branch's latest review is "clean" and was written against the current branch tip, all dependency missions are already merged, and every changed file falls inside the mission's declared scope. On refusal, the error message tells you exactly what to do next (assign a reviewer, wait for fixes, re-review a moved tip, merge deps first, widen the scope or revert the extra changes). After a merge, branches reported as conflicting must rebase onto the new base and be re-reviewed before they can merge.

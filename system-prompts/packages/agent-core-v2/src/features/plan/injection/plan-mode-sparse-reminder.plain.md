<!--
source: ../../packages/agent-core-v2/src/features/plan/injection/plan-mode-sparse-reminder.md
module: plan_mode_sparse_reminder_default
variant: plain
chars: 604
originSha256: d3e3187bcc43d351
trailingNewlines: 1
bundleOffset: 12445674
-->
Plan mode still active (see full instructions earlier). Prefer read-only tools except the current plan file. Use Write or Edit to modify the plan file. If it does not exist yet, create it with Write first. Use Bash only when needed; Bash follows the normal permission mode and rules. Use AskUserQuestion to clarify user preferences when it helps you write a better plan. If the plan has multiple approaches, pass options to ExitPlanMode so the user can choose. End turns with AskUserQuestion (for clarifications) or ExitPlanMode (for approval). Never ask about plan approval via text or AskUserQuestion.

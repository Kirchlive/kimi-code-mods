<!--
source: ../../packages/agent-core-v2/src/agent/permissionMode/injection/permission-mode-auto-enter-reminder.md
module: permission_mode_auto_enter_reminder_default
variant: plain
chars: 516
originSha256: 0975f1c992338bdc
trailingNewlines: 1
bundleOffset: 13458378
-->
Auto permission mode is active. Tool approvals will be handled automatically while this mode remains enabled.
  - Continue normally without pausing for approval prompts.
  - Do NOT call AskUserQuestion while auto mode is active. Make a reasonable decision and continue without asking the user.
  - ExitPlanMode is also approved automatically, without the user reviewing the plan. An auto-approved plan is NOT a signal from the user to start executing — follow the user's original instructions on whether to proceed.

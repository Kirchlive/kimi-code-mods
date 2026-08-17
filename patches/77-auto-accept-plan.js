// Accept a finished plan without the approval prompt.
//
// When the model leaves plan mode, Kimi stops and asks. The review lives in
// `agent-core-v2/src/features/plan/exitPlanModeReview.ts`:
//
//   async requestApproval(context) {
//     const display = context.execution.display;
//     if (display?.kind !== "plan_review") return void 0;
//     if (display.plan.trim().length === 0) return void 0;
//     this.trackPlanTelemetry("plan_submitted", { … });
//     return this.toolApproval.requestToolApproval(context, {
//       kind: "ask",
//       reason: { has_options: display.options !== void 0 },
//       resolveApproval: (result) => this.approvalResult(result, display)
//     }, "exit-plan-mode-review-ask");
//   }
//
// The patch does not build its own approval. It calls Kimi's own
// `approvalResult` with the decision already made, which is what makes this
// safe to do at all: leaving plan mode, the telemetry event, the "Approved
// Plan" output the model receives, and the saved-plan path all keep running
// through the code that already handles them. An approval assembled by hand
// here would have to reproduce every one of those, and would fall behind the
// first time Kimi changes any of them.
//
// The two guards above the splice are left in place. A display that is not a
// plan review, or a plan with no text, still returns undefined — auto-accept
// means "do not ask", not "approve anything".
//
// WHAT IT COSTS, AND THE CASE WHERE IT IS WRONG
// The prompt is the one place a plan can still be rejected or corrected before
// any file is touched, and this removes it. Worse, it is silent about a case
// that has no good automatic answer: when a plan offers several approaches,
// the prompt is how one is chosen. Auto-accepting selects none of them, and
// the model is told to execute the plan without a chosen approach. If you work
// with multi-option plans, leave this off.
//
// ------------------------------------------------------------------ settings
//
// `auto_accept_plan` in patch-settings.conf: on | off. The default matches
// lib/patch_settings.py, and it is `off` because of the paragraph above.

const MODE = String(settings.get('auto_accept_plan', 'off')).toLowerCase();

if (!['on', 'off'].includes(MODE)) {
  throw new Error(`auto_accept_plan must be on or off - got "${MODE}"`);
}

if (MODE === 'off') {
  throw new Error('already patched');
}

const ANCHOR = 'if (display.plan.trim().length === 0) return void 0;';

const REPLACEMENT = ANCHOR + '\n'
  + '\t\t\treturn this.approvalResult({ decision: "approved" }, display);';

if (js.includes(REPLACEMENT)) {
  throw new Error('already patched');
}

const n = js.split(ANCHOR).length - 1;
if (n === 0) {
  throw new Error('the plan review\'s empty-plan guard not found - '
    + 'the shape changed this release');
}
if (n !== 1) {
  throw new Error(`the plan review's empty-plan guard is not unique (${n}) - `
    + 'refusing to guess');
}

return js.replace(ANCHOR, () => REPLACEMENT);

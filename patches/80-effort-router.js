// Set the reasoning effort per turn, from the prompt itself.
//
// Kimi resolves one effort level per request, in exactly one place:
//
//   resolveThinkingEffort(requested, model) {
//     return resolveThinkingEffortForModel(requested, this.config.get(THINKING_SECTION),
//                                          model, this.strictThinkingValidation(model));
//   }
//
// `requested` is undefined unless something asked for a level, and the
// configured default is used instead. This patch fills that gap: when nothing
// asked, the router answers with a level derived from what you just typed.
//
// WHERE THE PROMPT IS SEEN
// Every prompt passes through `promptMetadataTextFromText`, which strips keys,
// tokens and control characters before anything else stores it. Reading the
// text there rather than at the composer means the router never sees a
// credential the rest of Kimi has already decided to redact, and it means one
// hook covers both the typed and the programmatic path.
//
// The splice observes and returns the value unchanged. If a release stops
// calling it on some turn, the routed level simply persists from the previous
// turn — the failure mode is a stale level, never a wrong request.
//
// WHY THERE IS NO CLASSIFIER MODEL
// tweakcc routes with a one-shot Haiku side-call. That is the better
// classifier and it is deliberately not ported, for two reasons. Kimi has no
// equivalent side-call helper to borrow, so it would mean building a second
// request path inside a patch — the kind of thing that belongs in a feature.
// And the side-call has a running cost that the thing it optimises does not
// obviously repay. What is here instead is a rule you can read in ten seconds
// and predict: it is worse at the margin and honest about it.
//
// WHAT IT COSTS
// Effort is part of the request. Changing it mid-conversation is exactly as
// expensive as your provider makes it — if it keys its prompt cache by the
// reasoning parameters, a turn that changes the level pays for a cold cache.
// That is measurable on your own bill and was not measured here, which is why
// `pin` exists: it only ever raises the level within a session, so the price
// is paid once instead of on every swing.
//
// Kimi's own guards still run last. `normalizeThinkingEffortForModel` clamps a
// level the model does not support, so the router can ask for `max` without
// having to know which models have it.
//
// ------------------------------------------------------------------ settings
//
// `effort_router` in patch-settings.conf:
//   off    Kimi's configured level, unchanged
//   pin    route upward only; the level never drops within a session
//   free   route both ways, every turn
//
// The rule, in order — first match wins:
//   max     "ultrathink", "think harder", "think deeply"
//   xhigh   "think hard", "carefully", "root cause", "why does", "design",
//           "architecture", "security", "race", "deadlock", "refactor"
//   low     under 80 characters and starting with a lookup verb
//           ("what is", "where is", "list", "show", "read", "open", "find")
//   medium  everything else

const MODE = String(settings.get('effort_router', 'off')).toLowerCase();
const ALLOWED = ['off', 'pin', 'free'];

if (!ALLOWED.includes(MODE)) {
  throw new Error(`effort_router must be one of ${ALLOWED.join(', ')} - got "${MODE}"`);
}

if (MODE === 'off') {
  throw new Error('already patched');
}

const MARK = '__tweakkimiEffort';

if (js.includes(MARK)) {
  throw new Error('already patched');
}

// ------------------------------------------------------------ 1. the router
//
// Kept in one string so the two splices below cannot drift apart, and hung off
// `globalThis` because the two sites are in different modules with no import
// between them. The rank table is what makes `pin` a floor rather than a
// second rule: levels are compared by their position in it.

const ROUTER = 'globalThis.' + MARK + '=globalThis.' + MARK + '||{level:void 0,'
  + 'pin:' + JSON.stringify(MODE === 'pin') + ','
  + 'rank:{off:0,minimal:1,low:2,medium:3,high:4,xhigh:5,max:6},'
  + 'route:function(t){'
  + 'if(typeof t!=="string"||t.length===0)return;'
  + 'var s=t.toLowerCase(),n;'
  + 'if(/ultrathink|think harder|think deeply/.test(s))n="max";'
  + 'else if(/think hard|carefully|root cause|why does|why is|design|architecture'
  + '|security|race condition|deadlock|refactor/.test(s))n="xhigh";'
  + 'else if(s.length<80&&/^(what is|what does|where is|where are|list |show |read '
  + '|open |find |which )/.test(s))n="low";'
  + 'else n="medium";'
  + 'if(this.pin&&this.level!==void 0&&(this.rank[n]||0)<=(this.rank[this.level]||0))return;'
  + 'this.level=n;'
  + '}};';

// ------------------------------------------------- 2. observe every prompt

const SEEN_ANCHOR = 'if (sanitized.length === 0) return void 0;\n'
  + '\treturn sanitized.slice(0, MAX_LAST_PROMPT_LENGTH);';

const SEEN_REPLACEMENT = 'if (sanitized.length === 0) return void 0;\n'
  + '\t' + ROUTER + '\n'
  + '\ttry { globalThis.' + MARK + '.route(sanitized); } catch {}\n'
  + '\treturn sanitized.slice(0, MAX_LAST_PROMPT_LENGTH);';

let seen = js.split(SEEN_ANCHOR).length - 1;
if (seen === 0) {
  throw new Error('the prompt sanitiser not found - the shape changed this release');
}
if (seen !== 1) {
  throw new Error(`the prompt sanitiser is not unique (${seen}) - refusing to guess`);
}

let out = js.replace(SEEN_ANCHOR, () => SEEN_REPLACEMENT);

// --------------------------------------------------- 3. answer with a level
//
// Only when nothing else asked. An explicit request — the profile's own level,
// a command, anything that passes `requested` — wins over the router, which is
// the same precedence tweakcc gives an explicit override.

const USE_ANCHOR = 'resolveThinkingEffort(requested, model) {\n'
  + '\t\t\treturn resolveThinkingEffortForModel(requested, this.config.get(THINKING_SECTION), '
  + 'model, this.strictThinkingValidation(model));';

const USE_REPLACEMENT = 'resolveThinkingEffort(requested, model) {\n'
  + '\t\t\tif (requested === void 0) { const r = globalThis.' + MARK + '; '
  + 'if (r && r.level !== void 0) requested = r.level; }\n'
  + '\t\t\treturn resolveThinkingEffortForModel(requested, this.config.get(THINKING_SECTION), '
  + 'model, this.strictThinkingValidation(model));';

const used = out.split(USE_ANCHOR).length - 1;
if (used === 0) {
  throw new Error('the effort resolver not found in agent-core-v2 - '
    + 'the shape changed this release');
}
if (used !== 1) {
  throw new Error(`the effort resolver is not unique (${used}) - refusing to guess`);
}

return out.replace(USE_ANCHOR, () => USE_REPLACEMENT);

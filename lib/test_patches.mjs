// Behaviour suite for the patch runner and for the patches themselves.
//
//   node lib/test_patches.mjs          runner contract only (fast, no bundle)
//   node lib/test_patches.mjs --bundle also applies every patch to the real
//                                      extracted bundle
//
// Two things are worth testing here and nothing else is. The runner's contract,
// because every patch depends on it: what a patch receives, what counts as a
// failure, and what `already patched` means. And each patch against the real
// bundle, because the only failure mode a patch has in practice is an anchor
// that moved — which no fixture can predict and no amount of unit testing can
// catch.
//
// Idempotency is checked the same way the runner defines it: applying a patch
// to its own output must throw `already patched`, not silently patch twice.

import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(HERE);
const RUNNER = join(HERE, 'run-patches.mjs');
const BUNDLE = join(ROOT, '.work', 'bundle.js');

let pass = 0;
const failures = [];

function check(name, cond, detail = '') {
  if (cond) { pass++; console.log('  ok   ' + name); }
  else { failures.push(name); console.log(`  FAIL ${name}${detail ? '  — ' + detail : ''}`); }
}

function sandbox() {
  const d = mkdtempSync(join(tmpdir(), 'tweakkimi-patches-'));
  mkdirSync(join(d, 'patches'));
  return d;
}

function runRunner(dir, input) {
  writeFileSync(join(dir, 'in.js'), input);
  try {
    const out = execFileSync(process.execPath,
      [RUNNER, join(dir, 'in.js'), join(dir, 'out.js'), join(dir, 'patches')],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
    return { code: 0, out, result: readFileSync(join(dir, 'out.js'), 'utf8') };
  } catch (e) {
    return { code: e.status ?? 1, out: (e.stdout || '') + (e.stderr || ''), result: null };
  }
}

// -------------------------------------------------------------------------
// the runner's contract
// -------------------------------------------------------------------------

console.log('runner contract:');

{
  const d = sandbox();
  writeFileSync(join(d, 'patches', 'a.js'), 'return js.replace("x", () => "y");');
  const r = runRunner(d, 'x');
  check('a patch rewrites the bundle', r.code === 0 && r.result === 'y', r.out);
}

{
  const d = sandbox();
  writeFileSync(join(d, 'patches', 'a.js'), 'throw new Error("already patched");');
  const r = runRunner(d, 'keep me');
  check("'already patched' is a no-op", r.code === 0 && r.result === 'keep me', r.out);
}

{
  const d = sandbox();
  writeFileSync(join(d, 'patches', 'a.js'), 'throw new Error("anchor not found");');
  const r = runRunner(d, 'x');
  check('a real failure stops the run', r.code !== 0);
}

{
  const d = sandbox();
  writeFileSync(join(d, 'patches', 'a.js'), 'return 42;');
  const r = runRunner(d, 'x');
  check('a non-string return is rejected', r.code !== 0);
}

// The settings channel. Three patches each grew their own copy of a
// twenty-line reader for `patch-settings.conf`; the runner now reads the file
// once and hands it over, so a patch asks a question instead of parsing a file.
{
  const d = sandbox();
  writeFileSync(join(d, 'patch-settings.conf'),
    '# a comment\nwd_command = on\nempty=\nsuggestion_height=half\n');
  writeFileSync(join(d, 'patches', 'a.js'),
    'return js + "|" + settings.get("wd_command", "off")' +
    ' + "|" + settings.get("missing", "fallback")' +
    ' + "|" + settings.get("empty", "fallback")' +
    ' + "|" + settings.get("suggestion_height", "default");');
  const r = runRunner(d, 'seed');
  check('settings reach the patch',
        r.result === 'seed|on|fallback|fallback|half', JSON.stringify(r.result));
}

{
  // No settings file at all: every lookup falls back, and nothing throws.
  const d = sandbox();
  writeFileSync(join(d, 'patches', 'a.js'),
    'return js + "|" + settings.get("wd_command", "off");');
  const r = runRunner(d, 'seed');
  check('a missing settings file falls back', r.result === 'seed|off', r.out);
}

{
  // The old idiom must keep working: a patch that ignores the second argument
  // is still a valid patch, which is what makes this change safe to land.
  const d = sandbox();
  writeFileSync(join(d, 'patches', 'a.js'), 'return js.toUpperCase();');
  const r = runRunner(d, 'abc');
  check('a patch may ignore the settings argument', r.result === 'ABC');
}

// -------------------------------------------------------------------------
// every patch against the real bundle
// -------------------------------------------------------------------------

// Every patch is exercised in its *active* state, not in whatever state
// patch-settings.conf happens to be in. A patch that is off by default would
// otherwise report `already patched` and sail through the suite with a broken
// anchor — which is the one failure this file exists to catch. The overrides
// below name the setting that turns each patch on; a patch with no switch
// needs no entry.
const ACTIVE = {
  'suggestion_height': 'half',
  'wd_command': 'on',
  'click_cursor': 'on',
  'agents_md_names': 'all',
  'read_line_numbers': 'off',
  'expanded_by_default': 'both',
  'read_limits': 'moderate',
  'auto_accept_plan': 'on',
  'effort_router': 'pin',
  'spinner_style': 'dots',
  'spinner_interval_ms': '100',
  'thinking_verbs': 'on',
  // Written the way patch-settings.conf can actually hold it: values are
  // trimmed there, so the trailing space Kimi's own marker has cannot be
  // spelled out and the patch adds it.
  'user_message_marker': '>',
  'user_message_border': 'round',
  'user_message_style': 'italic',
  'input_box_border': 'double',
};

if (process.argv.includes('--bundle')) {
  console.log('\npatches against the extracted bundle:');
  if (!existsSync(BUNDLE)) {
    console.log('  skip — no .work/bundle.js; run ./kimi-patch.sh --extract');
  } else {
    const bundle = readFileSync(BUNDLE, 'utf8');
    const settings = { get: (k, d = '') => ACTIVE[k] ?? d };
    const files = readdirSync(join(ROOT, 'patches'))
      .filter(f => f.endsWith('.js') && !f.startsWith('.')).sort();

    for (const f of files) {
      const src = readFileSync(join(ROOT, 'patches', f), 'utf8');
      let fn;
      try { fn = new Function('js', 'settings', src); }
      catch (e) { check(`${f} parses`, false, e.message); continue; }

      let once;
      try {
        once = fn(bundle, settings);
      } catch (e) {
        // A patch switched off in patch-settings.conf reports itself as a
        // no-op; that is a pass, not a missing anchor.
        check(`${f} finds its anchors`, e.message === 'already patched', e.message);
        continue;
      }
      if (typeof once !== 'string') {
        check(`${f} returns the bundle`, false, typeof once);
        continue;
      }
      check(`${f} finds its anchors`, true);
      check(`${f} changed something`, once !== bundle,
            'returned the bundle unchanged — the anchor matched nothing');

      let twice = null, thrown = null;
      try { twice = fn(once, settings); } catch (e) { thrown = e.message; }
      check(`${f} refuses to apply twice`,
            thrown === 'already patched' || twice === once,
            thrown ?? 'applied a second time and changed the bundle again');
    }

    // -- the logic two patches splice in, run in isolation -----------------
    //
    // Everything above proves a patch reaches the right place. These two put
    // the spliced code through its paces, because placement is not the
    // interesting half for either of them: a router that lands correctly and
    // then classifies everything as `medium` is worse than one that fails
    // loudly. Neither needs Kimi — the code is plain JavaScript once it is
    // out of the bundle.

    {
      const src = readFileSync(join(ROOT, 'patches', '80-effort-router.js'), 'utf8');
      const patched = new Function('js', 'settings', src)(bundle, settings);
      const decl = /globalThis\.__tweakkimiEffort=globalThis\.__tweakkimiEffort\|\|\{[\s\S]*?\}\};/
        .exec(patched);
      check('the router source can be lifted back out', decl !== null);

      if (decl !== null) {
        // The mode is baked into the source as `pin:true|false`, unquoted —
        // it is written with `'pin:' + JSON.stringify(...)`. Rewriting the
        // quoted spelling instead silently matched nothing and left both
        // builds pinned, which is how this harness first reported a router bug
        // that was its own.
        const build = (mode) => {
          const g = {};
          const source = decl[0].replace(/pin:(true|false),/, `pin:${mode === 'pin'},`);
          if (!/pin:(true|false),/.test(source)) {
            throw new Error('the router no longer carries its mode as pin:<bool>');
          }
          new Function('globalThis', source)(g);
          return g.__tweakkimiEffort;
        };

        const r = build('free');
        const route = (text) => { r.level = undefined; r.route(text); return r.level; };

        check('ultrathink asks for the top level', route('ultrathink this') === 'max',
              route('ultrathink this'));
        check('"think harder" too', route('please think harder about it') === 'max');
        check('a root-cause question routes high',
              route('why does this crash on the second run') === 'xhigh',
              route('why does this crash on the second run'));
        check('an architecture question routes high',
              route('design the module boundary here') === 'xhigh');
        check('a short lookup routes low',
              route('what is the default port') === 'low',
              route('what is the default port'));
        check('a long lookup does not route low',
              route('what is the default port, and how does the retry interact with '
                    + 'the queue when the first attempt times out midway') === 'medium');
        check('ordinary work routes medium',
              route('add a field to the settings form') === 'medium',
              route('add a field to the settings form'));
        check('empty input leaves the level alone',
              (() => { r.level = 'high'; r.route(''); return r.level; })() === 'high');
        check('a non-string leaves the level alone',
              (() => { r.level = 'high'; r.route(undefined); return r.level; })() === 'high');

        // `free` tracks both ways; `pin` is a floor. That difference is the
        // whole reason the setting has three values rather than two.
        const free = build('free');
        free.route('ultrathink this');
        free.route('what is the default port');
        check('free lets the level fall again', free.level === 'low', free.level);

        const pin = build('pin');
        pin.route('ultrathink this');
        pin.route('what is the default port');
        check('pin never lowers the level', pin.level === 'max', pin.level);
        pin.route('why does this crash');
        check('pin still refuses to lower from max', pin.level === 'max', pin.level);
      }
    }

    {
      const src = readFileSync(join(ROOT, 'patches', '71-thinking-verbs.js'), 'utf8');
      const patched = new Function('js', 'settings', src)(bundle, settings);
      const decl = /const KIMI_MODS_ACTIVITY_VERBS = \[[\s\S]*?\n\}\n/.exec(patched);
      check('the verb helper can be lifted back out', decl !== null);

      if (decl !== null) {
        const verbs = new Function(decl[0] + '\nreturn {KIMI_MODS_ACTIVITY_VERBS, kimiModsActivityVerb};')();
        const all = verbs.KIMI_MODS_ACTIVITY_VERBS;
        check('there are several verbs', all.length >= 8, all.length);
        check('the verb it returns is one of them',
              all.includes(verbs.kimiModsActivityVerb()));
        check('every verb is a non-empty string',
              all.every(v => typeof v === 'string' && v.length > 0));
        check('no verb repeats', new Set(all).size === all.length,
              all.length - new Set(all).size + ' duplicate(s)');
      }
    }

    // The whole stack, applied in filename order, must still parse. A patch
    // that splices in broken JavaScript passes every check above and then
    // takes the binary down at startup with no message — which is the worst
    // failure this project has, and the cheapest one to rule out.
    let stacked = bundle;
    const applied = [];
    for (const f of files) {
      const fn = new Function('js', 'settings', readFileSync(join(ROOT, 'patches', f), 'utf8'));
      try {
        const next = fn(stacked, settings);
        if (typeof next === 'string') { stacked = next; applied.push(f); }
      } catch { /* a no-op here was already reported above */ }
    }
    const probe = join(mkdtempSync(join(tmpdir(), 'tweakkimi-parse-')), 'bundle.js');
    writeFileSync(probe, stacked);
    let parseError = '';
    try {
      execFileSync(process.execPath, ['--check', probe],
                   { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (e) {
      parseError = ((e.stderr || '') + (e.stdout || '')).split('\n').slice(0, 4).join(' ');
    }
    check(`all ${applied.length} patches together still parse as JavaScript`,
          parseError === '', parseError);
  }
}

function readSettings(path) {
  const values = new Map();
  try {
    for (const line of readFileSync(path, 'utf8').split('\n')) {
      const t = line.trim();
      if (!t || t.startsWith('#')) continue;
      const i = t.indexOf('=');
      if (i > 0) values.set(t.slice(0, i).trim(), t.slice(i + 1).trim());
    }
  } catch { /* no file is a valid state: every lookup falls back */ }
  return { get: (k, d = '') => (values.get(k) || d) };
}

console.log();
if (failures.length === 0) {
  console.log(`${pass} passed, 0 failed.`);
} else {
  console.log(`${pass} passed, ${failures.length} FAILED.`);
  process.exit(1);
}

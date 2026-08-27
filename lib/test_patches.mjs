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
  const d = mkdtempSync(join(tmpdir(), 'kimi-code-mods-patches-'));
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
  'spinner_mirror': 'on',
  // Only read by the `custom` style, so it is inert in the sweep above and
  // exercised on its own below.
  'spinner_frames': 'default',
  'thinking_verbs': 'on',
  // Left at its default here so the sweep exercises the patch's own list —
  // its length is what the checks below assert on. A list of your own is
  // exercised on its own further down.
  'thinking_verbs_list': 'default',
  'thinking_verbs_format': '{}…',
  // Written the way patch-settings.conf can actually hold it: values are
  // trimmed there, so the trailing space Kimi's own marker has cannot be
  // spelled out and the patch adds it.
  'user_message_marker': '>',
  'user_message_border': 'round',
  'user_message_style': 'italic',
  'input_box_border': 'double',
  'cron_drop_dir': 'on',
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
      const decl = /globalThis\["__kimi-code-modsEffort"\]=globalThis\["__kimi-code-modsEffort"\]\|\|\{[\s\S]*?\}\};/
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
          return g['__kimi-code-modsEffort'];
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
      // The composer border does not rename the characters in place; it wraps
      // the original function and translates on the way out. That makes the
      // translation itself worth running: a swap table that misses a character
      // leaves a double frame half round and half square, which no placement
      // check would notice.
      const src = readFileSync(join(ROOT, 'patches', '73-input-box-border.js'), 'utf8');
      const styles = ['off', 'single', 'double', 'bold'];
      for (const style of styles) {
        const s = { get: (k, d = '') => (k === 'input_box_border' ? style : (ACTIVE[k] ?? d)) };
        const patched = new Function('js', 'settings', src)(bundle, s);
        const decl = /const swap = \{[^}]*\};/.exec(patched);
        if (decl === null) { check(`${style}: swap table found`, false); continue; }
        const swap = new Function(decl[0] + '\nreturn swap;')();
        const paint = (t) => t.replace(/[╭╮╰╯├┤─│]/g, (ch) => swap[ch] ?? ch);

        check(`${style}: the round corners are translated`,
              paint('╭╮╰╯') !== '╭╮╰╯', paint('╭╮╰╯'));
        check(`${style}: nothing outside the frame set is touched`,
              paint('! shell mode') === '! shell mode');
        // Every style either renames a character or blanks it; none may leave
        // a corner untranslated while translating its neighbour, because that
        // is what a half-square frame looks like.
        const corners = [...'╭╮╰╯'].map(paint);
        check(`${style}: all four corners agree`,
              new Set(corners.map(c => c === ' ')).size === 1,
              corners.join(''));
      }
    }

    {
      // Your own words and your own format have to reach the bundle, not just
      // be accepted by the patch — the list is spliced in as a literal, so a
      // setting that is read and then dropped would look identical from here
      // unless the literal itself is checked.
      const over = (extra) => ({ get: (k, d = '') => extra[k] ?? ACTIVE[k] ?? d });
      const mine = over({ thinking_verbs_list: 'alpha, beta, gamma',
                          thinking_verbs_format: '{}…' });
      const src71 = readFileSync(join(ROOT, 'patches', '71-thinking-verbs.js'), 'utf8');
      const own = new Function('js', 'settings', src71)(bundle, mine);
      check('your own words reach the bundle',
            own.includes('"alpha…"') && own.includes('"gamma…"'));
      check('and the built-in ones do not', !own.includes('"untangling..."'));

      // A format with no place for the word is refused rather than showing
      // one fixed string on every frame, which is the opposite of rotating.
      const bad = over({ thinking_verbs_list: 'alpha, beta, gamma',
                         thinking_verbs_format: 'no placeholder' });
      let refused = '';
      try { new Function('js', 'settings', src71)(bundle, bad); }
      catch (e) { refused = e.message; }
      check('a format without {} is refused', refused.includes('{}'), refused);
    }

    {
      // Custom spinner frames: both spellings mean the same list, and asking
      // for `custom` without supplying any is an error rather than a spinner
      // that quietly stays as it was.
      const src70 = readFileSync(join(ROOT, 'patches', '70-spinner-style.js'), 'utf8');
      for (const [written, expected] of [['x y z', '"x",\n\t\t"y",\n\t\t"z"'],
                                         ['xyz', '"x",\n\t\t"y",\n\t\t"z"']]) {
        const s70 = { get: (k, d = '') => ({ spinner_style: 'custom',
                                             spinner_frames: written })[k]
                                          ?? ACTIVE[k] ?? d };
        const out70 = new Function('js', 'settings', src70)(bundle, s70);
        check(`custom frames written as "${written}" reach the bundle`,
              out70.includes(expected), written);
      }
      const empty = { get: (k, d = '') => ({ spinner_style: 'custom',
                                             spinner_frames: 'default' })[k]
                                          ?? ACTIVE[k] ?? d };

      // Mirroring is a pass over whichever frames were chosen, so it has to
      // work with a preset as well as with frames of your own — as a style of
      // its own it could only ever mirror Kimi's.
      const mirrored = { get: (k, d = '') => ({ spinner_style: 'custom',
                                                spinner_frames: 'a b c',
                                                spinner_mirror: 'on' })[k]
                                             ?? ACTIVE[k] ?? d };
      const swung = new Function('js', 'settings', src70)(bundle, mirrored);
      check('mirroring runs the chosen frames there and back',
            swung.includes('"a",\n\t\t"b",\n\t\t"c",\n\t\t"c",\n\t\t"b",\n\t\t"a"'),
            /BRAILLE_SPINNER_FRAMES = \[[^\]]*\]/.exec(swung)?.[0]?.slice(0, 120));

      // Applied twice it must not double the frames again: a mirrored list is
      // a palindrome of even length, which is what tells a second run apart.
      // Without that the frame count would grow on every application, and the
      // runner would only notice once the spinner had forty of them.
      let second = '';
      try { new Function('js', 'settings', src70)(swung, mirrored); }
      catch (e) { second = e.message; }
      check('mirroring an already mirrored list is a no-op',
            second === 'already patched', second);

      const plainMirror = { get: (k, d = '') => ({ spinner_style: 'default',
                                                   spinner_mirror: 'on' })[k]
                                                ?? ACTIVE[k] ?? d };
      const own = new Function('js', 'settings', src70)(bundle, plainMirror);
      check('it also mirrors Kimi\'s own frames', own !== bundle);
      let why = '';
      try { new Function('js', 'settings', src70)(bundle, empty); }
      catch (e) { why = e.message; }
      check('custom with no frames is refused', why.includes('spinner_frames'), why);

      const one = { get: (k, d = '') => ({ spinner_style: 'custom',
                                           spinner_frames: 'x' })[k]
                                        ?? ACTIVE[k] ?? d };
      let why2 = '';
      try { new Function('js', 'settings', src70)(bundle, one); }
      catch (e) { why2 = e.message; }
      check('a single frame is refused', why2.includes('two frames'), why2);
    }

    {
      const src = readFileSync(join(ROOT, 'patches', '71-thinking-verbs.js'), 'utf8');
      const patched = new Function('js', 'settings', src)(bundle, settings);
      const decl = /const KIMICODEMODS_ACTIVITY_VERBS = \[[\s\S]*?\n\}\n/.exec(patched);
      check('the verb helper can be lifted back out', decl !== null);

      if (decl !== null) {
        const verbs = new Function(decl[0] + '\nreturn {KIMICODEMODS_ACTIVITY_VERBS, kimiCodeModsActivityVerb};')();
        const all = verbs.KIMICODEMODS_ACTIVITY_VERBS;
        check('there are several verbs', all.length >= 8, all.length);
        check('the verb it returns is one of them',
              all.includes(verbs.kimiCodeModsActivityVerb()));
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
    const probe = join(mkdtempSync(join(tmpdir(), 'kimi-code-mods-parse-')), 'bundle.js');
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

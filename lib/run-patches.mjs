// Apply every patches/*.js to the extracted bundle, in filename order.
//
// A patch is a function body that receives the bundle as `js` and its own
// switches as `settings`, and returns the new bundle. Same shape tweakcc's
// `adhoc-patch --script` uses, so patches are easy to move between the two
// setups:
//
//   if (settings.get('my_feature', 'off') !== 'on') throw new Error('already patched');
//   if (!js.includes(ANCHOR)) throw new Error('anchor not found');
//   if (js.includes(REPLACEMENT)) throw new Error('already patched');
//   return js.replace(ANCHOR, () => REPLACEMENT);
//
// `already patched` is a no-op, not a failure: a patch that has nothing to do
// on this build must not abort the run. Anything else thrown is a real failure
// and stops everything — a half-applied bundle is worse than an unpatched one.
//
// `settings` is read here, once, rather than in each patch. Three patches had
// each grown their own twenty-line copy of the same reader — resolving the
// file relative to the patch directory, tolerating its absence, parsing
// `key=value` — and a fourth copy would have been the moment the four started
// to disagree about what a missing file means.

import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const [, , inPath, outPath, patchDir] = process.argv;

// The settings file sits next to `patches/`, not next to this script: the
// patch directory is what the caller chose, and the sandboxed test suite
// relies on that being the only thing it has to point at.
function readSettings(dir) {
  const values = new Map();
  try {
    const conf = join(dirname(resolve(dir)), 'patch-settings.conf');
    for (const line of readFileSync(conf, 'utf8').split('\n')) {
      const t = line.trim();
      if (!t || t.startsWith('#')) continue;
      const i = t.indexOf('=');
      if (i > 0) values.set(t.slice(0, i).trim(), t.slice(i + 1).trim());
    }
  } catch {
    // No file, or an unreadable one, is a valid state and must not fail the
    // run: every lookup then falls back to the default the patch names.
  }
  // An empty value means "say nothing", so it falls back like a missing key.
  // Otherwise `key=` in the file would switch a feature to the empty string
  // and the patch would compare it against 'on' and quietly do nothing.
  return { get: (key, fallback = '') => values.get(key) || fallback };
}

// Operating-system files are never patches — `._fix.js` is a macOS sidecar,
// not code, and running it would fail in a confusing way. One shared list, see
// lib/os-cruft.txt.
const cruft = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'os-cruft.txt'), 'utf8')
  .split('\n')
  .map(l => l.replace(/#.*/, '').trim())
  .filter(Boolean)
  .map(p => new RegExp('^' + p.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*') + '$', 'i'));

const isCruft = name => cruft.some(re => re.test(name));

let js = readFileSync(inPath, 'utf8');
const before = js.length;

const files = readdirSync(patchDir).filter(f => f.endsWith('.js') && !isCruft(f)).sort();
if (files.length === 0) {
  console.log('no patches in ' + patchDir + ' — nothing to do');
  writeFileSync(outPath, js);
  process.exit(0);
}

let applied = 0, skipped = 0;
const failures = [];
const settings = readSettings(patchDir);

for (const f of files) {
  const src = readFileSync(join(patchDir, f), 'utf8');
  let fn;
  try {
    fn = new Function('js', 'settings', src);
  } catch (e) {
    failures.push(`${f}: does not parse — ${e.message}`);
    continue;
  }
  try {
    const out = fn(js, settings);
    if (typeof out !== 'string') {
      failures.push(`${f}: returned ${typeof out}, expected the patched bundle as a string`);
      continue;
    }
    const delta = out.length - js.length;
    js = out;
    applied++;
    const sign = delta === 0 ? 'no size change' : (delta > 0 ? `+${delta}` : `${delta}`) + ' chars';
    console.log(`  ✓ ${f} (${sign})`);
  } catch (e) {
    if (e.message === 'already patched') {
      skipped++;
      console.log(`  · ${f}: no-op on this build`);
    } else {
      failures.push(`${f}: ${e.message}`);
      console.log(`  ✗ ${f}: ${e.message}`);
    }
  }
}

if (failures.length) {
  console.error(`\n${failures.length} patch(es) failed:`);
  for (const f of failures) console.error('  ' + f);
  process.exit(1);
}

writeFileSync(outPath, js);
const delta = js.length - before;
console.log(`${applied} applied, ${skipped} no-op; bundle ${delta >= 0 ? '+' : ''}${delta} chars`);

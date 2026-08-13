// Example patch — proves the whole chain works and shows the expected shape.
// Delete it once you have real patches; it only rewrites the tagline in
// `kimi --help`, which makes a successful run visible without reading a log.
//
// The three guards below are the pattern worth copying:
//   * bail out loudly when the anchor is gone (the bundle is minified and
//     changes shape on every release)
//   * refuse to act when the anchor is ambiguous, rather than hitting whichever
//     occurrence comes first
//   * throw 'already patched' — the one message treated as a no-op, not a
//     failure — when there is nothing left to do

const ANCHOR = 'The Starting Point for Next-Gen Agents';
const REPLACEMENT = 'The Starting Point for Next-Gen Agents [tweakkimi]';

if (js.includes(REPLACEMENT)) {
  throw new Error('already patched');
}

const count = js.split(ANCHOR).length - 1;
if (count === 0) {
  throw new Error('banner tagline not found — it changed in this release');
}
if (count !== 1) {
  throw new Error(`banner tagline is not unique (${count} occurrences) — refusing to guess`);
}

return js.replace(ANCHOR, () => REPLACEMENT);

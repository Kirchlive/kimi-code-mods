#!/usr/bin/env python3
"""Reconstruct Kimi's prompt files from the bundle.

Every prompt in Kimi Code is a markdown file imported with `?raw`. The bundler
keeps the original path in a region comment and assigns the file's contents to
a module variable:

    //#region ../../packages/agent-core/src/profile/default/system.md?raw
    var system_default$1;
    var init_system$1 = __esmMin((() => {
        system_default$1 = `You are ${product_name}, an interactive …`;
    }));

So the prompts do not have to be guessed at by shape — they can be recovered
with their real names and directory layout. Each file is written back to
`<out>/<path under the package>`, with a header recording where it came from.

Kimi ships most prompts twice: once as a template literal with `${var}` holes
and once as a plain string with `{{ var }}` holes. Both are kept; the variant
is recorded in the header and in the filename suffix when they differ.

usage: extract-prompts.py <bundle.js> <outdir>
"""

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import jsstr


def sha(text: str) -> str:
    """Fingerprint of the pristine prompt, so an override can tell when
    upstream moved underneath it."""
    return hashlib.sha256(text.encode('utf8')).hexdigest()[:16]

REGION = re.compile(r'//#region (\S+?\.(?:md|ya?ml|toml|txt))\?raw\n')

# Prompt text that is not a `?raw` import lives in named constants instead —
# role prefixes, injected sections, summary prompts. Screaming-snake names and
# the bundler's `*_default` are the reliable markers; everything else in the
# bundle at that size is library code or JSDoc.
INLINE_NAME = re.compile(r'^(?:[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[a-z_$][\w$]*_default(?:\$\d+)?)$')
# Not every constant is declared with var/let/const — plenty are plain
# assignments inside a module initialiser, which is exactly where the bundler
# puts them.
INLINE_DECL = re.compile(r'(?:(?:var|let|const)\s+)?([A-Za-z_$][\w$]*)\s*=\s*(["\'`])')
MIN_INLINE = 200


def reads_like_a_prompt(text: str) -> bool:
    """Model-facing prose, as opposed to a word list or a code fragment."""
    words = re.findall(r'[A-Za-z][a-z]{2,}', text)
    letters = sum(c.isalpha() or c.isspace() for c in text)
    if len(words) < 20 or letters / len(text) < 0.75:
        return False
    addresses_model = re.search(r'\b(?:you|your|yours)\b', text, re.I)
    sentences = len(re.findall(r'[a-z][.!?](?:\s|$)', text))
    return bool(addresses_model) or sentences >= 2
# The assignment that follows the region header, e.g. `system_default$1 = ` or
# `\tsystem_default = `. The quote character tells us which variant this is.
ASSIGN = re.compile(r'([A-Za-z_$][\w$]*)\s*=\s*(["\'`])')


def read_literal(src: str, quote_at: int, quote: str) -> tuple[str, int]:
    """Return the raw literal body starting after `quote_at`, plus its end."""
    j = quote_at + 1
    n = len(src)
    while j < n:
        if src[j] == '\\':
            j += 2
            continue
        if src[j] == quote:
            return src[quote_at + 1:j], j
        j += 1
    raise ValueError(f'unterminated literal at {quote_at}')


def decode(body: str, quote: str) -> str:
    return jsstr.decode(body)


def variant(text: str, quote: str) -> str:
    if quote == '`' and re.search(r'\$\{[\w.]+\}', text):
        return 'template'
    if re.search(r'\{\{\s*[\w.]+\s*\}\}', text):
        return 'mustache'
    return 'plain'


def main():
    bundle = Path(sys.argv[1])
    out = Path(sys.argv[2])
    src = bundle.read_text(encoding='utf8', errors='replace')

    regions = list(REGION.finditer(src))
    print(f'markdown regions in the bundle: {len(regions)}')

    written, skipped, by_pkg = 0, [], {}
    seen: dict[tuple[str, str], int] = {}
    taken: set[int] = set()          # literal positions claimed by a source file

    for r in regions:
        path = r.group(1)
        # The assignment lives shortly after the region header.
        window = src[r.end():r.end() + 4000]
        m = ASSIGN.search(window)
        if not m:
            skipped.append((path, 'no assignment found'))
            continue
        quote_at = r.end() + m.end() - 1
        try:
            body, _ = read_literal(src, quote_at, m.group(2))
        except ValueError as e:
            skipped.append((path, str(e)))
            continue
        text = decode(body, m.group(2))
        if not text.strip():
            skipped.append((path, 'empty'))
            continue

        taken.add(quote_at)
        var = variant(text, m.group(2))
        # Strip the leading ../.. and keep the meaningful part of the path.
        rel = re.sub(r'^(?:\.\./)+', '', path)
        key = (rel, var)
        seen[key] = seen.get(key, 0) + 1
        stem = Path(rel)
        suffix = '' if seen[key] == 1 else f'.{seen[key]}'
        dest = out / stem.parent / f'{stem.stem}{suffix}.{var}.md'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            '<!--\n'
            f'source: {path}\n'
            f'module: {m.group(1)}\n'
            f'variant: {var}\n'
            f'chars: {len(text)}\n'
            f'originSha256: {sha(text)}\n'
            f'trailingNewlines: {len(text) - len(text.rstrip(chr(10)))}\n'
            f'bundleOffset: {quote_at}\n'
            '-->\n' + text.rstrip('\n') + '\n',
            encoding='utf8')
        written += 1
        pkg = rel.split('/src/')[0]
        by_pkg[pkg] = by_pkg.get(pkg, 0) + 1

    # --- inline constants, i.e. prompt text with no source file behind it.
    # Exclude only the literals already written out above, by exact position;
    # a window around the region header would swallow neighbouring constants.
    inline = 0
    inline_seen: dict[str, int] = {}
    for m in INLINE_DECL.finditer(src):
        name, quote = m.group(1), m.group(2)
        if not INLINE_NAME.match(name):
            continue
        quote_at = m.end() - 1
        if quote_at in taken:
            continue                      # already recovered as a source file
        try:
            body, _ = read_literal(src, quote_at, quote)
        except ValueError:
            continue
        if len(body) < MIN_INLINE:
            continue
        text = decode(body, quote)
        if not reads_like_a_prompt(text):
            continue
        base = re.sub(r'\$\d+$', '', name)
        inline_seen[base] = inline_seen.get(base, 0) + 1
        suffix = '' if inline_seen[base] == 1 else f'.{inline_seen[base]}'
        dest = out / 'inline' / f'{base}{suffix}.{variant(text, quote)}.md'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            '<!--\n'
            f'source: inline constant (no source file in the bundle)\n'
            f'module: {name}\n'
            f'variant: {variant(text, quote)}\n'
            f'chars: {len(text)}\n'
            f'originSha256: {sha(text)}\n'
            f'trailingNewlines: {len(text) - len(text.rstrip(chr(10)))}\n'
            f'bundleOffset: {quote_at}\n'
            '-->\n' + text.rstrip('\n') + '\n',
            encoding='utf8')
        inline += 1

    print(f'wrote {written} source-file prompts and {inline} inline constants to {out}')
    for pkg, n in sorted(by_pkg.items(), key=lambda kv: -kv[1]):
        print(f'  {pkg:<46} {n}')
    if skipped:
        print(f'\nskipped {len(skipped)}:')
        for p, why in skipped[:15]:
            print(f'  {p}: {why}')


if __name__ == '__main__':
    main()

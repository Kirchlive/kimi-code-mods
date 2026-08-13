#!/usr/bin/env python3
"""Write the files under system-prompts/ back into the bundle.

Every file there was extracted from the binary and carries a header naming the
literal it came from. Edit the markdown, run the patcher, and the edited text
replaces the built-in prompt.

Files are located by *anchor*, never by the recorded offset: offsets shift as
soon as an earlier replacement changes length, and they mean nothing at all
after a Kimi update. The anchor is the upstream source path
(`//#region …/system.md?raw`) or, for prompts with no source file, the constant
name. Both are real names from Kimi's own code rather than bundler artefacts,
so they survive a release far better than a position or a minified identifier.

Three guards, because all three failure modes are quiet:

  * **Drift.** The header records a fingerprint of the pristine prompt. If the
    prompt in the bundle no longer matches, the override was written against an
    older Kimi and is applied only when the file is unchanged from that older
    text — otherwise it is reported and skipped, never silently forced.
  * **Interpolation.** Prompts carry `${VAR}` holes the runtime fills. An
    override that invents a new one crashes the bundle at load; one that drops
    an existing one silently loses whatever it delivered. Both are checked.
  * **Escaping.** Text goes back into a JavaScript literal, so backslashes,
    the quote character and — in template literals — `` ` `` have to be
    re-escaped, while `${` must stay intact to keep interpolation working.

usage: apply-prompt-overrides.py <bundle.js> <prompt-dir> <out.js>
"""

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import jsstr
from oscruft import usable_files

REGION = re.compile(r'//#region (\S+?\.(?:md|ya?ml|toml|txt))\?raw\n')
ASSIGN = re.compile(r'([A-Za-z_$][\w$]*)\s*=\s*(["\'`])')
# Kimi fills two kinds of hole: `${VAR}` in template literals, `{{ VAR }}` in
# the mustache variants. Both have to survive an override intact.
INTERP = re.compile(r'\$\{[^}]{0,80}\}|\{\{\s*[\w.]{1,60}\s*\}\}')


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf8')).hexdigest()[:16]


def read_literal(src: str, quote_at: int, quote: str):
    j, n = quote_at + 1, len(src)
    while j < n:
        if src[j] == '\\':
            j += 2
            continue
        if src[j] == quote:
            return src[quote_at + 1:j], j
        j += 1
    raise ValueError(f'unterminated literal at {quote_at}')


decode = jsstr.decode
encode = jsstr.encode


def parse_header(raw: str):
    if not raw.startswith('<!--\n'):
        return None, raw
    end = raw.find('\n-->\n')
    if end < 0:
        return None, raw
    head = {}
    for line in raw[5:end].splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            head[k.strip()] = v.strip()
    return head, raw[end + 5:]


def index_bundle(src: str):
    """Map anchor -> (module, quote, quote_at, original_text)."""
    by_source, by_module = {}, {}
    taken = set()

    for r in REGION.finditer(src):
        window = src[r.end():r.end() + 4000]
        m = ASSIGN.search(window)
        if not m:
            continue
        quote_at = r.end() + m.end() - 1
        try:
            body, _ = read_literal(src, quote_at, m.group(2))
        except ValueError:
            continue
        rec = (m.group(1), m.group(2), quote_at, decode(body))
        by_source.setdefault(r.group(1), []).append(rec)
        taken.add(quote_at)

    for m in re.finditer(r'(?:(?:var|let|const)\s+)?([A-Za-z_$][\w$]*)\s*=\s*(["\'`])', src):
        quote_at = m.end() - 1
        if quote_at in taken:
            continue
        try:
            body, _ = read_literal(src, quote_at, m.group(2))
        except ValueError:
            continue
        if len(body) < 100:
            continue
        by_module.setdefault(m.group(1), []).append(
            (m.group(1), m.group(2), quote_at, decode(body)))

    return by_source, by_module


def main():
    bundle, promptdir, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    src = bundle.read_text(encoding='utf8', errors='replace')

    if not promptdir.is_dir():
        out.write_text(src, encoding='utf8')
        print(f'no prompt directory at {promptdir} — bundle unchanged')
        return

    by_source, by_module = index_bundle(src)
    files = usable_files(promptdir)

    edits = []          # (quote_at, quote, old_text, new_text, label)
    unchanged = drift = missing = broken = 0

    for f in files:
        head, body = parse_header(f.read_text(encoding='utf8', errors='replace'))
        label = str(f.relative_to(promptdir))
        if not head:
            print(f'  ! {label}: no header — skipped (re-extract to regenerate it)')
            broken += 1
            continue

        # Editors like to add a final newline, and the extractor writes one of
        # its own. Neither should count as an edit, so the trailing newlines of
        # the original are restored from the header.
        new_text = body.rstrip('\n') + '\n' * int(head.get('trailingNewlines', 0) or 0)
        want_sha = head.get('originSha256', '')
        module = head.get('module', '')
        source = head.get('source', '')

        # Resolve the anchor: source path first, constant name as fallback.
        cands = by_source.get(source, []) or by_module.get(module, [])
        if not cands:
            base = re.sub(r'\$\d+$', '', module)
            cands = by_module.get(base, [])
        if not cands:
            print(f'  ? {label}: anchor gone (source {source or module}) — skipped')
            missing += 1
            continue

        # Prefer the candidate whose current text still matches the recorded
        # fingerprint; that is the literal this file was extracted from.
        pick = next((c for c in cands if sha(c[3]) == want_sha), None)
        drifted = pick is None
        if drifted:
            pick = cands[0]

        mod, quote, quote_at, old_text = pick

        if new_text == old_text:
            unchanged += 1
            continue

        if drifted:
            if sha(new_text) == want_sha:
                # File untouched, upstream moved: nothing of the user's is lost.
                unchanged += 1
                continue
            print(f'  ~ {label}: upstream text changed since extraction — override skipped')
            print(f'      re-extract, re-apply your edit, then run again')
            drift += 1
            continue

        old_holes = set(INTERP.findall(old_text))
        new_holes = set(INTERP.findall(new_text))
        if new_holes - old_holes:
            print(f'  ✗ {label}: introduces unknown interpolation '
                  f'{sorted(new_holes - old_holes)[:3]} — refusing, this would break at load')
            broken += 1
            continue
        if old_holes - new_holes:
            print(f'  ! {label}: drops {sorted(old_holes - new_holes)[:3]} — '
                  f'the runtime value they carried is gone from this prompt')

        edits.append((quote_at, quote, old_text, new_text, label))

    # Apply back to front so earlier offsets stay valid.
    delta = 0
    for quote_at, quote, old_text, new_text, label in sorted(edits, reverse=True):
        body, end = read_literal(src, quote_at, quote)
        src = src[:quote_at + 1] + encode(new_text, quote) + src[end:]
        d = len(new_text) - len(old_text)
        delta += d
        print(f'  ✓ {label} ({d:+d} chars)')

    out.write_text(src, encoding='utf8')
    print(f'prompt overrides: {len(edits)} applied, {unchanged} unchanged, '
          f'{drift} drifted, {missing} anchor missing, {broken} rejected '
          f'({delta:+d} chars)')
    if broken:
        sys.exit(1)


if __name__ == '__main__':
    main()

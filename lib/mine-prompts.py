#!/usr/bin/env python3
"""Mine the extracted Kimi bundle for prompt text.

The bundle is minified JavaScript, so prompts appear as ordinary string or
template literals. Finding them is a two-step job: scan out every literal,
then keep the ones that read like prose rather than like code, a path, a
regex or a blob of CSS.

Run with `--write <dir>` to emit one markdown file per prompt; without it
you get a summary only.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

BUNDLE = Path.home() / '.kimi-code-mods/.work/bundle.js'
MIN_LEN = 120

# Literals whose content is clearly not prompt text.
REJECT = re.compile(
    r'^(?:[\w./@-]+|https?://\S+|[A-Za-z0-9+/=]{80,})$'      # paths, urls, base64
    r'|^[\s\d\W]+$'                                          # punctuation/digits only
    r'|[{;}]\s*[\w-]+\s*:\s*[^;]+;'                          # css rules
    r'|\\u[0-9a-fA-F]{4}.*\\u[0-9a-fA-F]{4}.*\\u[0-9a-fA-F]{4}'
)


def scan_literals(src: str):
    """Yield (start, end, quote, body) for every string/template literal.

    A light scanner: it tracks line and block comments so their contents do
    not masquerade as strings, and skips escaped terminators. It does not
    understand regex literals, which can produce a few bogus hits — the prose
    filter removes them.
    """
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '/' and i + 1 < n:
            nxt = src[i + 1]
            if nxt == '/':
                j = src.find('\n', i)
                i = n if j < 0 else j + 1
                continue
            if nxt == '*':
                j = src.find('*/', i + 2)
                i = n if j < 0 else j + 2
                continue
        if c in '"\'`':
            j = i + 1
            while j < n:
                if src[j] == '\\':
                    j += 2
                    continue
                if src[j] == c:
                    break
                j += 1
            if j < n:
                yield i, j + 1, c, src[i + 1:j]
                i = j + 1
                continue
        i += 1


def decode(body: str) -> str:
    """Turn the raw literal into the text the model would actually see."""
    out = body
    for a, b in (('\\n', '\n'), ('\\t', '\t'), ('\\"', '"'), ("\\'", "'"),
                 ('\\`', '`'), ('\\\\', '\\')):
        out = out.replace(a, b)
    return re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), out)


def is_prose(text: str) -> bool:
    if len(text) < MIN_LEN or REJECT.search(text):
        return False
    words = re.findall(r'[A-Za-z][a-z]{2,}', text)
    if len(words) < 12:
        return False
    letters = sum(ch.isalpha() or ch.isspace() for ch in text)
    if letters / len(text) < 0.72:
        return False
    # Real prose has sentences. Minified code chunks rarely do.
    return bool(re.search(r'[a-z][.!?:](?:\s|$)', text)) or text.count('\n') >= 2


def name_for(src: str, start: int, text: str) -> str:
    """Best-effort label from the code immediately before the literal."""
    lead = src[max(0, start - 200):start]
    for pat in (r'([A-Za-z_$][\w$]{2,40})\s*[:=]\s*$',
                r'([A-Za-z_$][\w$]{2,40})\s*[:=]\s*[`"\']?\s*$',
                r'function\s+([A-Za-z_$][\w$]{2,40})[^)]*\)\s*\{?\s*return\s*$'):
        m = re.search(pat, lead)
        if m and not re.fullmatch(r'[a-z]{1,3}\d*', m.group(1)):
            return m.group(1)
    # Fall back to the first meaningful words of the prompt itself.
    head = re.sub(r'[^A-Za-z0-9 ]+', ' ', text[:70]).split()
    return '-'.join(head[:6]).lower() or 'unnamed'


def slug(s: str) -> str:
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^A-Za-z0-9]+', '-', s).strip('-').lower()
    return (s or 'prompt')[:70]


def classify(text: str) -> str:
    t = text.lower()
    if '<system-reminder>' in t or 'system-reminder' in t:
        return 'system-reminder'
    if re.search(r'\byou are (?:kimi|an?\b|the\b)', t):
        return 'system-prompt'
    if re.search(r'^\s*(?:use this tool|launch|reads?|writes?|executes?|performs?) ', t):
        return 'tool-description'
    if 'skill' in t[:200] and ('---' in t[:20] or 'name:' in t[:120]):
        return 'skill'
    if re.search(r'\b(?:you should|you must|do not|never|always)\b', t):
        return 'instruction'
    return 'text'


def main():
    src = BUNDLE.read_text(encoding='utf8', errors='replace')
    print(f'bundle: {len(src) / 1e6:.1f} MB')

    seen, found = {}, []
    for start, end, quote, body in scan_literals(src):
        if len(body) < MIN_LEN:
            continue
        text = decode(body)
        if not is_prose(text):
            continue
        key = text.strip()
        if key in seen:
            seen[key]['count'] += 1
            continue
        rec = {'offset': start, 'quote': quote, 'text': text,
               'name': name_for(src, start, text), 'kind': classify(text),
               'len': len(text), 'count': 1}
        seen[key] = rec
        found.append(rec)

    found.sort(key=lambda r: -r['len'])
    by_kind = {}
    for r in found:
        by_kind.setdefault(r['kind'], []).append(r)

    print(f'prompt-like literals: {len(found)} unique, '
          f'{sum(r["len"] for r in found) / 1000:.0f}k chars total\n')
    for kind in sorted(by_kind, key=lambda k: -sum(r['len'] for r in by_kind[k])):
        rs = by_kind[kind]
        print(f'  {kind:<18} {len(rs):>4} literals, {sum(r["len"] for r in rs) / 1000:>6.1f}k chars')

    print('\nlargest 20:')
    for r in found[:20]:
        head = ' '.join(r['text'].split())[:78]
        print(f'  [{r["kind"]:<16}] {r["len"]:>6}  {r["name"][:28]:<28} {head}')

    if '--write' in sys.argv:
        out = Path(sys.argv[sys.argv.index('--write') + 1])
        out.mkdir(parents=True, exist_ok=True)
        version = json.loads((BUNDLE.parent / 'meta.json').read_text()).get('code_path', '')
        used = set()
        for r in found:
            base = f'{r["kind"]}-{slug(r["name"])}'
            name, k = base, 2
            while name in used:
                name, k = f'{base}-{k}', k + 1
            used.add(name)
            head = ' '.join(r['text'].split())[:100]
            (out / f'{name}.md').write_text(
                '<!--\n'
                f'name: {r["name"]}\n'
                f'kind: {r["kind"]}\n'
                f'description: {head}\n'
                f'bundleOffset: {r["offset"]}\n'
                f'length: {r["len"]}\n'
                f'occurrences: {r["count"]}\n'
                f'quote: {r["quote"]}\n'
                f'source: {version}\n'
                '-->\n' + r['text'] + '\n')
        print(f'\nwrote {len(found)} files to {out}')


if __name__ == '__main__':
    main()

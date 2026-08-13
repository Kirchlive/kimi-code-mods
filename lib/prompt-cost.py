#!/usr/bin/env python3
"""What the prompt apparatus costs, and what trimming it has bought so far.

Every prompt Kimi ships is paid for on every turn it is included in, so the
useful question is not "how long is this file" but "where would cutting
actually help". This report answers that in three passes: the total split by
engine generation and category, the most expensive individual prompts, and the
saving each override has produced against the pristine text it replaced.

The original length is not recomputed from the binary — it is recorded in each
file's `chars` header at extraction time, so the report works on the prompt
tree alone and stays correct after the binary has been patched.

Token counts are ESTIMATES. Kimi's tokeniser is not available here, and pulling
in a third-party one would be a dependency for a number nobody acts on to the
digit. The divisor is 3.7 characters per token, which is the usual range for
English prose with markdown punctuation; treat the figures as a way to compare
prompts against each other, not as a billing statement.

usage: prompt-cost.py <prompt-dir> [--top N] [--json] [--selfcheck]
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oscruft import usable_files

CHARS_PER_TOKEN = 3.7


def tokens(chars: int) -> int:
    return round(chars / CHARS_PER_TOKEN)


def parse_header(raw: str):
    """Split a prompt file into its header fields and its text."""
    if not raw.startswith('<!--\n'):
        return {}, raw
    end = raw.find('\n-->\n')
    if end < 0:
        return {}, raw
    head = {}
    for line in raw[5:end].splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            head[k.strip()] = v.strip()
    return head, raw[end + 5:]


def generation(rel: str) -> str:
    if rel.startswith('inline/'):
        return 'inline'
    if 'agent-core-v2' in rel:
        return 'v2'
    if 'agent-core' in rel:
        return 'v1'
    return 'other'


def category(rel: str) -> str:
    """Group by what the prompt is for, not where the bundler put it."""
    if rel.startswith('inline/'):
        return 'inline constants'
    tail = rel.split('/src/', 1)[1] if '/src/' in rel else rel
    if tail.startswith(('tools/', 'agent/tools/')):
        return 'tool descriptions'
    if tail.startswith(('skill/', 'app/skillCatalog')):
        return 'skills'
    if tail.startswith(('profile/', 'app/agentProfileCatalog')):
        return 'system prompt + profiles'
    return 'other prompts'


def collect(promptdir: Path):
    """One record per prompt file: what it weighs now, and what it weighed."""
    rows = []
    for p in usable_files(promptdir):
        head, body = parse_header(p.read_text(encoding='utf8', errors='replace'))
        rel = str(p.relative_to(promptdir))
        # Reconstruct exactly what the applier would write back, so an
        # untouched file shows a saving of zero rather than a stray newline.
        trailing = int(head.get('trailingNewlines', '0') or 0)
        current = len(body.rstrip('\n')) + trailing
        try:
            original = int(head.get('chars', current))
        except ValueError:
            original = current
        rows.append({
            'file': rel,
            'module': head.get('module', ''),
            'generation': generation(rel),
            'category': category(rel),
            'current_chars': current,
            'original_chars': original,
            'saved_chars': original - current,
        })
    return rows


def _table(title, keyfn, rows, indent='  '):
    groups = {}
    for r in rows:
        groups.setdefault(keyfn(r), []).append(r)
    print(f'\n{title}')
    print(f'{indent}{"":<28} {"files":>5} {"chars":>9} {"~tokens":>9} {"saved":>9}')
    for key in sorted(groups, key=lambda k: -sum(r['current_chars'] for r in groups[k])):
        g = groups[key]
        c = sum(r['current_chars'] for r in g)
        s = sum(r['saved_chars'] for r in g)
        saved = f'{tokens(s):>9}' if s else f'{"-":>9}'
        print(f'{indent}{key:<28} {len(g):>5} {c:>9} {tokens(c):>9} {saved}')
    c = sum(r['current_chars'] for r in rows)
    s = sum(r['saved_chars'] for r in rows)
    print(f'{indent}{"TOTAL":<28} {len(rows):>5} {c:>9} {tokens(c):>9} '
          f'{tokens(s) if s else "-":>9}')


def report(promptdir: Path, top: int):
    rows = collect(promptdir)
    if not rows:
        print(f'no prompt files under {promptdir}')
        return rows

    print(f'prompt cost report for {promptdir}')
    print(f'token figures are estimates at {CHARS_PER_TOKEN} characters per token')

    _table('by engine generation:', lambda r: r['generation'], rows)
    _table('by category:', lambda r: r['category'], rows)

    print(f'\nmost expensive prompts (top {top}):')
    print(f'  {"~tokens":>8} {"saved":>7}  file')
    for r in sorted(rows, key=lambda r: -r['current_chars'])[:top]:
        saved = f'{tokens(r["saved_chars"]):>7}' if r['saved_chars'] else f'{"-":>7}'
        print(f'  {tokens(r["current_chars"]):>8} {saved}  {r["file"]}')

    edited = [r for r in rows if r['saved_chars'] != 0]
    print('\noverrides with a measurable effect:')
    if not edited:
        print('  none — every prompt still matches the text extracted from the binary')
    else:
        print(f'  {"~tokens":>8} {"was":>8} {"now":>8} {"cut":>8}  file')
        for r in sorted(edited, key=lambda r: -abs(r['saved_chars'])):
            pct = 100.0 * r['saved_chars'] / r['original_chars'] if r['original_chars'] else 0
            print(f'  {tokens(r["saved_chars"]):>8} {r["original_chars"]:>8} '
                  f'{r["current_chars"]:>8} {pct:>7.1f}%  {r["file"]}')
        total = sum(r['saved_chars'] for r in edited)
        orig = sum(r['original_chars'] for r in rows)
        print(f'  saved {total} characters, about {tokens(total)} tokens '
              f'({100.0 * total / orig:.1f}% of the pristine total)')

    v1 = sum(r['current_chars'] for r in rows if r['generation'] == 'v1')
    v2 = sum(r['current_chars'] for r in rows if r['generation'] == 'v2')
    if v1 and v2:
        print(f'\nNote: the binary carries both engine generations, and only the one the '
              f'running\nprofile loads is actually sent. About {tokens(min(v1, v2))} of the '
              f'{tokens(v1 + v2)} tokens above are\ntherefore likely dead weight — but which '
              f'half depends on which generation is live,\nso nothing here assumes an answer.')
    return rows


def selfcheck():
    """Aggregation and savings arithmetic, on synthetic files."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        def make(rel, original, text, trailing=0):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f'<!--\nmodule: m\nchars: {original}\n'
                         f'trailingNewlines: {trailing}\n-->\n{text}\n', encoding='utf8')

        # Untouched: header length equals the body length, so saving is zero.
        make('packages/agent-core/src/tools/builtin/a.plain.md', 10, 'abcdefghij')
        # Trimmed by 5 characters.
        make('packages/agent-core-v2/src/agent/tools/b.plain.md', 15, 'abcdefghij')
        # A skill that grew by 2.
        make('packages/agent-core/src/skill/builtin/c.plain.md', 8, 'abcdefghij')
        # Inline constant with a trailing newline recorded in the header.
        make('inline/D.plain.md', 11, 'abcdefghij', trailing=1)
        (root / '.DS_Store').write_bytes(b'\x00')

        rows = collect(root)
        by = {r['file'].split('/')[-1]: r for r in rows}

        assert len(rows) == 4, f'os cruft leaked in: {len(rows)} rows'
        assert by['a.plain.md']['saved_chars'] == 0
        assert by['b.plain.md']['saved_chars'] == 5
        assert by['c.plain.md']['saved_chars'] == -2, 'growth must show as a negative saving'
        assert by['D.plain.md']['current_chars'] == 11, 'trailing newline must be counted'
        assert by['D.plain.md']['saved_chars'] == 0

        assert by['a.plain.md']['generation'] == 'v1'
        assert by['b.plain.md']['generation'] == 'v2'
        assert by['D.plain.md']['generation'] == 'inline'
        assert by['a.plain.md']['category'] == 'tool descriptions'
        assert by['b.plain.md']['category'] == 'tool descriptions'
        assert by['c.plain.md']['category'] == 'skills'
        assert by['D.plain.md']['category'] == 'inline constants'

        assert sum(r['current_chars'] for r in rows) == 41
        assert sum(r['saved_chars'] for r in rows) == 3
        assert tokens(37) == 10, tokens(37)

    print('prompt-cost selfcheck: ok')


def main():
    args = sys.argv[1:]
    if '--selfcheck' in args:
        selfcheck()
        return
    positional = [a for a in args if not a.startswith('--')]
    if not positional:
        print(__doc__)
        sys.exit(2)
    promptdir = Path(positional[0])
    if not promptdir.is_dir():
        print(f'not a directory: {promptdir}', file=sys.stderr)
        sys.exit(1)

    top = 15
    if '--top' in args:
        try:
            top = int(args[args.index('--top') + 1])
        except (IndexError, ValueError):
            print('--top needs a number', file=sys.stderr)
            sys.exit(2)

    if '--json' in args:
        rows = collect(promptdir)
        print(json.dumps({
            'charsPerToken': CHARS_PER_TOKEN,
            'totals': {
                'files': len(rows),
                'currentChars': sum(r['current_chars'] for r in rows),
                'originalChars': sum(r['original_chars'] for r in rows),
                'savedChars': sum(r['saved_chars'] for r in rows),
                'estimatedTokens': tokens(sum(r['current_chars'] for r in rows)),
            },
            'prompts': sorted(rows, key=lambda r: -r['current_chars']),
        }, indent=2))
        return

    report(promptdir, top)


if __name__ == '__main__':
    main()

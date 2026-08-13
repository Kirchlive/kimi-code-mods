#!/usr/bin/env python3
"""List Kimi's builtin tools with what each one costs in the prompt.

Every builtin tool ships its description in the top-level `tools[]` array of
every request, so an unused tool is a fixed per-turn tax. Kimi supports turning
them off through the global `[tools]` section of config.toml — no patching
involved — and this prints the names to put there together with the saving.

    python3 lib/list-tools.py                     # table, largest first
    python3 lib/list-tools.py --toml Cron Web     # ready-to-paste config block

Names are read out of the bundle rather than hardcoded, so a Kimi release that
renames or adds a tool shows up here instead of turning into a silently
ineffective config entry.
"""

import re
import sys
from pathlib import Path

BUNDLE = Path(__file__).parent.parent / '.work' / 'bundle.js'
PROMPTS = Path(__file__).parent.parent / 'system-prompts'

# Tools whose removal breaks Kimi rather than trimming it. Bash is fetched by
# name for shell execution (`builtinTools.get("Bash")`), the file tools are how
# the agent does anything at all, and the three Task* tools jointly gate
# background execution (`allowBackground`).
PROTECTED = {'Bash', 'Read', 'Write', 'Edit', 'Grep', 'Glob',
             'TaskList', 'TaskOutput', 'TaskStop'}

CHARS_PER_TOKEN = 3.7


def tool_names(src: str) -> list[str]:
    """Class names instantiated in initializeBuiltinTools, mapped to wire names."""
    i = src.find('this.builtinTools = new Map([')
    if i < 0:
        raise SystemExit('could not find initializeBuiltinTools — the bundle shape changed')
    block = src[i:i + 3200]
    classes = sorted(set(re.findall(r'new ([A-Za-z_$][\w$]*Tool[\w$]*)\s*\(', block)))
    names = []
    for cls in classes:
        m = re.search(re.escape(cls) + r'\s*=\s*class\b', src) or \
            re.search(r'class\s+' + re.escape(cls) + r'\b', src)
        if not m:
            continue
        nm = re.search(r'\bname\s*=\s*"([^"]+)"', src[m.start():m.start() + 1200])
        if nm:
            names.append(nm.group(1))
    return sorted(set(names))


# Where the wire name and the source file name disagree.
ALIASES = {'readmediafile': 'readmedia'}


def description_sizes() -> dict[str, int]:
    """Map a tool name to the size of its description, from the extracted prompts.

    The prompt files are named after their source file (`cron-create.plain.md`),
    so the mapping is by normalised name.
    """
    sizes = {}
    if not PROMPTS.is_dir():
        return sizes
    for p in PROMPTS.rglob('*.md'):
        if p.name.startswith('._'):
            continue
        rel = str(p)
        if '/tools/' not in rel and '/builtin/file' not in rel and '/builtin/shell' not in rel:
            continue
        stem = p.name.split('.')[0]                     # cron-create.plain.md -> cron-create
        key = stem.replace('-', '').replace('_', '').lower()
        body = p.read_text(errors='replace').split('-->\n', 1)[-1]
        sizes[key] = max(sizes.get(key, 0), len(body))  # v1/v2 twins: take the larger
    return sizes


def main():
    src = BUNDLE.read_text(errors='replace')
    names = tool_names(src)
    sizes = description_sizes()

    rows = []
    for n in names:
        key = n.replace('-', '').replace('_', '').lower()
        key = ALIASES.get(key, key)
        chars = sizes.get(key, 0)
        rows.append((n, chars, round(chars / CHARS_PER_TOKEN)))

    if '--toml' in sys.argv:
        wanted = sys.argv[sys.argv.index('--toml') + 1:]
        picked = [n for n, _, _ in rows
                  if any(w.lower() in n.lower() for w in wanted) and n not in PROTECTED]
        saved = sum(t for n, _, t in rows if n in picked)
        print('# Add to ~/.kimi-code/config.toml — no patching needed.')
        print(f'# Removes {len(picked)} tools from every request, about {saved} tokens per turn.')
        print('[tools]')
        print('disabled = [' + ', '.join(f'"{n}"' for n in picked) + ']')
        skipped = [n for n, _, _ in rows
                   if any(w.lower() in n.lower() for w in wanted) and n in PROTECTED]
        if skipped:
            print(f'# refused as load-bearing: {", ".join(skipped)}')
        return

    rows.sort(key=lambda r: -r[2])
    total = sum(t for _, _, t in rows)
    known = sum(1 for _, c, _ in rows if c)
    print(f'{len(rows)} builtin tools, {known} with a description found in system-prompts/')
    print(f'about {total} tokens of tool descriptions per request\n')
    print(f'{"tool":<20}{"~tokens":>9}   note')
    for n, chars, t in rows:
        note = 'load-bearing, keep' if n in PROTECTED else ('' if chars else 'no description file found')
        print(f'  {n:<18}{t:>9}   {note}')
    print('\nDisable what you do not use, in ~/.kimi-code/config.toml:')
    print('  [tools]')
    print('  disabled = ["CronCreate", "CronList", "CronDelete"]')
    print('\nGenerate a block:  python3 lib/list-tools.py --toml Cron')


if __name__ == '__main__':
    main()

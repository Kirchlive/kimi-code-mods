#!/usr/bin/env python3
"""Carry prompt overrides across a Kimi update.

`apply-prompt-overrides.py` refuses an override whose recorded fingerprint no
longer matches the prompt in the bundle: upstream rewrote the text, so the
override was written against something that no longer exists. Refusing is the
right call — forcing it would silently throw away whatever Moonshot changed —
but it leaves the edit stranded. This tool unstrands it by merging.

**Where the base comes from.** A three-way merge needs the *old pristine* text,
and the header records only its hash, which cannot be inverted. Two facts turn
that into a non-problem, with no discipline required of anyone:

  * A file you never edited needs no base at all. Its body still hashes to the
    recorded `originSha256`, which proves it is pristine, so the merge reduces
    to "take the new version".
  * A file upstream never touched needs no base either. Both headers carry the
    hash of their own pristine text, so comparing the two says whether the
    prompt moved at all; if it did not, the edit simply carries over.
  * Only a file that *both* sides changed needs a real ancestor — and the old
    pristine text is still on disk, inside `baseline/kimi-<old-version>`, the
    very binary the tree was extracted from. The patcher stores baselines per
    version and never deletes them, so the base is recoverable after the fact.
    Point `--base` at that binary (or at a pristine tree) and it is extracted
    on the spot.

The recovered base is checked against the recorded hash before it is used, so
pointing `--base` at the wrong version is caught rather than merged against.

**Conflicts never reach the binary.** A conflicted merge is written beside the
prompt as `<name>.md.conflict`, which the applier's `*.md` glob does not match,
while the `.md` itself is left at the new upstream text. Nothing half-merged
can be patched in. Resolving means editing the `.conflict` file and renaming it
over the `.md`.

usage: migrate-prompts.py <old-tree> <new-tree> <out-tree> [--base <tree|binary>] [--dry-run]
       migrate-prompts.py --selfcheck
"""

import difflib
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oscruft import usable_files

CONFLICT_SUFFIX = '.conflict'


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf8')).hexdigest()[:16]


# ------------------------------------------------------------------ prompt files

def split_file(raw: str):
    """Return (header dict, verbatim header block, body)."""
    if not raw.startswith('<!--\n'):
        return None, '', raw
    end = raw.find('\n-->\n')
    if end < 0:
        return None, '', raw
    head = {}
    for line in raw[5:end].splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            head[k.strip()] = v.strip()
    return head, raw[:end + 5], raw[end + 5:]


def body_text(head: dict, body: str) -> str:
    """The prompt as the applier will reconstruct it.

    Editors add a trailing newline and the extractor writes one of its own;
    neither counts as an edit, so the original's trailing newlines are restored
    from the header before anything is compared or hashed.
    """
    return body.rstrip('\n') + '\n' * int(head.get('trailingNewlines', 0) or 0)


def key_of(head: dict, rel: Path) -> tuple:
    """A handle that survives the file being renamed between versions.

    The upstream source path is the stable name — the same anchor the applier
    trusts. Inline constants have no source file, so they fall back to their
    constant name with the bundler's `$N` disambiguator stripped, since that
    suffix is an artefact of how the bundle was assembled, not a real name.
    """
    source = head.get('source', '')
    variant = head.get('variant', '')
    if source and not source.startswith('inline constant'):
        return ('source', source, variant)
    module = re.sub(r'\$\d+$', '', head.get('module', ''))
    if module:
        return ('module', module, variant)
    return ('path', str(rel), variant)


def load_tree(root: Path) -> dict:
    """key -> (relative path, header, header block, normalised body)."""
    out = {}
    for p in usable_files(root):
        head, block, body = split_file(p.read_text(encoding='utf8', errors='replace'))
        rel = p.relative_to(root)
        if head is None:
            print(f'  ! {rel}: no header — ignored')
            continue
        out[key_of(head, rel)] = (rel, head, block, body_text(head, body))
    return out


# ------------------------------------------------------------------ three-way merge

def _edits(base: list, other: list):
    """Regions of `base` that `other` replaces, as (start, end, replacement)."""
    ops = difflib.SequenceMatcher(None, base, other, autojunk=False).get_opcodes()
    return [(i1, i2, other[j1:j2]) for tag, i1, i2, j1, j2 in ops if tag != 'equal']


def _rebuild(base: list, lo: int, hi: int, edits: list) -> list:
    """How one side sees base[lo:hi] after its own edits."""
    out, cur = [], lo
    for start, end, replacement in edits:
        out.extend(base[cur:start])
        out.extend(replacement)
        cur = end
    out.extend(base[cur:hi])
    return out


def _terminated(lines: list) -> list:
    """Conflict markers must start on their own line."""
    if lines and not lines[-1].endswith('\n'):
        return lines[:-1] + [lines[-1] + '\n']
    return lines


def merge3(base_text: str, our_text: str, their_text: str,
           ours_label: str = 'yours', theirs_label: str = 'upstream'):
    """Line-wise three-way merge. Returns (text, conflict count).

    Disjoint edits both survive; identical edits collapse to one; edits that
    touch the same region become a conflict rather than a guess.
    """
    base = base_text.splitlines(keepends=True)
    ours = our_text.splitlines(keepends=True)
    theirs = their_text.splitlines(keepends=True)

    e_ours, e_theirs = _edits(base, ours), _edits(base, theirs)
    out, conflicts = [], 0
    pos = io = it = 0

    while io < len(e_ours) or it < len(e_theirs):
        next_ours = e_ours[io][0] if io < len(e_ours) else len(base) + 1
        next_theirs = e_theirs[it][0] if it < len(e_theirs) else len(base) + 1
        start = min(next_ours, next_theirs)
        out.extend(base[pos:start])

        # Grow the region until neither side has another edit touching it, so
        # two edits that overlap are judged together rather than interleaved.
        lo = hi = start
        group_ours, group_theirs = [], []
        growing = True
        while growing:
            growing = False
            while io < len(e_ours) and e_ours[io][0] <= hi:
                hi = max(hi, e_ours[io][1])
                group_ours.append(e_ours[io])
                io += 1
                growing = True
            while it < len(e_theirs) and e_theirs[it][0] <= hi:
                hi = max(hi, e_theirs[it][1])
                group_theirs.append(e_theirs[it])
                it += 1
                growing = True

        side_ours = _rebuild(base, lo, hi, group_ours)
        side_theirs = _rebuild(base, lo, hi, group_theirs)

        if not group_ours:
            out.extend(side_theirs)
        elif not group_theirs:
            out.extend(side_ours)
        elif side_ours == side_theirs:
            out.extend(side_ours)
        else:
            conflicts += 1
            out = _terminated(out)
            out.append(f'<<<<<<< {ours_label}\n')
            out.extend(_terminated(side_ours))
            out.append('||||||| base\n')
            out.extend(_terminated(base[lo:hi]))
            out.append('=======\n')
            out.extend(_terminated(side_theirs))
            out.append(f'>>>>>>> {theirs_label}\n')
        pos = hi

    out.extend(base[pos:])
    return ''.join(out), conflicts


# ------------------------------------------------------------------ base recovery

def tree_from_binary(binary: Path, workdir: Path) -> Path:
    """Extract a pristine prompt tree straight out of a Kimi binary."""
    lib = Path(__file__).parent
    bundle, meta = workdir / 'bundle.js', workdir / 'meta.json'
    subprocess.run([sys.executable, str(lib / 'sea.py'), 'extract',
                    str(binary), str(bundle), str(meta)],
                   check=True, capture_output=True, text=True)
    tree = workdir / 'pristine'
    subprocess.run([sys.executable, str(lib / 'extract-prompts.py'), str(bundle), str(tree)],
                   check=True, capture_output=True, text=True)
    return tree


# ------------------------------------------------------------------ migration

def migrate(old_root: Path, new_root: Path, out_root: Path,
            base_root: Path | None = None, dry_run: bool = False) -> int:
    old = load_tree(old_root)
    new = load_tree(new_root)
    base = load_tree(base_root) if base_root else {}

    counts = dict(merged=0, kept=0, pristine=0, conflict=0, added=0, dropped=0, nobase=0)
    conflict_paths = []

    for key, (rel, head, block, new_body) in sorted(new.items(), key=lambda kv: str(kv[1][0])):
        dest = out_root / rel
        old_entry = old.get(key)

        if old_entry is None:
            _write(dest, block + new_body, dry_run)
            counts['added'] += 1
            print(f'  + {rel}: new upstream prompt')
            continue

        _, old_head, _, old_body = old_entry
        edited = sha(old_body) != old_head.get('originSha256', '')

        if not edited:
            _write(dest, block + new_body, dry_run)
            counts['pristine'] += 1
            continue

        # Both headers record the hash of their own pristine text, so comparing
        # them says whether upstream touched this prompt at all — without
        # needing the base. When it did not, the edit carries over verbatim and
        # there is nothing to merge.
        if old_head.get('originSha256', '') == head.get('originSha256', 'x'):
            _write(dest, block + old_body, dry_run)
            counts['kept'] += 1
            print(f'  = {rel}: your edit carried over, upstream unchanged')
            continue

        base_entry = base.get(key)
        base_body = base_entry[3] if base_entry else None
        # Only a base that matches the hash the override was written against can
        # be trusted; anything else would merge against the wrong ancestor.
        if base_body is None or sha(base_body) != old_head.get('originSha256', ''):
            _write(dest, block + new_body, dry_run)
            _write(dest.with_name(dest.name + CONFLICT_SUFFIX),
                   block + _two_way(old_body, new_body), dry_run)
            counts['nobase'] += 1
            conflict_paths.append(rel)
            why = 'no base available' if base_body is None else 'base does not match the recorded hash'
            print(f'  ✗ {rel}: {why} — needs manual resolution')
            continue

        merged, conflicts = merge3(base_body, old_body, new_body)
        if conflicts:
            _write(dest, block + new_body, dry_run)
            _write(dest.with_name(dest.name + CONFLICT_SUFFIX), block + merged, dry_run)
            counts['conflict'] += 1
            conflict_paths.append(rel)
            print(f'  ✗ {rel}: {conflicts} conflict(s) — resolve {rel.name}{CONFLICT_SUFFIX}')
        else:
            _write(dest, block + merged, dry_run)
            counts['merged'] += 1
            print(f'  ✓ {rel}: merged your edit into the new text')

    for key, (rel, head, _, old_body) in sorted(old.items(), key=lambda kv: str(kv[1][0])):
        if key in new:
            continue
        counts['dropped'] += 1
        edited = sha(old_body) != head.get('originSha256', '')
        note = ' — it carried an edit, which is now gone' if edited else ''
        print(f'  − {rel}: removed upstream{note}')

    total_conflicts = counts['conflict'] + counts['nobase']
    print(f"\nmigration: {counts['merged']} merged, {counts['kept']} kept, "
          f"{counts['pristine']} taken from upstream, {counts['added']} added, "
          f"{counts['dropped']} dropped, {total_conflicts} need resolving"
          + (' (dry run, nothing written)' if dry_run else ''))

    if conflict_paths:
        print(f'\nresolve each of these, then rename the .conflict file over the .md:')
        for rel in conflict_paths[:20]:
            print(f'  {out_root / rel}{CONFLICT_SUFFIX}')
        if len(conflict_paths) > 20:
            print(f'  … and {len(conflict_paths) - 20} more')
    return total_conflicts


def _two_way(ours: str, theirs: str) -> str:
    """A conflict block for the case where no ancestor could be recovered."""
    out = ['<<<<<<< yours\n']
    out.extend(_terminated(ours.splitlines(keepends=True)))
    out.append('=======\n')
    out.extend(_terminated(theirs.splitlines(keepends=True)))
    out.append('>>>>>>> upstream\n')
    return ''.join(out)


def _write(dest: Path, text: str, dry_run: bool):
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding='utf8')


# ------------------------------------------------------------------ selfcheck

HEADER = ('<!--\n'
          'source: ../../packages/demo/src/{name}.md\n'
          'module: {name}_default\n'
          'variant: plain\n'
          'chars: {chars}\n'
          'originSha256: {sha}\n'
          'trailingNewlines: 0\n'
          'bundleOffset: 0\n'
          '-->\n')


def _prompt_file(root: Path, name: str, origin: str, body: str):
    p = root / f'{name}.plain.md'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(HEADER.format(name=name, chars=len(origin), sha=sha(origin)) + body + '\n',
                 encoding='utf8')
    return p


def _selfcheck():
    from oscruft import usable_files as _usable

    original = 'Line one.\nLine two.\nLine three.\nLine four.\nLine five.'

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        old, new, basedir, out = td / 'old', td / 'new', td / 'base', td / 'out'

        # base: the pristine old text, for every case
        for name in ('clean', 'untouched', 'clash', 'ours-only'):
            _prompt_file(basedir, name, original, original)

        # 0. ours-only: we edited, upstream did not touch it at all
        ours_only = original.replace('Line four.', 'Line four, mine alone.')
        _prompt_file(old, 'ours-only', original, ours_only)
        _prompt_file(new, 'ours-only', original, original)

        # 1. clean: we changed the first line, upstream changed the last
        ours_clean = original.replace('Line one.', 'Line one, edited by me.')
        theirs_clean = original.replace('Line five.', 'Line five, rewritten upstream.')
        _prompt_file(old, 'clean', original, ours_clean)
        _prompt_file(new, 'clean', theirs_clean, theirs_clean)

        # 2. untouched: we never edited it, upstream moved
        theirs_untouched = original.replace('Line three.', 'Line three, upstream.')
        _prompt_file(old, 'untouched', original, original)
        _prompt_file(new, 'untouched', theirs_untouched, theirs_untouched)

        # 3. clash: both rewrote the same line
        ours_clash = original.replace('Line two.', 'Line two, my way.')
        theirs_clash = original.replace('Line two.', 'Line two, their way.')
        _prompt_file(old, 'clash', original, ours_clash)
        _prompt_file(new, 'clash', theirs_clash, theirs_clash)

        conflicts = migrate(old, new, out, basedir)

        merged = (out / 'clean.plain.md').read_text()
        assert 'Line one, edited by me.' in merged, 'our edit was lost in a clean merge'
        assert 'Line five, rewritten upstream.' in merged, 'upstream change was lost'
        assert sha(theirs_clean) in merged, 'merged file must carry the new header hash'

        untouched = (out / 'untouched.plain.md').read_text()
        assert 'Line three, upstream.' in untouched, 'unedited file should follow upstream'
        assert not (out / f'untouched.plain.md{CONFLICT_SUFFIX}').exists()

        assert conflicts == 1, f'expected exactly one conflict, got {conflicts}'
        clash_md = (out / 'clash.plain.md').read_text()
        assert 'Line two, their way.' in clash_md and '<<<<<<<' not in clash_md, \
            'the .md must stay clean and appliable'
        clash_conflict = out / f'clash.plain.md{CONFLICT_SUFFIX}'
        assert clash_conflict.exists(), 'conflict file missing'
        text = clash_conflict.read_text()
        for marker in ('<<<<<<< yours', '||||||| base', '=======', '>>>>>>> upstream'):
            assert marker in text, f'missing conflict marker {marker!r}'

        # The real guard: the applier globs *.md, so a conflict file is invisible.
        names = {p.name for p in _usable(out)}
        assert f'clash.plain.md{CONFLICT_SUFFIX}' not in names, \
            'conflict file must not be picked up as an override'
        assert 'clash.plain.md' in names

        ours_only_out = (out / 'ours-only.plain.md').read_text()
        assert 'Line four, mine alone.' in ours_only_out, \
            'an edit upstream never touched must carry over untouched'

        # Without a base, only the files upstream also rewrote can conflict —
        # an edit upstream left alone still needs no ancestor.
        out2 = td / 'out2'
        c2 = migrate(old, new, out2, None)
        assert c2 == 2, f'expected the two contested files to need resolving, got {c2}'
        assert (out2 / f'clean.plain.md{CONFLICT_SUFFIX}').exists()
        assert '<<<<<<< yours' in (out2 / f'clean.plain.md{CONFLICT_SUFFIX}').read_text()
        assert not (out2 / f'ours-only.plain.md{CONFLICT_SUFFIX}').exists(), \
            'a base should not be needed when only we changed the file'
        assert 'Line four, mine alone.' in (out2 / 'ours-only.plain.md').read_text()

        # A dry run must leave the filesystem alone.
        out3 = td / 'out3'
        migrate(old, new, out3, basedir, dry_run=True)
        assert not out3.exists() or not list(out3.rglob('*')), 'dry run wrote files'

    print('migrate-prompts selfcheck: clean merge, unchanged pickup and conflict all behave')


# ------------------------------------------------------------------ entry point

def main():
    args = [a for a in sys.argv[1:]]
    if '--selfcheck' in args:
        _selfcheck()
        return

    dry_run = '--dry-run' in args
    args = [a for a in args if a != '--dry-run']

    base = None
    if '--base' in args:
        i = args.index('--base')
        base = Path(args[i + 1]).expanduser()
        del args[i:i + 2]

    if len(args) != 3:
        print(__doc__)
        sys.exit(2)

    old_root, new_root, out_root = (Path(a).expanduser() for a in args)
    for p in (old_root, new_root):
        if not p.is_dir():
            print(f'ERROR: not a directory: {p}', file=sys.stderr)
            sys.exit(2)

    tmp = None
    try:
        if base is not None and not base.is_dir():
            if not base.exists():
                print(f'ERROR: --base does not exist: {base}', file=sys.stderr)
                sys.exit(2)
            tmp = tempfile.mkdtemp(prefix='tweakkimi-base-')
            print(f'recovering the old pristine prompts from {base.name} …')
            base = tree_from_binary(base, Path(tmp))
        conflicts = migrate(old_root, new_root, out_root, base, dry_run)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    sys.exit(1 if conflicts else 0)


if __name__ == '__main__':
    main()

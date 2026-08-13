"""Is this file an operating-system dropping rather than input?

Patterns come from lib/os-cruft.txt, the single list shared by the shell, the
JavaScript patch runner and the Python tools here.
"""

from fnmatch import fnmatch
from pathlib import Path

PATTERNS = [p for p in
            (line.split('#')[0].strip()
             for line in (Path(__file__).parent / 'os-cruft.txt').read_text().splitlines())
            if p]


def is_os_cruft(name: str) -> bool:
    """Match against the file name only, case-insensitively."""
    low = name.lower()
    return any(fnmatch(low, p.lower()) for p in PATTERNS)


def usable_files(root: Path, glob: str = '*.md'):
    """Every input file under `root`, with OS files left out."""
    return sorted(p for p in root.rglob(glob) if not is_os_cruft(p.name))


def _selfcheck():
    assert is_os_cruft('.DS_Store')
    assert is_os_cruft('._system.md'), 'AppleDouble sidecar must be excluded'
    assert is_os_cruft('Thumbs.db') and is_os_cruft('thumbs.db')
    assert is_os_cruft('.Trash-1000') and is_os_cruft('.nfs0001')
    assert not is_os_cruft('system.md')
    assert not is_os_cruft('00-banner.js')
    assert not is_os_cruft('read.mustache.md')
    print(f'oscruft selfcheck: ok ({len(PATTERNS)} patterns)')


if __name__ == '__main__':
    _selfcheck()

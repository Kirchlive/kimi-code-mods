#!/usr/bin/env python3
"""Extract and repack the Node SEA payload of a Mach-O binary.

Kimi Code ships as a Node.js Single Executable Application: the whole bundle
sits as plain UTF-8 JavaScript inside a `NODE_SEA,__NODE_SEA_BLOB` section.
That is simpler than Bun's module directory (tweakcc has to resolve an entry
module by name), but it comes with two constraints Bun does not have:

  * the binary is Developer-ID signed with a hardened runtime, so any edit
    makes macOS SIGKILL it until it is re-signed;
  * growing the payload means moving __LINKEDIT, which every remaining load
    command points into.

Both are handled here. Growth is always rounded up to a page so the delta
applies uniformly to every file offset and vm address after the segment.
"""

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

PAGE = 0x1000
SEG_NODE_SEA = 'NODE_SEA'
SEG_LINKEDIT = '__LINKEDIT'

LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB
LC_DYLD_INFO_ONLY = 0x80000022
LC_FUNCTION_STARTS = 0x26
LC_DATA_IN_CODE = 0x29
LC_CODE_SIGNATURE = 0x1D
LC_DYLD_EXPORTS_TRIE = 0x80000033
LC_DYLD_CHAINED_FIXUPS = 0x80000034
LC_LINKER_OPTIMIZATION_HINT = 0x2E

# Load commands whose payload lives in __LINKEDIT, as (command, [u32 offsets
# into the command body that hold a file offset]). Sizes stay untouched;
# only positions move.
LINKEDIT_POINTERS = {
    LC_SYMTAB: [0, 8],                     # symoff, stroff
    LC_DYSYMTAB: [48, 56, 64],             # indirectsymoff, extreloff, locreloff
    LC_DYLD_INFO_ONLY: [0, 8, 16, 24, 32],  # rebase, bind, weak, lazy, export
    LC_FUNCTION_STARTS: [0],
    LC_DATA_IN_CODE: [0],
    LC_CODE_SIGNATURE: [0],
    LC_DYLD_EXPORTS_TRIE: [0],
    LC_DYLD_CHAINED_FIXUPS: [0],
    LC_LINKER_OPTIMIZATION_HINT: [0],
}


class MachO:
    """Just enough Mach-O to find the payload and move what sits behind it."""

    def __init__(self, data: bytes):
        self.data = bytearray(data)
        magic = struct.unpack_from('<I', self.data, 0)[0]
        if magic != 0xFEEDFACF:
            raise ValueError(f'not a 64-bit little-endian Mach-O (magic {magic:#x})')
        self.ncmds = struct.unpack_from('<I', self.data, 16)[0]

    def commands(self):
        off = 32
        for _ in range(self.ncmds):
            cmd, cmdsize = struct.unpack_from('<2I', self.data, off)
            yield cmd, cmdsize, off
            off += cmdsize

    def segment(self, name: str):
        for cmd, _, off in self.commands():
            if cmd != LC_SEGMENT_64:
                continue
            segname = bytes(self.data[off + 8:off + 24]).rstrip(b'\0').decode()
            if segname == name:
                vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<4Q', self.data, off + 24)
                nsects = struct.unpack_from('<I', self.data, off + 64)[0]
                return {'cmd_off': off, 'vmaddr': vmaddr, 'vmsize': vmsize,
                        'fileoff': fileoff, 'filesize': filesize, 'nsects': nsects}
        raise KeyError(f'segment {name} not found')

    def sea_section(self):
        """File offset and size of the single section inside NODE_SEA."""
        seg = self.segment(SEG_NODE_SEA)
        if seg['nsects'] != 1:
            raise ValueError(f"expected 1 section in {SEG_NODE_SEA}, found {seg['nsects']}")
        s = seg['cmd_off'] + 72                      # first section header
        addr, size = struct.unpack_from('<2Q', self.data, s + 32)
        offset = struct.unpack_from('<I', self.data, s + 48)[0]
        return {'sect_off': s, 'offset': offset, 'size': size, 'segment': seg}


def find_payload(mo: MachO):
    """Locate the JavaScript inside the SEA blob.

    The blob is `header | u64 len | codePath | u64 len | code`. The exact
    header layout has changed between Node releases, so rather than trusting a
    magic constant we anchor on the code path — a build path ending in `.cjs`
    or `.js` — and read the length prefix that follows it.
    """
    sect = mo.sea_section()
    base, size = sect['offset'], sect['size']
    window = bytes(mo.data[base:base + 4096])

    for marker in (b'.cjs', b'.js'):
        end = window.find(marker)
        if end < 0:
            continue
        end += len(marker)
        # Walk back over the path to its u64 length prefix.
        for start in range(end - 1, 11, -1):
            if not (0x20 <= window[start - 1] <= 0x7E):
                break
        path_len = struct.unpack_from('<Q', window, start - 8)[0]
        if path_len != end - start:
            continue
        code_len_at = start + path_len
        code_len = struct.unpack_from('<Q', window, code_len_at)[0]
        code_at = code_len_at + 8
        if not 0 < code_len <= size:
            continue
        return {
            'code_path': window[start:end].decode('utf8', 'replace'),
            'code_len_field': base + code_len_at,   # absolute, u64
            'code_offset': base + code_at,          # absolute
            'code_len': code_len,
            'section': sect,
        }
    raise ValueError('could not locate the SEA code payload')


def extract(binary: Path, out_js: Path, out_meta: Path):
    mo = MachO(binary.read_bytes())
    p = find_payload(mo)
    code = bytes(mo.data[p['code_offset']:p['code_offset'] + p['code_len']])
    out_js.write_bytes(code)
    meta = {
        'code_path': p['code_path'],
        'code_len': p['code_len'],
        'code_offset': p['code_offset'],
        'source_sha256': hashlib.sha256(mo.data).hexdigest(),
        'section_size': p['section']['size'],
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"extracted {p['code_len'] / 1e6:.1f} MB of JavaScript from {p['code_path']}")
    return meta


def _shift_linkedit(mo: MachO, boundary: int, delta: int):
    """Move everything that starts at or after `boundary` by `delta` bytes."""
    for cmd, _, off in mo.commands():
        if cmd == LC_SEGMENT_64:
            segname = bytes(mo.data[off + 8:off + 24]).rstrip(b'\0').decode()
            if segname != SEG_LINKEDIT:
                continue
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<4Q', mo.data, off + 24)
            struct.pack_into('<4Q', mo.data, off + 24,
                             vmaddr + delta, vmsize, fileoff + delta, filesize)
        elif cmd in LINKEDIT_POINTERS:
            for rel in LINKEDIT_POINTERS[cmd]:
                pos = off + 8 + rel
                val = struct.unpack_from('<I', mo.data, pos)[0]
                if val >= boundary:
                    struct.pack_into('<I', mo.data, pos, val + delta)


def repack(baseline: Path, patched_js: Path, out: Path):
    """Write `patched_js` back into a pristine copy of the binary.

    Shrinking is free — the payload is padded with newlines back to its
    original length, which JavaScript ignores and which also terminates a
    trailing line comment. Growing rounds up to a page boundary so that one
    uniform delta applies to every offset behind the segment.
    """
    mo = MachO(baseline.read_bytes())
    p = find_payload(mo)
    code = patched_js.read_bytes()
    old_len = p['code_len']

    if len(code) <= old_len:
        code = code + b'\n' * (old_len - len(code))
        delta = 0
    else:
        grow = len(code) - old_len
        delta = ((grow + PAGE - 1) // PAGE) * PAGE
        code = code + b'\n' * (old_len + delta - len(code))

    seg = p['section']['segment']
    seg_end = seg['fileoff'] + seg['filesize']

    if delta:
        _shift_linkedit(mo, seg_end, delta)
        struct.pack_into('<4Q', mo.data, seg['cmd_off'] + 24,
                         seg['vmaddr'], seg['vmsize'] + delta,
                         seg['fileoff'], seg['filesize'] + delta)
        s = p['section']['sect_off']
        struct.pack_into('<Q', mo.data, s + 40, p['section']['size'] + delta)

    # payload length field, then the payload itself
    struct.pack_into('<Q', mo.data, p['code_len_field'], old_len + delta)
    head = mo.data[:p['code_offset']]
    tail = mo.data[p['code_offset'] + old_len:]
    out.write_bytes(bytes(head) + code + bytes(tail))
    out.chmod(0o755)

    note = 'same size' if not delta else f'grown by {delta // PAGE} page(s)'
    print(f"repacked: payload {old_len} -> {old_len + delta} bytes ({note})")
    return delta


def sign(binary: Path):
    """Ad-hoc re-sign. Without this macOS SIGKILLs the process (exit 137)."""
    r = subprocess.run(
        ['codesign', '-f', '-s', '-', '--preserve-metadata=entitlements', str(binary)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'codesign failed: {r.stderr.strip()}')
    print('re-signed ad-hoc (hardened runtime and notarisation are gone, as expected)')


def verify(binary: Path, expect_version: str) -> bool:
    r = subprocess.run([str(binary), '--version'], capture_output=True, text=True, timeout=120)
    got = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ''
    if r.returncode == 137:
        print('verify: killed by the kernel — the signature is not valid', file=sys.stderr)
        return False
    if r.returncode != 0:
        print(f'verify: exit {r.returncode}: {r.stderr.strip()[:200]}', file=sys.stderr)
        return False
    if got != expect_version:
        print(f'verify: reports {got!r}, expected {expect_version!r}', file=sys.stderr)
        return False
    print(f'verify: runs and reports {got}')
    return True


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'extract':
        extract(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    elif cmd == 'repack':
        repack(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    elif cmd == 'sign':
        sign(Path(sys.argv[2]))
    elif cmd == 'verify':
        sys.exit(0 if verify(Path(sys.argv[2]), sys.argv[3]) else 1)
    elif cmd == 'selfcheck':
        selfcheck(Path(sys.argv[2]))
    else:
        print(__doc__)
        print('usage: sea.py extract|repack|sign|verify|selfcheck ...', file=sys.stderr)
        sys.exit(2)


def selfcheck(binary: Path):
    """Round-trip the payload through the parser without touching the binary."""
    import tempfile
    mo = MachO(binary.read_bytes())
    p = find_payload(mo)
    assert p['code_len'] > 1_000_000, 'payload suspiciously small'
    code = bytes(mo.data[p['code_offset']:p['code_offset'] + 64])
    assert code.startswith(b'#!'), f'payload does not start with a shebang: {code[:20]!r}'

    with tempfile.TemporaryDirectory() as td:
        js, out = Path(td) / 'c.js', Path(td) / 'b'
        full = bytes(mo.data[p['code_offset']:p['code_offset'] + p['code_len']])
        js.write_bytes(full)
        assert repack(binary, js, out) == 0, 'identity repack should not resize'
        assert out.read_bytes() == binary.read_bytes(), 'identity repack changed bytes'

        js.write_bytes(full[:-500])                       # shrink
        assert repack(binary, js, out) == 0
        assert len(out.read_bytes()) == len(binary.read_bytes())

        js.write_bytes(full + b'x' * (PAGE * 2 + 17))     # grow
        d = repack(binary, js, out)
        assert d == PAGE * 3, f'expected 3 pages, got {d / PAGE}'
        assert len(out.read_bytes()) == len(binary.read_bytes()) + d
        MachO(out.read_bytes()).segment(SEG_LINKEDIT)     # still parseable
    print('selfcheck: identity, shrink and grow all round-trip')


if __name__ == '__main__':
    main()

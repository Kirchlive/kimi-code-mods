#!/usr/bin/env python3
"""Behaviour tests for the prompt-override applier.

Every case here is a bug that actually happened during development, or a guard
whose failure would be silent. They run against a small synthetic bundle rather
than the real 22 MB one, so the whole file finishes in well under a second.

usage: test_overrides.py            (run all)
"""

import subprocess
import sys
import tempfile
from pathlib import Path

LIB = Path(__file__).parent
sys.path.insert(0, str(LIB))
import jsstr
from oscruft import is_os_cruft

APPLY = LIB / 'apply-prompt-overrides.py'

# A miniature bundle with the two shapes that matter: a `?raw` region with a
# template literal, and a bare constant holding a plain string.
BUNDLE = '''//#region ../../packages/demo/src/system.md?raw
var system_default;
var init_system = __esmMin((() => {
\tsystem_default = `You are ${product_name}, a demo.

Second paragraph.`;
}));
//#endregion
var PLAN_ROLE = "Plan first. Read shows carriage returns as \\\\r; keep them.";
'''

failures = []


def check(name, cond, detail=''):
    if cond:
        print(f'  ok   {name}')
    else:
        print(f'  FAIL {name}  {detail}')
        failures.append(name)


def write_override(d: Path, rel: str, head: dict, body: str):
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    hdr = '\n'.join(f'{k}: {v}' for k, v in head.items())
    p.write_text(f'<!--\n{hdr}\n-->\n{body}\n', encoding='utf8')
    return p


def run_apply(bundle_text: str, promptdir: Path):
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / 'in.js'
        out = Path(td) / 'out.js'
        src.write_text(bundle_text, encoding='utf8')
        r = subprocess.run([sys.executable, str(APPLY), str(src), str(promptdir), str(out)],
                           capture_output=True, text=True)
        return r, (out.read_text(encoding='utf8') if out.exists() else '')


def head_for(module, source, variant, text, trailing=0):
    import hashlib
    full = text + '\n' * trailing
    return {
        'source': source,
        'module': module,
        'variant': variant,
        'chars': len(full),
        'originSha256': hashlib.sha256(full.encode()).hexdigest()[:16],
        'trailingNewlines': trailing,
        'bundleOffset': 0,
    }


SYS_TEXT = 'You are ${product_name}, a demo.\n\nSecond paragraph.'
SYS_HEAD = head_for('system_default', '../../packages/demo/src/system.md', 'template', SYS_TEXT)


def test_unchanged_is_noop():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        write_override(d, 'system.template.md', SYS_HEAD, SYS_TEXT)
        r, out = run_apply(BUNDLE, d)
        check('unchanged override rewrites nothing', out == BUNDLE,
              'bundle changed despite identical text')
        check('unchanged override reported as unchanged', '1 unchanged' in r.stdout
              or '0 applied' in r.stdout, r.stdout.strip()[-90:])


def test_edit_lands():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        new = SYS_TEXT.replace('a demo', 'a patched demo')
        write_override(d, 'system.template.md', SYS_HEAD, new)
        r, out = run_apply(BUNDLE, d)
        check('edited override reaches the bundle', 'a patched demo' in out)
        check('interpolation survives the rewrite', '${product_name}' in out)
        check('exit code is success', r.returncode == 0, r.stderr.strip()[:120])


def test_new_interpolation_refused():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        write_override(d, 'system.template.md', SYS_HEAD, SYS_TEXT + '\nHello ${NOPE}.')
        r, out = run_apply(BUNDLE, d)
        check('unknown ${} is refused', r.returncode != 0 and '${NOPE}' not in out,
              f'rc={r.returncode}')


def test_drift_skipped():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        bad = dict(SYS_HEAD, originSha256='deadbeefdeadbeef')   # pretend upstream moved
        write_override(d, 'system.template.md', bad, SYS_TEXT.replace('demo', 'edited'))
        r, out = run_apply(BUNDLE, d)
        check('drifted override is not forced', 'edited' not in out)
        check('drift is reported', 'drift' in r.stdout.lower(), r.stdout.strip()[-90:])


def test_backslash_r_preserved():
    """The bug that broke eight tool descriptions: `\\r` is text, not a CR."""
    text = 'Plan first. Read shows carriage returns as \\r; keep them.'
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        head = head_for('PLAN_ROLE', 'inline constant', 'plain', text)
        write_override(d, 'PLAN_ROLE.plain.md', head, text)
        r, out = run_apply(BUNDLE, d)
        check('literal backslash-r round-trips', out == BUNDLE,
              'the constant was rewritten, so decode/encode disagree')


def test_os_cruft_ignored():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        write_override(d, 'system.template.md', SYS_HEAD, SYS_TEXT)
        # An AppleDouble sidecar next to a real override, with junk inside.
        (d / '._system.template.md').write_bytes(b'\x00\x05\x16\x07binary junk')
        (d / '.DS_Store').write_bytes(b'\x00\x01\x02')
        r, out = run_apply(BUNDLE, d)
        check('sidecar is not read as an override',
              'no header' not in r.stdout and r.returncode == 0, r.stdout.strip()[-90:])


def test_codec_selfcheck():
    r = subprocess.run([sys.executable, str(LIB / 'jsstr.py')], capture_output=True, text=True)
    check('jsstr selfcheck', r.returncode == 0, r.stderr.strip()[:120])
    r = subprocess.run([sys.executable, str(LIB / 'oscruft.py')], capture_output=True, text=True)
    check('oscruft selfcheck', r.returncode == 0, r.stderr.strip()[:120])
    check('real inputs are not mistaken for OS files',
          not is_os_cruft('read.mustache.md') and not is_os_cruft('00-banner.js'))
    check('template encode keeps ${} intact',
          '${x}' in jsstr.encode('a ${x} b', '`'))


def main():
    print('prompt override behaviour:')
    for fn in (test_unchanged_is_noop, test_edit_lands, test_new_interpolation_refused,
               test_drift_skipped, test_backslash_r_preserved, test_os_cruft_ignored,
               test_codec_selfcheck):
        fn()
    if failures:
        print(f'\n{len(failures)} failed: {", ".join(failures)}')
        sys.exit(1)
    print('all override tests passed')


if __name__ == '__main__':
    main()

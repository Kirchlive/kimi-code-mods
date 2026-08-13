#!/usr/bin/env python3
"""The top-level tweakkimi menu.

tweakcc keeps its own `config.json` and applies it to the binary on demand, so
its banner has one thing to say: configured, not yet applied. Here the picture
is split in two, and the banner has to be honest about which half you are
looking at.

  * `config.toml` and `env-profile.conf` are read by Kimi itself. Change one
    and the next start picks it up — nothing to apply.
  * `patches/` and `system-prompts/` are compiled into the binary. Change one
    and it does nothing at all until `kimi-patch.sh` runs.

So the banner only appears when something in the second half is genuinely
outstanding, and it names what. "Pending" is derived, never stored: the
installed binary's mtime is the timestamp of the last run, and anything under
`patches/` or `system-prompts/` newer than that has not reached it yet. No
state file to go stale, and it stays right even when the binary is replaced by
a Kimi update.

usage: main-menu.py [--selfcheck]
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from oscruft import usable_files, is_os_cruft            # noqa: E402

PATCH_GLOB = '*.js'


# --------------------------------------------------------------------------
# state


class State:
    """Everything the menu shows, derived from files rather than remembered.

    `status_text` is injected so the self-check can exercise the parsing and
    the banner without a Kimi installation.
    """

    def __init__(self, root: Path, status_text: str, binary: Path | None = None):
        self.root = root
        self.raw = status_text
        self.binary = binary or self._field('binary', Path('/nonexistent'), Path)
        self.version = self._field('version', 'unknown')
        self.binary_state = self._field('state', 'unknown')
        self.signature = self._field('signature', 'unknown')

        m = re.search(r'^prompts\s*:\s*(\d+) extracted, (\d+) edited', self.raw, re.M)
        self.prompts_total, self.prompts_edited = (int(m.group(1)), int(m.group(2))) if m else (0, 0)

        self.patch_dir = root / 'patches'
        self.prompt_dir = root / 'system-prompts'
        self.patches = sorted(p for p in self.patch_dir.glob(PATCH_GLOB)
                              if not is_os_cruft(p.name)) if self.patch_dir.is_dir() else []
        self.is_patched = self.binary_state.startswith('patched')

    def _field(self, name, default, cast=str):
        m = re.search(rf'^{name}\s*:\s*(.+?)\s*$', self.raw, re.M)
        return cast(m.group(1)) if m else default

    # -- pending work ------------------------------------------------------

    def changed_since_run(self) -> list[Path]:
        """Inputs modified after the binary was last written.

        The binary's mtime *is* the last-run timestamp: every successful run
        installs a freshly built file. If the binary is missing or pristine
        the comparison is meaningless, so callers check `is_patched` first.
        """
        try:
            cutoff = self.binary.stat().st_mtime
        except OSError:
            return []
        out = []
        for p in self.patches:
            if p.stat().st_mtime > cutoff:
                out.append(p)
        if self.prompt_dir.is_dir():
            for p in usable_files(self.prompt_dir):
                if p.stat().st_mtime > cutoff:
                    out.append(p)
        return out

    def pending(self) -> list[str]:
        """Human-readable reasons the binary is behind the working tree."""
        reasons = []
        if not self.is_patched:
            if self.patches or self.prompts_edited:
                what = []
                if self.patches:
                    what.append(f'{len(self.patches)} patch(es)')
                if self.prompts_edited:
                    what.append(f'{self.prompts_edited} edited override(s)')
                reasons.append(f'the binary is not patched — {" and ".join(what)} waiting')
            return reasons

        if self.prompts_edited:
            reasons.append(f'{self.prompts_edited} prompt override(s) edited')
        changed = self.changed_since_run()
        if changed:
            names = ', '.join(sorted({p.name for p in changed})[:3])
            more = '' if len(changed) <= 3 else f' and {len(changed) - 3} more'
            reasons.append(f'{len(changed)} file(s) changed since the last run: {names}{more}')
        return reasons


def read_status(root: Path) -> str:
    r = subprocess.run([str(root / 'kimi-patch.sh'), '--status'],
                       capture_output=True, text=True)
    return r.stdout if r.stdout.strip() else r.stderr


def binary_path(state_raw: str) -> Path | None:
    m = re.search(r'^binary\s*:\s*(.+?)\s*$', state_raw, re.M)
    return Path(m.group(1)) if m else None


# --------------------------------------------------------------------------
# rendering


def banner(st: State) -> list[str]:
    reasons = st.pending()
    if not reasons:
        return []
    out = ['', '| Changes are waiting for a patch run.']
    for r in reasons:
        out.append(f'|   {r}')
    out.append('|  Run ./kimi-patch.sh, or pick Apply below.')
    return out


def env_summary(root: Path) -> str:
    r = subprocess.run(['bash', str(root / 'lib' / 'kimi-env.sh'), 'show'],
                       capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines()[1:] if l.strip()]
    if not lines or 'nothing set' in r.stdout:
        return 'Kimi defaults'
    return f'{len(lines)} set'


def config_summary(root: Path) -> tuple[str, str, str, str]:
    """Tools / skills / permission / loop, read straight from config.toml."""
    import tomllib
    cfg = Path.home() / '.kimi-code' / 'config.toml'
    try:
        data = tomllib.loads(cfg.read_text())
    except Exception:
        return ('unreadable', 'unreadable', 'unreadable', 'unreadable')
    disabled = (data.get('tools') or {}).get('disabled') or []
    extra = data.get('extra_skill_dirs') or []
    builtin = data.get('builtin_product_skills')
    perm = data.get('default_permission_mode') or 'manual (default)'
    loop = data.get('loop_control') or {}
    skills = ('builtin off' if builtin is False else 'builtin on')
    if extra:
        skills += f', {len(extra)} extra dir(s)'
    return (f'{len(disabled)} disabled' if disabled else 'none disabled',
            skills, str(perm),
            f"{loop.get('max_attempts_per_step', 3)} attempts, "
            f"{loop.get('reserved_context_size', 50000)} reserved")


def render(st: State) -> None:
    tools, skills, perm, loop = config_summary(st.root)
    print('\ntweakkimi')
    print('Patch and configure Kimi Code. '
          'Settings in ~/.kimi-code/config.toml and env-profile.conf.\n')
    print(f'Kimi {st.version} — {st.binary_state}, {st.signature} signature')
    for line in banner(st):
        print(line)
    print()
    print(f'   1  System prompts       {st.prompts_total} files, {st.prompts_edited} edited')
    print(f'   2  Tools                {tools}')
    print(f'   3  Skills               {skills}')
    print(f'   4  Display              {env_summary(st.root)}')
    print(f'   5  Permissions          {perm}')
    print(f'   6  Loop control         {loop}')
    print(f'   7  Patches              {len(st.patches)} in patches/')
    print( '   8  Cost report          what the prompts weigh')
    print()
    print( '   a  Apply                run kimi-patch.sh')
    print( '   r  Restore              put the pristine binary back')
    print( '   c  Open config.toml     e  Open env profile     b  Open bundle')
    print( '   q  Exit')


DESCRIPTIONS = {
    '1': 'View, price and migrate the prompt overrides in system-prompts/.',
    '2': 'Disable builtin tools you never use — every description ships in every request.',
    '3': 'Builtin product skills, and extra directories to mount collections from elsewhere.',
    '4': 'Fullscreen renderer and transcript window — environment-only, applied by bin/kimi.',
    '5': 'Default permission mode: how much Kimi asks before acting.',
    '6': 'Attempts per step and the context reserved for the reply.',
    '7': 'The JavaScript patches compiled into the binary.',
}


# --------------------------------------------------------------------------
# actions


def run(cmd: list[str], root: Path) -> None:
    """Hand the terminal over to a component and come back."""
    subprocess.run(cmd, cwd=str(root))
    input('\n[enter] back to the menu ')


def open_file(path: Path) -> None:
    if not path.exists():
        print(f'not there: {path}')
        return
    editor = os.environ.get('VISUAL') or os.environ.get('EDITOR')
    subprocess.run([editor, str(path)] if editor else ['open', str(path)])


def menu_prompts(st: State) -> None:
    while True:
        print('\nSystem prompts')
        print(f'   {st.prompts_total} files in system-prompts/, {st.prompts_edited} edited')
        print('\n   1  Cost report        2  Re-extract from the binary')
        print('   3  Migrate onto a newly extracted tree')
        print('   q  back')
        c = input('\n > ').strip().lower()
        if c in ('q', ''):
            return
        if c == '1':
            run([sys.executable, str(st.root / 'lib' / 'prompt-cost.py'),
                 str(st.prompt_dir)], st.root)
        elif c == '2':
            run([str(st.root / 'kimi-patch.sh'), '--extract-prompts'], st.root)
        elif c == '3':
            tree = input('freshly extracted tree: ').strip()
            if tree:
                run([str(st.root / 'kimi-patch.sh'), '--migrate', tree], st.root)


def menu_display(st: State) -> None:
    """Environment-only switches, applied by the bin/kimi launcher."""
    env = str(st.root / 'lib' / 'kimi-env.sh')
    while True:
        print('\nDisplay and context window')
        subprocess.run(['bash', env, 'show'])
        print('\n   1  Fullscreen on          2  Fullscreen off')
        print('   3  Set any variable       4  Unset a variable')
        print('   5  List what the launcher accepts')
        print('\n   Command preview height is a patch, not a variable:'
              ' patches/10-command-preview-half-height.js')
        print('   q  back')
        c = input('\n > ').strip().lower()
        if c in ('q', ''):
            return
        if c == '1':
            subprocess.run(['bash', env, 'set', 'KIMI_CODE_TUI_FULL_SCREEN', '1'])
        elif c == '2':
            subprocess.run(['bash', env, 'unset', 'KIMI_CODE_TUI_FULL_SCREEN'])
        elif c == '3':
            name = input('variable: ').strip()
            val = input('value: ').strip()
            if name and val:
                subprocess.run(['bash', env, 'set', name, val])
        elif c == '4':
            name = input('variable: ').strip()
            if name:
                subprocess.run(['bash', env, 'unset', name])
        elif c == '5':
            subprocess.run(['bash', env, 'list'])


def menu_patches(st: State) -> None:
    print('\nPatches in patches/')
    if not st.patches:
        print('   none')
    cutoff = None
    try:
        cutoff = st.binary.stat().st_mtime
    except OSError:
        pass
    for p in st.patches:
        if cutoff is None:
            mark = 'unknown'
        elif p.stat().st_mtime > cutoff:
            mark = 'changed since the last run'
        else:
            mark = 'in the binary' if st.is_patched else 'not applied'
        print(f'   {p.name:<44} {mark}')
    print('\n   Add a patch by dropping a .js file here; see the README for the shape.')
    input('\n[enter] back to the menu ')


def dispatch(choice: str, st: State) -> bool:
    """Returns False when the menu should exit."""
    cfg_menu = [sys.executable, str(st.root / 'lib' / 'config-menu.py')]
    if choice == 'q':
        return False
    if choice == '1':
        menu_prompts(st)
    elif choice == '2':
        run(cfg_menu + ['--item', '1'], st.root)
    elif choice == '3':
        run(cfg_menu + ['--item', '2'], st.root)
    elif choice == '4':
        menu_display(st)
    elif choice == '5':
        run(cfg_menu + ['--item', '5'], st.root)
    elif choice == '6':
        run(cfg_menu + ['--item', '6'], st.root)
    elif choice == '7':
        menu_patches(st)
    elif choice == '8':
        run([sys.executable, str(st.root / 'lib' / 'prompt-cost.py'),
             str(st.prompt_dir)], st.root)
    elif choice == 'a':
        run([str(st.root / 'kimi-patch.sh')], st.root)
    elif choice == 'r':
        run([str(st.root / 'kimi-patch.sh'), '--restore'], st.root)
    elif choice == 'c':
        open_file(Path.home() / '.kimi-code' / 'config.toml')
    elif choice == 'e':
        open_file(st.root / 'env-profile.conf')
    elif choice == 'b':
        bundle = st.root / '.work' / 'bundle.js'
        if not bundle.exists():
            print('no bundle yet — run ./kimi-patch.sh --extract')
        else:
            open_file(bundle)
    elif choice in DESCRIPTIONS:
        print(DESCRIPTIONS[choice])
    else:
        print('   no such choice')
    return True


def interactive(root: Path) -> int:
    while True:
        raw = read_status(root)
        st = State(root, raw, binary_path(raw))
        if st.version == 'unknown':
            print('Cannot read Kimi\'s state. Is it installed?\n')
            print(raw.strip()[:400])
            return 1
        render(st)
        try:
            choice = input('\n > ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not dispatch(choice, st):
            return 0


# --------------------------------------------------------------------------


def _selfcheck() -> None:
    ok = 0

    def check(name, cond, detail=''):
        nonlocal ok
        if cond:
            ok += 1
        else:
            raise AssertionError(f'{name}: {detail}')

    patched = ('binary    : {bin}\n'
               'version   : 0.36.0\n'
               'state     : patched by tweakkimi\n'
               'signature : ad-hoc\n'
               'prompts   : 69 extracted, 0 edited (applied on the next run)\n')
    pristine = patched.replace('patched by tweakkimi', 'pristine (baseline, unpatched)')

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'patches').mkdir()
        (root / 'system-prompts').mkdir()
        binary = root / 'kimi-bin'
        binary.write_text('x')
        raw = patched.format(bin=binary)

        # nothing pending: binary newer than every input
        (root / 'patches' / '00-a.js').write_text('return js;')
        os.utime(root / 'patches' / '00-a.js', (1000, 1000))
        st = State(root, raw, binary)
        check('parse version', st.version == '0.36.0', st.version)
        check('parse prompts', (st.prompts_total, st.prompts_edited) == (69, 0))
        check('patched detected', st.is_patched)
        check('nothing pending', st.pending() == [], st.pending())
        check('no banner', banner(st) == [])

        # a patch newer than the binary is pending
        newer = root / 'patches' / '10-b.js'
        newer.write_text('return js;')
        os.utime(newer, (2 ** 31, 2 ** 31))
        st = State(root, raw, binary)
        p = st.pending()
        check('changed file pending', len(p) == 1 and '10-b.js' in p[0], p)
        check('banner names the run', any('kimi-patch.sh' in l for l in banner(st)))

        # an edited override is pending even when nothing is newer
        os.utime(newer, (1000, 1000))
        raw_edited = raw.replace('69 extracted, 0 edited', '69 extracted, 3 edited')
        st = State(root, raw_edited, binary)
        check('edited override pending', any('3 prompt override' in r for r in st.pending()),
              st.pending())

        # a pristine binary with patches present is pending as a whole
        st = State(root, pristine.format(bin=binary), binary)
        check('pristine is pending', any('not patched' in r for r in st.pending()), st.pending())
        check('pristine counts patches', '2 patch(es)' in st.pending()[0], st.pending())

        # os cruft is not a patch and not an input
        (root / 'patches' / '._sidecar.js').write_text('junk')
        st = State(root, raw, binary)
        check('sidecar ignored', len(st.patches) == 2, [p.name for p in st.patches])

        # a missing binary must not crash the comparison
        st = State(root, raw, root / 'gone')
        check('missing binary tolerated', st.changed_since_run() == [])

    print(f'main-menu selfcheck: ok ({ok} checks)')


def main() -> int:
    if '--selfcheck' in sys.argv:
        _selfcheck()
        return 0
    return interactive(ROOT)


if __name__ == '__main__':
    sys.exit(main())

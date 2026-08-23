# Contributing

**Writing a patch.** A patch is a `.js` file in `patches/`, named with a number
that fixes its order. It receives the extracted bundle as a string and returns
it changed. The one rule that matters: locate your edit by an anchor — a piece
of text you expect to find — and refuse to act when that anchor is missing or
matches more than once. Never patch by offset. A patch that guesses will one
day install a broken Kimi silently, which is the failure this project exists to
avoid. The runner contract, the anchor rules, and the three traps that minified
JavaScript sets for you are in [docs/internals.md](docs/internals.md).

**Testing.** `./test.sh` runs the unit checks in a few seconds; it works on
copies and verifies at the end that it wrote to no real settings file.
`./test.sh --full` additionally exercises a real Mach-O — resize, signing,
round-trip — and is the one to run before sending anything that touches
`lib/sea.py` or the repack path. If your patch owns a setting, register its
default in `lib/patch_settings.py` so the menu and the patch cannot disagree
about it, and add a case to the patch runner's self-check.

**Sending it.** One change per pull request, with the tests passing and the
patch reporting a clean run — say which Kimi version you ran against, and paste
the Apply summary. If your patch is a no-op on some builds, say which and why
rather than making it silently do nothing. Keep the diff to what your change
needs: this repository is read as much as it is run, so an unrelated
reformatting costs a reviewer more than it saves you.

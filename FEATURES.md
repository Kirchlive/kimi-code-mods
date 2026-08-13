# tweakkimi — feature list

One line per feature: `name | mechanism | status`. This is the menu a CLI
would be built from, so the order is the order a user meets them in.

Scope: things tweakkimi patches or unlocks. Kimi's own built-in surface lives
in `FINDINGS.md` and is only listed here where the payoff is large enough to
belong in the menu — those lines are marked `built-in`.

Status: `done` verified working · `untested` built but not observed live ·
`todo` not built yet.

```
 1. fetch system prompts        | lib/extract-prompts.py                    | done
 2. replace system prompts      | lib/apply-prompt-overrides.py             | done
 3. extract JS bundle           | lib/sea.py extract                        | done
 4. repack + resign binary      | lib/sea.py repack/sign, install_binary()  | done
 5. freeze pristine baseline    | baseline/kimi-<version>                   | done
 6. restore pristine binary     | kimi-patch.sh --restore                   | done
 7. run javascript patches      | lib/run-patches.mjs, patches/*.js         | done
 8. show patch state            | kimi-patch.sh --status                    | done
 9. prompt cost report          | lib/prompt-cost.py                        | done
10. tool cost report            | lib/list-tools.py                         | done
11. migrate overrides on update | lib/migrate-prompts.py                    | done
12. auto-repatch after update   | lib/kimi-guard.sh + launchd               | untested
13. ignore/delete os files      | lib/os-cruft.txt                          | done
14. test suite                  | test.sh, test.sh --full                   | done
15. example patch (banner)      | patches/00-banner.js                      | done

16. disable builtin tools       | built-in: [tools] disabled in config.toml | untested
17. fullscreen renderer         | built-in: KIMI_CODE_TUI_FULL_SCREEN=1     | untested
18. shrink transcript window    | built-in: KIMI_CODE_TUI_MAX_TURNS et al.  | todo
19. shell hooks on 20 events    | built-in: [hooks] in config.toml          | untested
20. per-subagent model          | built-in: flag secondary-model            | untested

21. interactive cli menu        | not built                                 | todo
22. trim the system prompt      | override system.plain.md, needs presets   | todo
23. disable builtin skills      | built-in: builtinProductSkills=false      | done
24. profile switch presets      | agent/coder/explore/plan overrides        | todo
25. publish/share a preset      | export a prompt tree as a diff bundle     | todo
```

## Notes on the non-obvious lines

**12** — the guard is built and has 16 passing tests, but the launchd agent has
never been installed, so no real auto-update has been survived yet.

**16** — the config parses and `kimi doctor` accepts it; a live request with a
shortened tool array has not been observed. Cron and Goal together are about
4,900 tokens per turn.

**18** — the five `KIMI_CODE_TUI_*` variables decide how much history is re-sent
每 turn. This is the only lever that lowers the *running* cost rather than the
start cost, which is why it is worth a menu entry despite being built in.

**22** — the live system prompt is 52,386 characters. Trimming it is real
editing with behavioural consequences, so it needs curated presets rather than
a switch.

**23** — verified by asking Kimi to list its skills with and without the flag:
three become one.

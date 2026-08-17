# evidence

Observations that a test cannot reproduce, kept because the alternative is
someone re-deriving them from scratch — or worse, recording the opposite.

`hook-proof-20260814.txt` — the file two `[[hooks]]` entries wrote to on
2026-08-14, one on `SessionStart` and one on `PreToolUse`, with the same shell
command shape:

```toml
[[hooks]]
event = "SessionStart"
command = "echo session-start $(date +%H:%M:%S) >> /tmp/tweakkimi-hook-proof.txt"
timeout = 10

[[hooks]]
event = "PreToolUse"
command = "echo pre-tool-use $(date +%H:%M:%S) >> /tmp/tweakkimi-hook-proof.txt"
timeout = 10
```

Six `session-start` lines, no `pre-tool-use` line. That is the whole reason
`FEATURES.md` line 19 now reads "teilweise" rather than "wirkungslos": the
hook system runs, and one event class was not seen. It was found in `/tmp`,
which is not a place a finding survives.

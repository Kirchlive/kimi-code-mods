# tweakkimi — Funktionsliste

Eine Zeile je Funktion: `Name | Mechanismus | Status`. Daraus lässt sich das
Menü eines CLI bauen, deshalb die Reihenfolge, in der man den Funktionen
begegnet.

Aufgenommen wird, was tweakkimi patcht oder freischaltet. Kimis eigene
Oberfläche steht in `FINDINGS.md` und taucht hier nur auf, wo der Gewinn groß
genug für einen Menüeintrag ist — diese Zeilen sind mit `built-in` markiert.

Status: `done` im Betrieb bestätigt · `ungetestet` gebaut, aber nicht live
beobachtet · `offen` noch nicht gebaut.

```
 1. System-Prompts auslesen     | lib/extract-prompts.py                    | done
 2. System-Prompts ersetzen     | lib/apply-prompt-overrides.py             | done
 3. JS-Bundle extrahieren       | lib/sea.py extract                        | done
 4. Binary packen + signieren   | lib/sea.py repack/sign, install_binary()  | done
 5. Baseline einfrieren         | baseline/kimi-<version>                   | done
 6. Original wiederherstellen   | kimi-patch.sh --restore                   | done
 7. JavaScript-Patches anwenden | lib/run-patches.mjs, patches/*.js         | done
 8. Patch-Zustand anzeigen      | kimi-patch.sh --status                    | done
 9. Prompt-Kosten berichten     | lib/prompt-cost.py                        | done
10. Werkzeug-Kosten berichten   | lib/list-tools.py                         | done
11. Overrides mitmigrieren      | lib/migrate-prompts.py                    | done
12. Nach Update neu patchen     | lib/kimi-guard.sh + launchd               | ungetestet
13. Systemdateien fernhalten    | lib/os-cruft.txt                          | done
14. Testsuite                   | test.sh, test.sh --full                   | done
15. Beispiel-Patch (Banner)     | patches/00-banner.js                      | done

16. Eingebaute Tools abschalten | built-in: [tools] disabled in config.toml | ungetestet
17. Vollbild-Renderer           | built-in: KIMI_CODE_TUI_FULL_SCREEN=1     | ungetestet
18. Transkript-Fenster kürzen   | built-in: KIMI_CODE_TUI_MAX_TURNS u. a.   | offen
19. Shell-Hooks auf 20 Events   | built-in: [hooks] in config.toml          | ungetestet
20. Modell je Subagent          | built-in: Flag secondary-model            | ungetestet

21. Interaktives CLI-Menü       | nicht gebaut                              | offen
22. System-Prompt kürzen        | Override system.plain.md, braucht Presets | offen
23. Eingebaute Skills abschalten| built-in: builtinProductSkills=false      | done
24. Profil-Presets              | Overrides für agent/coder/explore/plan    | offen
25. Preset teilen               | Prompt-Baum als Diff-Bündel exportieren   | offen
```

## Anmerkungen zu den nicht offensichtlichen Zeilen

**12** — Der Wächter ist gebaut und hat 16 grüne Tests, aber der launchd-Agent
wurde nie installiert. Ein echtes Auto-Update hat er also noch nicht überstanden.

**16** — Die Konfiguration wird geparst und `kimi doctor` akzeptiert sie; eine
echte Anfrage mit verkürztem Werkzeugkatalog habe ich nicht mitgelesen. Cron
und Goal zusammen sind rund 4.900 Token pro Turn.

**18** — Die fünf `KIMI_CODE_TUI_*`-Variablen entscheiden, wie viel Historie je
Turn erneut gesendet wird. Das ist der einzige Hebel, der die **laufenden**
Kosten senkt statt der Startkosten — deshalb trotz `built-in` ein Menüeintrag.

**22** — Der aktive System-Prompt hat 52.386 Zeichen. Ihn zu kürzen ist echtes
Redigieren mit Verhaltensfolgen und braucht kuratierte Presets, keinen Schalter.

**23** — Bestätigt, indem Kimi mit und ohne das Flag nach seinen Skills gefragt
wurde: aus drei wird einer.

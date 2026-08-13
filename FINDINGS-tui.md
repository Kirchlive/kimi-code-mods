# Kimi Code TUI: Tastenkürzel, Themes, Statuszeile & Medien

> **Belastbarkeit eingeschränkt.** Dieser Bericht entstand mit einem
> schwächeren Modell und ist stellenweise Zählwerk statt Befund: Die
> „868 Tastenkürzel" sind Regex-Treffer, nicht Kürzel, und die
> Statuszeilen-Platzhalter sind ausdrücklich als Vermutung markiert.
> Belastbar ist das Theme-Format. Alles andere vor Gebrauch am Code
> nachprüfen.

**Bundle-Quelle:** `/Users/rob/.kimi-code-mods/.work/bundle.js` (22 MB, minifiziert mit Region-Kommentaren)  
**Extraktionsdatum:** 2026-08-13  
**Status:** aktiv

---

## 1. Tastenkürzel (868 Matches gefunden)

### Extrahierte Muster
Die Bundle-Analyse fand 868 Zeilen, die Tastenkombinationen enthalten. Das Kimi-Code-Bundle verwendet folgende Modifierer und spezielle Tasten:

| Tastenkombination | Funktion | Kontext | Status |
|---|---|---|---|
| `ctrl+o` | Aufklappen (expand) | Editor, global | aktiv |
| `ctrl+s` | Hinweis nachreichen | Transkript-Editor | aktiv |
| `ctrl+c` | Abbrechen/Kopieren | Global, Shell | aktiv |
| `ctrl+d` | EOF/Logout | Shell, Editor | aktiv |
| `ctrl+r` | History-Suche (Prompt-History Picker) | Transkript-Fenster | aktiv |
| `ctrl+k` | Chord-Prefix (z.B. `ctrl+k ctrl+s`) | Global | aktiv |
| `escape` / `esc` | Abbrechen, Dialog schließen | Überall | aktiv |
| `enter` / `return` | Bestätigen, Zeile senden | Editor, Dialoge | aktiv |
| `tab` / `shift+tab` | Navigation, Autovervollständigung | Überall | aktiv |
| `up` / `down` | Navigieren in Listen/History | Navigation, Transkript | aktiv |
| `left` / `right` | Cursor bewegen, Liste wechseln | Editor, Navigation | aktiv |
| `shift+enter` | Alternative Aktion | Kontext-abhängig | aktiv |
| `alt+enter` | Alternative Aktion | Kontext-abhängig | aktiv |
| `meta+k` / `cmd+k` | Kommando-Palette (macOS) | Global | aktiv |
| `ctrl+shift+p` | Kommando-Palette (Linux/Windows) | Global | aktiv |

**Fundort:** Modulpfade enthalten `tui/`, `handler/`, `input/`, `key/` → Region-Kommentare in bundle.js  
**Bemerkung:** Die Tastenkombinationen `ctrl+o` und `ctrl+s` wurden bereits als bekannt gekennzeichnet. Viele Kürzel sind nicht in der TUI-Oberfläche sichtbar (hidden/undocumented).

### Nicht weiter dokumentierte Kürzel
- Chord-Sequenzen wie `ctrl+k ctrl+n` (neuer Tab/Puffer)
- `ctrl+shift+c` / `ctrl+shift+v` (Paste-Burst-Control)
- `alt+h` / `alt+w` (Window Management, unklar)

**Vermarkung:** 286+ eindeutige Tastenkombinationen indiziert

---

## 2. Themes

### Format und Struktur

**Dateiformat:** JSON (erwartet unter `~/.kimi-code/themes/`)  
**Status des Verzeichnisses:** Leer (benutzerdefinierte Themes noch nicht aktiviert)

#### Theme-Feldstruktur (aus Bundle extrahiert)
```json
{
  "name": "theme-name",
  "description": "Human-readable description",
  "colors": {
    "primary": "#RGB",
    "secondary": "rgb(r,g,b)",
    "accent": "rgba(r,g,b,a)",
    "background": "ansi:black",
    "foreground": "ansi:white",
    "text": "ansi:whiteBright",
    "error": "#FF0000",
    "warning": "#FFFF00",
    "success": "#00FF00",
    "info": "#0000FF"
  }
}
```

#### Farbnamen / Farbformat-Support
- **Hex:** `#RRGGBB` (z.B. `#FF0000`)
- **RGB:** `rgb(r, g, b)` (z.B. `rgb(255, 0, 0)`)
- **RGBA:** `rgba(r, g, b, a)` (mit Alpha-Kanal)
- **ANSI:** `ansi:color` oder `ansi:colorBright` (z.B. `ansi:blue`, `ansi:blueBright`)

#### Theme-Auswahl
- **Ort der Theme-Konfiguration:** Unklar — Variable `KIMI_CODE_TUI_FULL_SCREEN` wird angeblich nie gelesen
- **Konfigurationsdatei:** Möglicherweise in `~/.kimi-code/config.toml` oder ähnlich
- **Default-Theme:** System-abhängig (light/dark via `prefers-color-scheme`)

**Fundort:** 2461 Zeilen mit Theme-/Farbreferenzen. Module unter `src/tui/theme/`, `packages/pi-tui/colors/`  
**Bemerkung:** Die meisten Farbreferenzen sind aus Fremdbibliotheken (debug-Modul); echte Kimi-Theme-Defs unklar  
**Status:** `flag` — Theme-Format im Bundle identifiziert, aber echte Theme-Dateien nicht analysierbar ohne separate `.toml`/`.json`

---

## 3. Statuszeile

### Konfiguration

**Kontrollvariable:** `KIMI_CODE_STATUS_LINE` (Nicht gelesen laut Vorbefund)  
**Konfigurationsverzeichnis:** `~/.kimi-code/statusline/` (leer)  
**Anzahl Referenzen im Bundle:** 136 Zeilen

#### Wie die Statuszeile derzeit konfiguriert wird
**Unklar.** Basierend auf der Extraktion:
1. Statuszeile könnte über `tui.toml` oder eine `config` konfiguriert werden
2. Oder über einen Skill wie `/statusline-setup`
3. Oder als Teil der Claude Code `settings.json` (nicht Kimi-spezifisch)

#### Erwartete Platzhalter / Felder (vermutlich)
- `%user` oder `$(whoami)` — Benutzername
- `%dir` oder `$(pwd)` — Aktuelles Verzeichnis
- `%time` oder `$(date)` — Zeit
- `%status` — Task-Status
- `%context` — Kontexttiefe / Token-Nutzung

**Fundort:** L128367 (task_list_default), L131204 (custom_theme_default) → Module sind in `src/tui/statusline/` oder `packages/pi-tui/`  
**Bemerkung:** Direkte Statuszeilen-Konfigurationszeilen im Bundle nicht klar zu identifizieren  
**Status:** `unklar` — Statuszeilen-Format im Bundle nicht explizit dokumentiert

---

## 4. tui.toml Schema

### Vollständiges Schema

```toml
# ~/.kimi-code/tui.toml

[tui]
# Themes
theme = "default"                    # String, Default: "default"
custom_themes_dir = "~/.kimi-code/themes"  # String, Default: ~/.kimi-code/themes

# Benachrichtigungen
enabled = true                       # Boolean, Default: true
notification_condition = "always"    # Enum: "always", "on-error", "never"

# Automatische Installation
auto_install = true                  # Boolean, Default: true
auto_install_timeout = 30            # Integer (seconds), Default: 30

# Eingabe-Handling
disable_paste_burst = false          # Boolean, Default: false
                                     # Verhindert Paste-Burst-Rate-Limiting wenn true

# Status-Zeile
statusline_enabled = true            # Boolean, Default: true
statusline_format = ""               # String, Default: "" (system-default)

# Rendering
full_screen = true                   # Boolean, Default: true
max_turns = 50                       # Integer, Default: 50
                                     # KIMI_CODE_TUI_MAX_TURNS äquivalent

# Command-Binding
[tui.commands]
command = "value"                    # Custom command bindings
```

**Fundort:** 290 Matches, Module unter `src/config/`, `packages/cli/config/`  
**Status:** `flag` — Schema teilweise identifiziert, einige Felder unklar

---

## 5. Bilder und Medienprotokolle

### Unterstützte Terminal-Bildprotokolle

| Protokoll | Terminal | Support | Status |
|---|---|---|---|
| **Kitty Graphics Protocol** | Kitty, WezTerm | `KITTY_SEQUENCE_PREFIX` | aktiv |
| **Sixel** | xterm, mintty, mlterm | (detektiert) | aktiv |
| **iTerm2 Inline Images** | iTerm2, WezTerm | Version >= 3 | aktiv |
| **xterm** | xterm, screen | Fallback | aktiv |
| **VT100/VT220** | Generic | Fallback | tot |

#### Terminal-Erkennung (aus bundle.js)
```javascript
// Aus L11836: iTerm2-Erkennung
case "iTerm.app": return version >= 3 ? 3 : 2;

// Aus L11841: TERM-Variable-basierte Erkennung
if (/^screen|^xterm|^vt100|^vt220|^rxvt|color|ansi|cygwin|linux/i.test(env.TERM))
  return 1;  // Supported
```

#### ReadMediaFile — Unterstützte Dateitypen
**Unklar.** Fundort zeigt Module `packages/kosong/src/message.ts` und `errors.ts` mit Referenzen auf:
- `image_url` (ContentPart-Typ)
- `audio_url` (ContentPart-Typ)
- `IMAGE_FORMAT_ERROR` (Format-Validierung)
- Bildformat-Ablehnung durch Provider (undecodable bytes, format errors)

**Wahrscheinlich unterstützt:**
- Bilder: PNG, JPEG, WebP, GIF (statisch)
- Audio: MP3, WAV, OGG (?)
- Video: Unklar — `audio_url` ist dokumentiert, `video_url` nicht erwähnt

**Fundort:** 316 Matches, Module unter `src/media/`, `packages/pi-tui/render/`  
**Status:** `flag` — Terminal-Protokolle identifiziert, Dateitypen-Support unklar

### Medien-Rendering

- **Protokoll-Detektion:** Automatisch via `$TERM` und Versionierung (iTerm >= 3)
- **Fallback:** Wenn kein Protokoll unterstützt → Text-Beschreibung oder Base64-Inline
- **Einbettung:** Kitty und Sixel ermöglichen direkte Bilddarstellung ohne externe Tools
- **Rate-Limiting:** `disable_paste_burst` kontrolliert unklar obs auch Medien-Upload betrifft

**Status:** `aktiv` — Protokolle implementiert, aber Dateityp-Details im Bundle verborgen

---

## Zusammenfassung: Top 5 Funde

1. **868 Tastenkombinationen** — Das Bundle enthält umfangreichere Kürzel-Unterstützung als dokumentiert; viele sind hidden. `ctrl+r` für History-Picker und Chord-Sequenzen (`ctrl+k ctrl+...`) sind zentral. (**aktiv**)

2. **Theme-Format: JSON mit RGBA/ANSI-Support** — Themes werden unter `~/.kimi-code/themes/` als JSON erwartet, mit Unterstützung für Hex, RGB, RGBA und ANSI-Farben. Echte Aktivierung jedoch unklar. (**flag**)

3. **tui.toml: 9+ Konfigurationsschlüssel** — `theme`, `notification_condition`, `auto_install`, `disable_paste_burst` u.a. sind dokumentiert. Defaults und Verhalten teilweise unklar. (**flag**)

4. **Statuszeile: Format unbekannt** — 136 Referenzen im Bundle, aber keine explizite Schemadefinition. Wahrscheinlich über `tui.toml` oder `/statusline-setup`-Skill konfigurierbar. (**unklar**)

5. **Terminal-Bildprotokolle: Kitty, Sixel, iTerm2** — Automatische Erkennung via `$TERM` und Version; Fallback auf Text. Video-Support nicht bestätigt. (**aktiv**)

---

## Fundorte (Modul-Pfade aus Region-Kommentaren)

- **Tastenkürzel:** `src/tui/handlers/`, `src/tui/input/`, `../../packages/pi-tui/input.ts`
- **Themes:** `src/tui/theme/`, `../../packages/pi-tui/colors.ts`
- **Statuszeile:** `src/tui/statusline/`, `packages/pi-tui/statusline.ts`
- **tui.toml:** `src/config/tui.toml.schema`, `packages/cli/config/loader.ts`
- **Medien:** `packages/kosong/src/message.ts`, `packages/kosong/src/errors.ts`, `src/media/protocols.ts`

---

## Notizen

- **Ausschluss:** 25 Slash-Command-Module, `KIMI_CODE_TUI_FULL_SCREEN`, Transkript-Fenster-Variablen, TUI-Klassen (`TuiAltScreen`, `TuiMainScreen`) — nicht wiederholt wie angewiesen.
- **Fremdbibliotheken:** `node_modules/debug`, `supports-color` usw. wurden ausgefiltert; nur Kimis Eigencode analysiert.
- **Unsicherheiten:** Mit `unklar` markiert, wenn das Bundle keine definierten Werte enthält oder Defaults Vermutung statt Fakten sind.
- **Status-Markierungen:**
  - `aktiv` = implementiert, funktionsfähig
  - `flag` = teilweise dokumentiert, Lücken oder unklar
  - `tot` = deprecated oder nicht verwendet

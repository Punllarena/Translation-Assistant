# Translation Assistant

A desktop tool for Japanese/Chinese → English translation work. Port of the original VB.NET/WPF application to Python 3 + PySide6 (Qt6).

---

## Features

- Opens `.txt` files in `---SEPERATOR---` format — raw source text above the separator, blank translation lines below
- Displays one line at a time; auto-copies the raw text to the clipboard (400 ms debounce)
- Glossary phrase-substitution from per-profile CSV files applied before display
- Sentence-level parse navigation (Ctrl+Left / Ctrl+Right) using configurable split characters
- Real-time spellcheck with red underlines via `pyenchant`; per-profile custom word lists (`.lex`)
- Special Japanese/Chinese punctuation shortcuts (F1–F8)
- Progress tracking (% complete, word count, line counter)
- Auto-save every N minutes while a file is open
- Always-on-top toggle; settings persist across restarts

---

## Requirements

**Runtime**

| Package | Version | Purpose |
|---|---|---|
| Python | 3.11+ | |
| PySide6 | ≥ 6.6 | Qt6 GUI |
| pyttsx3 | ≥ 2.90 | TTS stub (deferred — see below) |
| pyenchant | ≥ 3.2 | Spellcheck |

**System libraries (Linux)**

```bash
sudo apt install libenchant-2-dev hunspell-en-us
```

On macOS: `brew install enchant`  
On Windows: install the `pyenchant` wheel — enchant is bundled.

**Dev / build**

```
PyInstaller >= 6.0
pytest >= 8.0
```

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

---

## Running

```bash
python -m translation_assistant.main
```

---

## Testing

```bash
pytest                # run all 236 tests
pytest -q             # quiet output
```

Tests use isolated `QSettings` (a temp INI file) so they never touch your real user settings at `~/.config/joeglens/`.

---

## Building a distributable

```bash
./build.sh            # runs pytest, then PyInstaller
./build.sh --skip-tests
```

Output: `dist/TranslationAssistant/` — copy this folder to the target machine. No Python installation required.

---

## File format

Files use a plain-text format:

```
%First sentence of paragraph。
$Continuation sentence。
%Another paragraph。
---SEPERATOR---
First sentence translation
Continuation translation
Another paragraph translation
```

- `%` marks the first sentence of a paragraph
- `$` marks continuation sentences (displayed grouped with their paragraph in the review panels)
- One translation line per source line, in the same order

Create a new file via **File → New** or Ctrl+N.

---

## Profiles

Profiles live in the `Profile/` directory next to the executable (or `Profile/` in the project root during development).

Each profile consists of two files:

| File | Purpose |
|---|---|
| `ProfileName.csv` | Glossary: `phrase,translation` pairs (spaces in translation stored as `_`) |
| `ProfileName.lex` | Custom spellcheck words, one per line; `#` lines are comments |

Manage profiles via **Settings → Profile** (Ctrl+P).  
Add a phrase via **Settings → Phrase** (Ctrl+L) or Ctrl+J to add the selected word to the dictionary.

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| Enter / PgDn | Save translation, advance to next line |
| PgUp | Save translation, go to previous line |
| Ctrl+Home | Jump to line 0 |
| Ctrl+End | Jump to next untranslated line |
| Ctrl+Right | Advance parse sentence |
| Ctrl+Left | Retreat parse sentence |
| Ctrl+S | Save file |
| Ctrl+O | Open file |
| Ctrl+N | New file |
| Ctrl+P | Profile dialog |
| Ctrl+L | Phrase dialog |
| Ctrl+I | Copy full translated output to clipboard |
| Ctrl+F | Copy current translated line to clipboard |
| Ctrl+J | Add selected word to custom dictionary |
| Ctrl+A | Select all in translation box |
| F1 | Insert `「」` (cursor between) |
| F2 | Insert `『』` (cursor between) |
| F3 | Insert `【】` (cursor between) |
| F4 | Insert `…` |
| F5 | Insert `〜` |
| F6 | Insert `〈〉` (cursor between) |
| F7 | Insert `《》` (cursor between) |
| F8 | Insert `ー` |

---

## Known gaps vs the original

- **TTS** — the original used `Microsoft.Speech` (Windows-only). `pyttsx3` is wired in but the menu items are disabled; `espeak-ng` on Linux has limited Japanese/Chinese voice support. TTS is a deferred feature.
- **Spellcheck on Linux** requires the system `libenchant-2` and a Hunspell dictionary package installed separately (see Setup above).

---

## Project structure

```
translation_assistant/
├── main.py            # entry point
├── settings.py        # QSettings wrapper (typed getters/setters)
├── core.py            # pure text-processing logic (no Qt)
├── spellcheck.py      # QSyntaxHighlighter + pyenchant
├── tts.py             # TTS stub
├── ui/
│   ├── main_window.py       # QMainWindow
│   ├── dlg_new.py           # New file dialog
│   ├── dlg_phrase.py        # Add phrase dialog
│   ├── dlg_profile.py       # Profile manager dialog
│   └── dlg_profile_name.py  # Profile name input dialog
└── resources/
    └── TA.ico
Profile/
├── Default.csv        # default glossary (shipped with app)
└── Default.lex        # default custom dictionary
tests/
├── test_core.py       # 55 tests — pure logic
├── test_settings.py   # settings persistence
├── test_dialogs.py    # dialog behaviour
├── test_main_window.py  # 58 main window tests
├── test_spellcheck.py   # 26 spellcheck tests
└── test_integration.py  # 46 end-to-end tests
```

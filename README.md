# Translation Assistant

A desktop tool for Japanese/Chinese → English translation work. Port of the original VB.NET/WPF application to Python 3 + PySide6 (Qt6), with a SQLite backend replacing the original file-based storage.

---

## Features

- Documents stored in a SQLite database (`ta.db`) next to the executable — no loose files to manage
- Organise documents into **series** with per-chapter titles and ordering
- **Open Document** dialog groups chapters by series, shows translation progress %, last-edited timestamp, live filter, delete with confirmation, and in-place metadata editing
- Displays one source line at a time; auto-copies raw text to clipboard (400 ms debounce)
- Glossary phrase-substitution from per-profile entries applied before display
- Sentence-level parse navigation (Ctrl+Left / Ctrl+Right) using configurable split characters
- Real-time spellcheck with red underlines via `pyenchant`; per-profile custom word lists
- Special Japanese/Chinese punctuation shortcuts (F1–F8)
- Progress tracking (% complete, word count, line counter) — blank paragraph markers excluded
- Auto-save every N minutes while a document is open
- Always-on-top toggle; settings persist across restarts

---

## Requirements

**Runtime**

| Package | Version | Purpose |
|---|---|---|
| Python | 3.11+ | |
| PySide6 | ≥ 6.6 | Qt6 GUI |
| pyttsx3 | ≥ 2.90 | TTS stub (deferred) |
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

`ta.db` is created in the project root on first run (next to the executable in a built dist).

---

## Testing

```bash
pytest            # run all 361 tests
pytest -q         # quiet output
```

Tests use an in-memory SQLite database and isolated `QSettings` — they never touch your real data.

---

## Building a distributable

```bash
./build.sh            # runs pytest, then PyInstaller
./build.sh --skip-tests
```

Output: `dist/TranslationAssistant/` — copy this folder to the target machine. No Python installation required. `ta.db` is created next to the executable on first launch.

---

## Document format (internal)

Documents are stored in SQLite. The underlying text format (used during import/export) is:

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
- `$` marks continuation sentences (displayed grouped in the review panels)
- Blank lines between paragraphs are stored as bare `%` markers and are skipped during navigation and excluded from progress calculation

Create a new document via **File → New** (Ctrl+N). Specify Series Title, Series Order, and Chapter Title to group related chapters together.

---

## Profiles

Profiles are stored in the SQLite database. Each profile has a glossary (phrase → translation pairs) and a custom spellcheck word list.

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
| Ctrl+S | Save |
| Ctrl+O | Open document |
| Ctrl+N | New document |
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
├── core.py            # pure text-processing logic (no Qt)
├── db.py              # Database class — all SQLite CRUD
├── settings.py        # QSettings wrapper (typed getters/setters)
├── spellcheck.py      # QSyntaxHighlighter + pyenchant
├── tts.py             # TTS stub
└── ui/
    ├── main_window.py       # QMainWindow
    ├── dlg_new.py           # New document dialog
    ├── dlg_open.py          # Open document dialog (grouped tree view)
    ├── dlg_phrase.py        # Add phrase dialog
    ├── dlg_profile.py       # Profile manager dialog
    └── dlg_profile_name.py  # Profile name input dialog
tests/
├── conftest.py
├── test_core.py         # pure logic
├── test_db.py           # database CRUD
├── test_settings.py     # settings persistence
├── test_dialogs.py      # dialog behaviour
├── test_dlg_open.py     # open document dialog
├── test_main_window.py  # main window
├── test_spellcheck.py   # spellcheck
└── test_integration.py  # end-to-end
```

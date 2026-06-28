# Translation Assistant

A desktop tool for Japanese/Chinese → English translation work. Port of the original VB.NET/WPF application to Python 3 + PySide6 (Qt6), with a SQLite backend replacing the original file-based storage.

---

## Features

- Documents stored in a SQLite database (`ta.db`) next to the executable — no loose files to manage
- Organise documents into **series** with per-chapter titles and ordering
- **Open Document** dialog groups chapters by series, shows translation progress %, last-edited timestamp, live filter, delete with confirmation, and in-place metadata editing
- **Syosetu batch importer** — paste a series URL, pick chapters, fetch them all at once with rate limiting
- **Translation memory** panel — suggests matching translations from previously translated lines; collapsible in the 2D workspace layout
- Displays one source line at a time; auto-copies raw text to clipboard (400 ms debounce)
- Restores the last opened document on startup
- Glossary phrase-substitution from per-profile entries applied before display
- Sentence-level parse navigation (Ctrl+Left / Ctrl+Right) using configurable split characters
- Real-time spellcheck with red underlines via `pyenchant`; per-profile custom word lists
- Special Japanese/Chinese punctuation shortcuts (F1–F8)
- Progress tracking (% complete, word count, line counter) — blank paragraph markers excluded
- Auto-save every N minutes while a document is open
- Always-on-top toggle; settings persist across restarts
- Import / export individual documents to the original TXT format
- Database backup and restore (full `ta.db` copy)
- **Setup Guide** dialog walks through MeCab and JParser installation on first launch
- **Usage statistics** — heatmap calendar and per-day table showing lines translated (**Help → Statistics**)
- **Ollama translator** — local LLM translation via a running Ollama instance; configurable model and system prompt; streams tokens into the aggregator panel
- **WordPress publisher** — publish a completed chapter to a WordPress site via the REST API; status check and safeguard prevent accidental re-publishing; configure via **File → WordPress Settings**
- **Customizable keyboard shortcuts** — rebind any action via **Settings → Customize Shortcuts**
- **Dark theme** — global QSS stylesheet with card panels and high-contrast source text
- **2D workspace layout** — nested splitters place the TA widget, aggregator, and TM panel in a single unified window

---

## Requirements

**Runtime**

| Package | Version | Purpose |
|---|---|---|
| Python | 3.11+ | |
| PySide6 | ≥ 6.6 | Qt6 GUI |
| pyenchant | ≥ 3.2 | Spellcheck |
| requests | ≥ 2.28 | Syosetu scraper |
| beautifulsoup4 | ≥ 4.12 | Syosetu scraper |
| httpx | ≥ 0.27 | Ollama / LibreTranslate HTTP |

**System libraries (Linux)**

```bash
sudo apt install libenchant-2-dev hunspell-en-us
```

On macOS: `brew install enchant`  
On Windows: install the `pyenchant` wheel — enchant is bundled.

**Optional: Translation Aggregator panels**

| Panel | What to install |
|---|---|
| MeCab | `pip install fugashi unidic-lite` |
| JParser | Download `edict2` from [edrdg.org](https://www.edrdg.org/jmdict/edict.html) → place at `dictionaries/edict2` |
| Ollama | Install [Ollama](https://ollama.com) and pull a model (e.g. `ollama pull gemma3`) |

Without these, the panels display setup instructions instead of output.

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
pytest            # run all 739 tests
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

Pre-built releases (AppImage for Linux, NSIS installer for Windows) are produced by the GitHub Actions release workflow on tagged commits.

---

## Importing from Syosetu

1. **File → Manage Series** — create or select a series, then click **Fetch from Syosetu**
2. Paste the series index URL (e.g. `https://ncode.syosetu.com/n…/`)
3. The dialog loads the chapter list; tick the chapters to import
4. Click **Fetch Selected** — chapters are fetched with rate limiting and saved to the database

---

## Ollama translator

With [Ollama](https://ollama.com) running locally:

1. Pull a model: `ollama pull gemma3` (or any chat model)
2. Open **Settings → Aggregator Settings** and enable **Ollama**
3. Set the URL (`http://localhost:11434`) and model name
4. Optionally customise the system prompt
5. The Ollama panel in the aggregator streams the response as tokens arrive

---

## Document format (import/export)

The TXT format used by **File → Import / Export** is:

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

Create a new document via **File → New Document** (Ctrl+N). Specify Series Title, Series Order, and Chapter Title to group related chapters together. Create a standalone series entry via **File → New Series**.

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
| Ctrl+G | Go to specific line number |
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

- **TTS** — the original used `Microsoft.Speech` (Windows-only). TTS is not implemented in this port; `espeak-ng` on Linux has limited Japanese/Chinese voice support.
- **Spellcheck on Linux** requires the system `libenchant-2` and a Hunspell dictionary package installed separately (see Setup above).

---

## Project structure

```
translation_assistant/
├── main.py            # entry point
├── core.py            # pure text-processing logic (no Qt)
├── db.py              # Database class — all SQLite CRUD
├── migration.py       # DB schema migrations
├── scraper.py         # Syosetu HTTP scraper + worker threads
├── settings.py        # QSettings wrapper (typed getters/setters)
├── spellcheck.py      # QSyntaxHighlighter + pyenchant
├── wp_publisher.py    # WordPress REST API client (no Qt)
└── ui/
    ├── combined_window.py   # QMainWindow shell (menu bar + central widget)
    ├── main_widget.py       # Main application widget (state, navigation, actions)
    ├── dlg_new.py           # New document dialog
    ├── dlg_new_series.py    # New series dialog
    ├── dlg_open.py          # Open document dialog (grouped tree view)
    ├── dlg_fetch_series.py  # Syosetu batch import dialog
    ├── dlg_batch_import.py  # Batch file import dialog
    ├── dlg_series.py        # Series manager dialog
    ├── dlg_series_phrases.py # Series phrase suggestions dialog
    ├── dlg_stats.py         # Usage statistics (heatmap + table)
    ├── dlg_setup.py         # Setup guide dialog (MeCab / JParser)
    ├── dlg_shortcuts.py     # Keyboard shortcut customisation dialog
    ├── dlg_phrase.py        # Add phrase dialog
    ├── dlg_profile.py       # Profile manager dialog
    ├── dlg_profile_name.py  # Profile name input dialog
    └── dlg_wp_settings.py   # WordPress endpoint / credentials dialog
ta/                          # Translation Aggregator module
├── config/                  # Language and translator settings
├── core/                    # Clipboard, filter, history, substitutions
├── translators/             # Bing, DeepL, Google, JParser, LibreTranslate, MeCab, Ollama
└── ui/
    ├── aggregator_widget.py # Aggregator panel embedded in CombinedMainWindow
    ├── panels_container.py  # Translator panel layout
    ├── source_panel.py      # Source text display
    ├── translation_panel.py # Per-translator output panel (supports streaming)
    └── dialogs/             # Aggregator settings, history, substitutions dialogs
tests/
├── conftest.py
├── test_core.py              # pure logic
├── test_db.py                # database CRUD
├── test_migration.py         # schema migration
├── test_settings.py          # settings persistence
├── test_dialogs.py           # dialog behaviour
├── test_dlg_open.py          # open document dialog
├── test_dlg_new_series.py    # new series dialog
├── test_dlg_series_phrases.py # series phrase suggestions
├── test_combined_window.py   # main window shell
├── test_main_window.py       # main widget
├── test_scraper.py           # scraper
├── test_spellcheck.py        # spellcheck
├── test_ollama.py            # Ollama translator
├── test_wp_publisher.py      # WordPress publisher
└── test_integration.py       # end-to-end
```

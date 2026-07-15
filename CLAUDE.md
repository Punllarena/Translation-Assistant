# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Activate venv (required before any command)
source .venv/bin/activate

# Run the application
python -m translation_assistant.main

# Run all tests
pytest

# Run a single test file
pytest tests/test_core.py -q

# Run a single test by name
pytest tests/test_core.py::test_parse_file_content_basic -q

# Build distributable (runs tests first)
./build.sh
./build.sh --skip-tests   # skip tests when iterating on the spec
```

System dependency for spellcheck on Linux: `sudo apt install libenchant-2-dev hunspell-en-us`

## Architecture

### Entry point and window hierarchy

```
main.py
  └── CombinedMainWindow          # ui/combined_window.py — the actual QMainWindow
        ├── TranslationAssistantWidget   # ui/main_widget.py — all TA logic as QWidget
        └── AggregatorWidget             # ta/ui/aggregator_widget.py — machine translation panel
```

**`main.py` creates `CombinedMainWindow`, not `MainWindow`.** `ui/main_window.py` is an older standalone window that is no longer launched. Do not add features to `main_window.py` — use `main_widget.py` and `combined_window.py` instead.

**Menu bar pattern.** `CombinedMainWindow._setup_menubar()` builds the entire menu bar. It pulls actions from `TranslationAssistantWidget` (e.g. `ta.action_save`, `ta.action_stats`) — actions are constructed in `TranslationAssistantWidget._build_actions()`. To add a new menu item: add a `QAction` in `_build_actions`, then reference it in `_setup_menubar`.

**Status bar.** `TranslationAssistantWidget` owns a `QStatusBar` embedded in its layout (not the QMainWindow status bar). Add status bar widgets in `TranslationAssistantWidget._setup_statusbar()`.

### Module layout

```
translation_assistant/
├── main.py              # entry point — creates CombinedMainWindow
├── core.py              # ALL pure text logic (no Qt); safe to unit test without a display
├── db.py                # Database class — all SQLite CRUD; _conn injection seam for tests
├── settings.py          # QSettings wrapper with typed getters/setters; owns profile dir helpers
├── migration.py         # one-time CSV/LEX → SQLite importer (run_startup_migration)
├── scraper.py           # syosetu.com FetchWorker (QThread)
├── spellcheck.py        # QSyntaxHighlighter subclass using pyenchant
└── ui/
    ├── combined_window.py      # CombinedMainWindow — THE running QMainWindow
    ├── main_widget.py          # TranslationAssistantWidget — all TA logic as QWidget
    ├── card_list.py            # CardListView + LineCard — whole-chapter card editor
    ├── main_window.py          # LEGACY standalone window — not launched, do not modify
    ├── dlg_new.py              # New-document dialog
    ├── dlg_new_series.py       # Batch new-series dialog
    ├── dlg_open.py             # Document picker (replaces QFileDialog)
    ├── dlg_phrase.py           # Add-phrase dialog
    ├── dlg_profile.py          # Profile manager
    ├── dlg_profile_name.py     # Profile name input
    ├── dlg_series.py           # Series manager
    ├── dlg_series_phrases.py   # Series phrase suggestions
    ├── dlg_stats.py            # Usage statistics (HeatmapWidget + StatsDialog)
    ├── dlg_fetch_series.py     # Batch syosetu fetch
    ├── dlg_batch_import.py     # Batch import from files
    └── dlg_setup.py            # First-run setup wizard
```

### Key design decisions

**`core.py` is framework-agnostic.** Every text-processing function takes plain Python types and returns plain Python types. No Qt imports. This makes them trivially testable.

**`db.py` is the single SQLite access point.** All reads and writes go through the `Database` class. The constructor accepts `_conn: sqlite3.Connection | None` — tests pass an in-memory connection, production uses the file at `settings.db_path`. Never import `sqlite3` outside `db.py` — with one sanctioned exception: `ta/core/history.py`, the aggregator's standalone history/MT-cache store (`~/.local/share/ta-python/history.db`), kept separate so the aggregator stays self-contained.

**Schema migrations are idempotent.** `Database._apply_schema()` applies `ALTER TABLE` migrations using `PRAGMA table_info` checks. Adding a column: check if it exists first, then `ALTER TABLE … ADD COLUMN`. This pattern is safe to run on existing databases.

**`AppSettings` injection seam.** The constructor accepts `_qs: QSettings | None`. Tests pass a temp-file-backed `QSettings` instance; production uses `QSettings("joeglens", "TranslationAssistant")`. Never write to `QSettings` directly — always go through `AppSettings`.

**`SpellHighlighter` injection seam.** The constructor accepts `_dict` to replace the real enchant dictionary in tests. Pass any object with `check(word) -> bool` and `suggest(word) -> list`.

**Event routing.** All key presses in `TranslationAssistantWidget` route through `_handle_key` via an event filter on the widget.

**File format (legacy import only).** The `---SEPERATOR---` (intentional typo from original) marker divides source text from translations. Raw lines are prefixed with `%` (paragraph start) or `$` (continuation). Documents are now stored in SQLite; the TXT format is only used for import/export.

**Clipboard debounce.** A 400 ms single-shot `QTimer` delays clipboard writes. Rapid navigation restarts the timer instead of flooding the clipboard.

### Testing

Tests use shared fixtures from `conftest.py`:
- `qapp` (session-scoped) — single `QApplication` for the session
- `tmp_settings` — `AppSettings` backed by a temp INI file with a temp profile dir

DB tests use in-memory SQLite via `Database(":memory:", _conn=conn)`.

Test files: `test_core.py`, `test_db.py`, `test_settings.py`, `test_dialogs.py`, `test_spellcheck.py`, `test_main_window.py`, `test_combined_window.py`, `test_card_list.py`, `test_integration.py`, `test_migration.py`, `test_dlg_open.py`, `test_dlg_new_series.py`, `test_dlg_series_phrases.py`, `test_scraper.py`. Total: 898 tests.

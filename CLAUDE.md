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

### Module layout

```
translation_assistant/
├── main.py          # entry point — creates QApplication + MainWindow
├── core.py          # ALL pure text logic (no Qt); safe to unit test without a display
├── settings.py      # QSettings wrapper with typed getters/setters; also owns profile dir helpers
├── spellcheck.py    # QSyntaxHighlighter subclass using pyenchant
├── tts.py           # stub (pyttsx3 wired but menu items disabled; TTS deferred)
└── ui/
    ├── main_window.py      # QMainWindow — the entire application state lives here
    ├── dlg_new.py          # New-file dialog (calls core.build_new_file)
    ├── dlg_phrase.py       # Add-phrase dialog (appends to profile CSV)
    ├── dlg_profile.py      # Profile manager (QComboBox + editable QTableWidget)
    └── dlg_profile_name.py # Profile name input (sanitises forbidden filename chars)
```

### Key design decisions

**`core.py` is framework-agnostic.** Every text-processing function (`parse_file_content`, `build_new_file`, `save_file`, `replace_and_parse`, `build_review_text`, `calculate_progress`, `build_clipboard_output`, `load_glossary`) takes plain Python types and returns plain Python types. No Qt imports. This makes them trivially testable and is the deliberate split between logic and UI.

**`AppSettings` injection seam.** The constructor accepts `_qs: QSettings | None`. Tests pass a temp-file-backed `QSettings` instance; production uses `QSettings("joeglens", "TranslationAssistant")`. Never write to `QSettings` directly — always go through `AppSettings`.

**`SpellHighlighter` injection seam.** The constructor accepts `_dict` to replace the real enchant dictionary in tests. Pass any object with `check(word) -> bool` and `suggest(word) -> list`.

**Event routing.** All key presses (Enter, PgDn, PgUp, Ctrl+*, F1–F8) in `MainWindow` route through a single `_handle_key` method via an event filter installed on the `QMainWindow`. This mirrors the VB original's `PreviewKeyDown` approach.

**File format.** The `---SEPERATOR---` (note: intentional typo from original) marker divides source text from translations. Raw lines are prefixed with `%` (paragraph start) or `$` (continuation). The raw section is preserved verbatim on save — `save_file` never touches it. Empty lines in the raw section produce blank lines in review panels and are skipped during navigation.

**Clipboard debounce.** A 400 ms single-shot `QTimer` delays `_write_to_clipboard`. Rapid navigation restarts the timer instead of flooding the clipboard.

**Profile directory.** `settings.get_profile_dir()` is the single source of truth. In dev it resolves to `<repo_root>/Profile/`; in a PyInstaller bundle it resolves to `<exe_dir>/Profile/` via `sys.frozen` detection.

### Testing

Tests use two shared fixtures from `conftest.py`:
- `qapp` (session-scoped) — single `QApplication` for the session
- `tmp_settings` — `AppSettings` backed by a temp INI file with a temp profile dir; uses `monkeypatch` on `_get_app_root`

Test files map to modules: `test_core.py` (55), `test_settings.py`, `test_dialogs.py`, `test_spellcheck.py` (26), `test_main_window.py` (58), `test_integration.py` (46). Total: 236 tests.

### Planned work: SQLite migration (`SQLITE_PLAN.md`)

A planned migration (not yet started) will replace filesystem-based profile storage (`Profile/*.csv`, `Profile/*.lex`) and TXT-file documents with a single SQLite database (`ta.db`). The plan introduces:
- A new `db.py` module (`Database` class) with all CRUD; accepts `_conn` injection seam for in-memory tests
- `dlg_open.py` document picker replacing `QFileDialog`
- `File → Import / Export` for the old TXT format (retaining interop)
- `filepath`/`txt_output` state in `MainWindow` replaced by `_doc_id: int | None`

Stages A–G are defined in `SQLITE_PLAN.md`. Each stage must leave the test suite green before the next begins. `core.py` pure functions are unchanged by the migration.

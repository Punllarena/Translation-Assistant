# SQLite Migration Plan

Move profile data (glossary CSVs, custom word LEX files) and translation documents (TXT files) from the filesystem into a single SQLite database.

---

## Motivation

| Current | Problem |
|---|---|
| Glossary in `Profile/*.csv` | Partial write on crash corrupts the active profile |
| Custom words in `Profile/*.lex` | Same fragility; no deduplication |
| Documents as `*.txt` files | User must remember where files are saved; no metadata |
| Profile directory on disk | Platform-specific path; can get out of sync with QSettings |

SQLite gives us:
- **Atomic saves** — transactions mean a crash can't corrupt data
- **Single backup file** — one `ta.db` file contains everything
- **Document library** — open recent, search across documents without a file picker
- **Richer metadata** — created/modified timestamps, word count cache, notes
- **Simpler profile CRUD** — no filesystem rename/delete edge cases

The `---SEPERATOR---` text format is still retained as an **import/export** format for file sharing. It is no longer the storage format.

---

## Database location

```
~/.local/share/joeglens/TranslationAssistant/ta.db   (Linux)
~/Library/Application Support/joeglens/TranslationAssistant/ta.db  (macOS)
%APPDATA%\joeglens\TranslationAssistant\ta.db   (Windows)
```

Use `QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)` to resolve this at runtime — it already respects the platform convention and is aware of PyInstaller bundles.

`QSettings` continues to store window-level preferences (geometry, on_top, tts, auto_save, show_progress). It does **not** store profile data or document paths — those move to SQLite.

---

## Schema

```sql
PRAGMA journal_mode = WAL;   -- safe concurrent reads during auto-save
PRAGMA foreign_keys = ON;

-- ── Profiles ────────────────────────────────────────────────────────────────

CREATE TABLE profiles (
    id          INTEGER PRIMARY KEY,
    name        TEXT    UNIQUE NOT NULL,
    parse_chars TEXT    NOT NULL
                        DEFAULT '、 。 ？ ！ 「 」 …… ',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    is_default  INTEGER NOT NULL DEFAULT 0  -- only one row should have 1
);

-- ── Glossary (was ProfileName.csv) ──────────────────────────────────────────

CREATE TABLE glossary (
    id          INTEGER PRIMARY KEY,
    profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    phrase      TEXT    NOT NULL,
    translation TEXT    NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(profile_id, phrase)
);

CREATE INDEX idx_glossary_profile ON glossary(profile_id, sort_order);

-- ── Custom spellcheck words (was ProfileName.lex) ───────────────────────────

CREATE TABLE custom_words (
    id          INTEGER PRIMARY KEY,
    profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    word        TEXT    NOT NULL COLLATE NOCASE,
    UNIQUE(profile_id, word)
);

CREATE INDEX idx_words_profile ON custom_words(profile_id);

-- ── Documents (was *.txt files) ─────────────────────────────────────────────

CREATE TABLE documents (
    id              INTEGER PRIMARY KEY,
    title           TEXT    NOT NULL,         -- display name (no extension)
    source_language TEXT    NOT NULL DEFAULT 'ja',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    last_position   INTEGER NOT NULL DEFAULT 0  -- remembered array_pointer
);

-- ── Lines (was individual lines inside the TXT file) ────────────────────────

CREATE TABLE lines (
    id              INTEGER PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    line_number     INTEGER NOT NULL,   -- 0-based; determines display order
    prefix          TEXT    NOT NULL DEFAULT '%',  -- '%' or '$'
    raw_text        TEXT    NOT NULL,
    translated_text TEXT    NOT NULL DEFAULT '',
    UNIQUE(document_id, line_number)
);

CREATE INDEX idx_lines_document ON lines(document_id, line_number);

-- ── Schema version (for future migrations) ──────────────────────────────────

CREATE TABLE schema_version (
    version INTEGER NOT NULL
);
INSERT INTO schema_version VALUES (1);
```

### Design decisions

- **`prefix` as its own column** — instead of embedding `%`/`$` in `raw_text`, store it separately. `core.py` functions that currently strip markers get simpler.
- **Profiles are not bound to documents** — the active profile is a user preference stored in QSettings (`ProfileUsed` key stays). A document opened with profile A can be re-read with profile B; the glossary substitution is applied at load time, not stored.
- **`last_position`** — the window can restore scroll position when reopening a document without needing a separate recent-files list.
- **`is_default` flag** — the Default profile is distinguished by a flag, not by its name, so it can be renamed without breaking logic.
- **No `file_path` column** — documents imported from TXT files do not retain the source path. If re-export is needed the user uses File → Export. This avoids stale-path confusion.

---

## New module: `db.py`

All database access is centralised here. Nothing else imports `sqlite3` directly.

```python
# translation_assistant/db.py

class Database:
    def __init__(self, path: Path | str, *, _conn=None) -> None:
        """
        path  — filesystem path to the .db file (created if absent).
        _conn — injection seam: pass an in-memory sqlite3.Connection for tests.
        """

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def close(self) -> None: ...

    # ── Profiles ─────────────────────────────────────────────────────────────

    def list_profiles(self) -> list[str]: ...
    def get_profile_id(self, name: str) -> int | None: ...
    def create_profile(self, name: str) -> int: ...         # returns new id
    def rename_profile(self, old: str, new: str) -> None: ...
    def delete_profile(self, name: str) -> None: ...        # raises if is_default

    # ── Glossary ─────────────────────────────────────────────────────────────

    def get_glossary(self, profile: str) -> list[tuple[str, str]]: ...
    def set_glossary(self, profile: str, rows: list[tuple[str, str]]) -> None:
        # Replaces all rows in a single transaction.
        ...
    def add_phrase(self, profile: str, phrase: str, translation: str) -> None: ...
    def delete_phrase(self, profile: str, phrase: str) -> None: ...

    # ── Custom words ─────────────────────────────────────────────────────────

    def get_custom_words(self, profile: str) -> list[str]: ...
    def add_word(self, profile: str, word: str) -> None: ...  # idempotent

    # ── Documents ────────────────────────────────────────────────────────────

    def list_documents(self) -> list[dict]: ...
        # Returns [{id, title, updated_at, last_position}, ...]
    def create_document(self, title: str) -> int: ...         # returns doc id
    def delete_document(self, doc_id: int) -> None: ...
    def get_document(self, doc_id: int) -> dict: ...          # title, position, …
    def set_last_position(self, doc_id: int, pos: int) -> None: ...

    # ── Lines ─────────────────────────────────────────────────────────────────

    def get_lines(self, doc_id: int) -> list[dict]: ...
        # Returns [{line_number, prefix, raw_text, translated_text}, ...]
    def save_lines(self, doc_id: int, lines: list[dict]) -> None:
        # Full replace in a single transaction; touches updated_at on document.
        ...
    def save_translation(self, doc_id: int, line_number: int, text: str) -> None:
        # Partial update — only one translated_text cell; used by auto-save.
        ...
```

**Test seam:** `_conn` accepts a `sqlite3.Connection` (typically `:memory:`). Tests pass `sqlite3.connect(":memory:")` — no temp files, no `monkeypatch`.

---

## Changes to existing modules

### `settings.py`

Remove:
- `get_profile_dir()`, `ensure_profile_defaults()`, `profile_dir` property — filesystem profile management moves to `db.py`

Keep:
- `AppSettings` with `QSettings` for: `parse_char`, `profile_used`, `show_progress`, `auto_save`, `on_top`, `tts`, `tts_lang`

Add:
- `db_path` property — returns the platform-appropriate path for `ta.db`

### `core.py`

The pure functions stay unchanged. They operate on `list[str]` / `str`; the DB is not their concern.

**Add two conversion helpers** (used by import/export, not by normal operation):

```python
def lines_to_db_rows(raw_lines: list[str], translated_lines: list[str]) -> list[dict]:
    """Convert the in-memory arrays to the shape expected by db.save_lines()."""

def db_rows_to_arrays(rows: list[dict]) -> tuple[list[str], list[str]]:
    """Convert db.get_lines() output back to (raw_lines, translated_lines).
    
    Prefixes ('%'/'$') are prepended to raw_text for compatibility with the
    existing parse/display functions.
    """
```

### `main_window.py`

**Opening a document:**
- `File → Open` shows a document picker dialog (list of documents from `db.list_documents()`) instead of `QFileDialog`
- `File → Import` retains `QFileDialog` for reading the old TXT format; calls `core.parse_file_content` then `db.create_document` + `db.save_lines`

**Saving a document:**
- `_navigate_forward` calls `db.save_translation(doc_id, line_number, text)` — single row update, no full-file write
- `Ctrl+S` / auto-save calls `db.save_lines(doc_id, all_lines)` — full flush in one transaction
- The "File saved…" status message still applies after either save

**State variables:**
- `filepath: Path | None` → `_doc_id: int | None`
- `txt_output: str` (raw_section for save round-trip) — **removed**; the DB owns the raw text

**Spell check:**
- `_load_spell_dict` calls `db.get_custom_words(profile)` instead of reading a `.lex` file
- `_add_to_dictionary` calls `db.add_word(profile, word)` instead of appending to a file

### Dialogs

**`dlg_profile.py`**
- Glossary table populated from `db.get_glossary(profile)` instead of reading a CSV
- Save calls `db.set_glossary(profile, rows)` instead of writing a CSV
- New / Delete / Rename call the corresponding `db.*_profile()` methods

**`dlg_phrase.py`**
- On accept: calls `db.add_phrase(profile, phrase, translation)` instead of appending to a CSV
- Return value changes from CSV content string to nothing (DB is the source of truth)

**New: `dlg_open.py`** (document picker)
- `QDialog` with a `QListWidget` or `QTableWidget` showing `db.list_documents()`
- Columns: Title, Last modified, Lines
- Buttons: Open, Delete, Cancel
- Double-click opens immediately

---

## Import / Export

These are standalone functions in `core.py` (or a new `io.py`). They use the existing file format so files can still be shared.

```python
def import_txt(path: Path, db: Database, title: str | None = None) -> int:
    """Read a ---SEPERATOR--- file and create a new document. Returns doc_id."""

def export_txt(doc_id: int, path: Path, db: Database) -> None:
    """Write a document back to the ---SEPERATOR--- file format."""
```

Menu items:
- `File → Import from file…` replaces `File → Open` (old behaviour)
- `File → Export to file…` replaces `File → Save As` (old behaviour)
- `File → Open` now opens the document picker

---

## Migration

A one-time migration runs on first startup after the update, before the main window opens:

```python
def migrate_files_to_db(profile_dir: Path, db: Database) -> None:
    """
    Import all CSV and LEX files from an existing Profile/ directory into the DB.
    Idempotent: skips profiles that already exist in the DB.
    Does NOT delete the source files (user can do that manually).
    """
    for csv_path in sorted(profile_dir.glob("*.csv")):
        name = csv_path.stem
        if db.get_profile_id(name) is not None:
            continue
        profile_id = db.create_profile(name)
        rows = core.load_glossary(csv_path)
        db.set_glossary(name, rows)

        lex_path = profile_dir / f"{name}.lex"
        if lex_path.exists():
            words = [
                line.strip() for line in lex_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            ]
            for word in words:
                db.add_word(name, word)
```

TXT documents are **not** auto-imported — there is no canonical list of which TXT files belong to the app. The user imports them explicitly via File → Import.

---

## Testing strategy

### `tests/test_db.py`

All `Database` tests use an in-memory connection:

```python
@pytest.fixture
def db():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    return Database(":memory:", _conn=conn)
```

Cover:
- Schema creation (tables exist after `__init__`)
- Profile CRUD (create, list, rename, delete, default cannot be deleted)
- Glossary round-trip (set then get returns same rows in same order)
- Custom words (add, dedup via UNIQUE, get)
- Document CRUD (create, list, delete cascades to lines)
- Lines round-trip (save then get returns correct prefix/raw/translated)
- `save_translation` updates exactly one cell, leaves others unchanged
- Migration function imports CSV + LEX files correctly

### `tests/test_integration.py`

Replace the file-backed fixtures with a DB-backed fixture:

```python
@pytest.fixture
def db(tmp_path):
    import sqlite3
    return Database(tmp_path / "ta.db")

@pytest.fixture
def win(qapp, tmp_path, monkeypatch, db):
    settings = _make_settings(tmp_path, monkeypatch)
    w = MainWindow(_settings=settings, _db=db)
    yield w
    w.destroy()
```

`MainWindow.__init__` gains a `_db: Database | None = None` injection seam (mirrors the existing `_settings` seam).

Existing end-to-end tests that load content via `win.load_content(text)` will be updated to use `db.create_document` + `db.save_lines` + `win.open_document(doc_id)`.

---

## Stage breakdown

| Stage | Work | Notes |
|---|---|---|
| A — Schema + `db.py` | Write `Database` class with full CRUD; `tests/test_db.py` | No UI changes yet; all existing tests still pass |
| B — Settings update | Add `db_path` to `AppSettings`; remove filesystem profile helpers | `settings.py` gets smaller |
| C — Migration utility | `migrate_files_to_db`; run once on startup; write `tests/test_migration.py` | Existing Profile/ files kept as backup |
| D — Profile dialogs | Rewrite `dlg_profile.py` and `dlg_phrase.py` to use DB | Spellcheck `_load_spell_dict` updated too |
| E — Document open/save | Replace file open/save in `MainWindow` with DB calls; add `dlg_open.py` | Biggest change; `_doc_id` replaces `filepath` |
| F — Import/Export | Add `File → Import` / `File → Export` menu items; keep TXT round-trip | Preserves interop with old files |
| G — Tests & cleanup | Update all fixtures; delete filesystem profile helpers; remove `Profile/*.csv` from build | Final pass |

Each stage is a self-contained PR that leaves the test suite green.

---

## Open questions

1. **Document titles** — use the original filename (without extension) as the title on import? Allow renaming inside the app? A title column with a rename action in `dlg_open.py` is the cleanest approach.

2. **`parse_chars` per document vs per profile** — currently `parse_char` is a single app-wide setting. The schema puts it on the profile. If a user translates Japanese with one profile and Chinese with another, they get different parse chars automatically. Is that desirable?

3. **Multi-document workflow** — should the app support having multiple documents open in tabs, or remain single-document? SQLite makes tabs trivial to add later (just open a second `_doc_id`), but the current UI is single-document. Recommend keeping it single-document for now.

4. **Backup strategy** — SQLite WAL mode protects against corruption, but users may still want a backup. Consider a `File → Export all…` that dumps every document to a zip of TXT files.

# Batch Import Design

**Date:** 2026-06-16
**Status:** Approved

## Overview

Add a "Import Folder…" action to the File menu that imports an entire folder of `---SEPERATOR---` TXT files into the DB, optionally grouping them as a series and importing a glossary profile from a CSV file found in the folder.

## Requirements

- User picks a folder via directory picker
- All `*.txt` files in the folder are imported as documents, sorted alphabetically (sort order becomes series chapter order)
- Series name field is pre-filled with folder name; user can edit or clear (blank = ungrouped)
- If a single `*.csv` file exists in the folder, it is imported as a glossary profile (named after the CSV stem) and linked to the series
- Files whose title (stem) already exists in the DB are skipped (no overwrite)
- After import, a summary is shown in-place: count of imported, skipped, and errored files, with file names listed for skipped and errored entries
- No progress dialog; import runs synchronously

## Architecture

### Files changed

| File | Change |
|---|---|
| `translation_assistant/core.py` | Add `batch_import_folder()` |
| `translation_assistant/ui/dlg_batch_import.py` | New `BatchImportDialog` |
| `translation_assistant/ui/main_widget.py` | Add `action_batch_import` + `_on_batch_import()` |
| `translation_assistant/ui/combined_window.py` | Wire action into File menu |

### `core.batch_import_folder`

```python
def batch_import_folder(
    folder: Path,
    db,
    *,
    series_title: str = "",
) -> dict:
    ...
```

Returns `{"imported": [str], "skipped": [str], "errors": [(str, str)]}`.

**Logic:**
1. Collect `folder/*.txt`, sort by name. Each file's series_order = its index in the sorted list.
2. Detect a single `*.csv` in the folder. If found:
   - `load_glossary(csv_path)` → pairs
   - Profile name = CSV stem
   - `db.create_profile(profile_name)` if not exists
   - `db.set_glossary(profile_name, pairs)`
   - If `series_title` is non-empty: `db.set_series_profile(series_title, profile_name)`
3. Build existing title set: `{d["title"] for d in db.list_documents()}`
4. For each TXT in sorted order:
   - If stem in existing titles → append stem to `skipped`, continue
   - Else: call `import_txt(path, db, title=stem, series_title=series_title, series_order=i)` → append stem to `imported`
   - Note: `import_txt` must be extended to accept `series_title: str = ""` and `series_order: int = 0` kwargs (currently only accepts `title`)
   - On exception → append `(stem, str(e))` to `errors`
5. Return summary dict.

Framework-agnostic. No Qt imports.

### `BatchImportDialog`

Modal `QDialog`. Two phases rendered in a single `QStackedWidget` (or by showing/hiding widget groups).

**Phase 1 — Input:**
- Folder path label + "Browse…" button (`QFileDialog.getExistingDirectory`)
- Series name `QLineEdit`, pre-filled with folder name when folder is chosen; editable; clearable
- "Import" `QPushButton`, disabled until a folder is selected

**Phase 2 — Summary (replaces Phase 1 content in-place):**
- "Import complete." header label
- Counts: Imported N / Skipped M / Errors K
- Skipped file names (if any), one per line
- Error file names + messages (if any), one per line
- "Close" button (calls `accept()`)

Constructor signature: `BatchImportDialog(db: Database, settings: AppSettings, parent=None)`

The dialog calls `core.batch_import_folder(folder, db, series_title=series_title)` on the Import button click.

### `main_widget.py`

In `_build_actions()`:
```python
self.action_batch_import = QAction("Import Folder…", self)
self.action_batch_import.triggered.connect(self._on_batch_import)
```

New handler:
```python
def _on_batch_import(self) -> None:
    from translation_assistant.ui.dlg_batch_import import BatchImportDialog
    dlg = BatchImportDialog(self._db, self._settings, parent=self)
    dlg.exec()
```

### `combined_window.py`

Add after `action_import` in File menu:
```python
file_menu.addAction(ta.action_batch_import)
```

## Data Flow

```
User picks folder
  → dialog pre-fills series name with folder.name
  → user edits/clears series name
  → clicks Import
    → core.batch_import_folder(folder, db, series_title=series_title)
      → scans *.txt (sorted)
      → detects *.csv → create/update profile + link to series
      → per TXT: skip if title exists, else import_txt()
      → returns summary dict
  → dialog switches to summary phase
  → user clicks Close
```

## Error Handling

- Missing separator in a TXT file: caught as `ValueError`, recorded in `errors`
- Unreadable file (permissions, encoding): caught as `OSError` / `UnicodeDecodeError`, recorded in `errors`
- Multiple CSV files in folder: skip CSV import entirely, note in summary (add a `"warnings"` key to result dict)
- Empty folder (no TXT files): import completes immediately with all-zero counts

## Testing

All tests against `core.batch_import_folder` using in-memory DB:

- Import N valid TXT files → `imported` count = N, DB document count = N
- One title pre-exists → that file in `skipped`, rest imported
- One file missing separator → that file in `errors`, rest imported
- CSV present + series name given → profile created, glossary rows set, `series_profiles` row exists
- CSV present + series name blank → profile created, no `series_profiles` row
- Multiple CSVs → warning in result, no profile import
- Empty folder → all counts zero

Dialog tested manually (no dialog unit tests in this project).

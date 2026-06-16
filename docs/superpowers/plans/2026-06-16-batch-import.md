# Batch Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Import Folder…" to the File menu so users can import an entire folder of `---SEPERATOR---` TXT files as a series, with optional glossary profile from a CSV in the same folder.

**Architecture:** Extend `core.import_txt` with series params, add pure `core.batch_import_folder`, create `ui/dlg_batch_import.py`, and wire one new `QAction` in `main_widget.py` + `combined_window.py`.

**Tech Stack:** Python 3.12, PySide6, SQLite via `translation_assistant.db.Database`, pytest

---

## File Map

| File | Action |
|---|---|
| `translation_assistant/core.py` | Extend `import_txt`; add `batch_import_folder` |
| `translation_assistant/ui/dlg_batch_import.py` | Create `BatchImportDialog` |
| `translation_assistant/ui/main_widget.py` | Add `action_batch_import` + `_on_batch_import` |
| `translation_assistant/ui/combined_window.py` | Wire action into File menu |
| `tests/test_core.py` | Add `TestImportTxtSeries` + `TestBatchImportFolder` |

---

## Task 1: Extend `import_txt` to accept series params

`core.import_txt` currently calls `db.create_document(doc_title)` with no series info. It needs two new optional kwargs to support batch import.

**Files:**
- Modify: `translation_assistant/core.py` (line 154)
- Modify: `tests/test_core.py` (append to `TestImportTxt` class)

- [ ] **Step 1: Write the failing test**

Open `tests/test_core.py`. After the existing `TestImportTxt` class, add a new class:

```python
class TestImportTxtSeries:
    def _db(self):
        import sqlite3
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        return Database(":memory:", _conn=conn)

    def test_series_title_stored(self, tmp_path):
        db = self._db()
        txt = tmp_path / "ch01.txt"
        txt.write_text("%A\n---SEPERATOR---\n\n", encoding="utf-8")
        doc_id = import_txt(txt, db, series_title="My Series", series_order=0)
        docs = db.list_documents()
        assert docs[0]["series_title"] == "My Series"

    def test_series_order_stored(self, tmp_path):
        db = self._db()
        txt = tmp_path / "ch02.txt"
        txt.write_text("%B\n---SEPERATOR---\n\n", encoding="utf-8")
        doc_id = import_txt(txt, db, series_title="S", series_order=7)
        docs = db.list_documents()
        assert docs[0]["series_order"] == 7

    def test_defaults_to_no_series(self, tmp_path):
        db = self._db()
        txt = tmp_path / "ch03.txt"
        txt.write_text("%C\n---SEPERATOR---\n\n", encoding="utf-8")
        import_txt(txt, db)
        docs = db.list_documents()
        assert docs[0]["series_title"] == ""
        assert docs[0]["series_order"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate
pytest tests/test_core.py::TestImportTxtSeries -v
```

Expected: 3 FAILED — `import_txt() got an unexpected keyword argument 'series_title'`

- [ ] **Step 3: Extend `import_txt` in `core.py`**

Replace the existing `import_txt` function (lines 154–165):

```python
def import_txt(path: Path, db, title: str | None = None, *,
               series_title: str = "", series_order: int = 0) -> int:
    """Read a ---SEPERATOR--- file and create a new document in the DB.

    Returns the new document id.
    Raises ValueError if the separator is missing.
    """
    text = path.read_text(encoding="utf-8")
    raw_lines, translated_lines, _ = parse_file_content(text)
    doc_title = title if title is not None else path.stem
    doc_id = db.create_document(
        doc_title, series_title=series_title, series_order=series_order
    )
    db.save_lines(doc_id, lines_to_db_rows(raw_lines, translated_lines))
    return doc_id
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_core.py::TestImportTxtSeries tests/test_core.py::TestImportTxt -v
```

Expected: all PASS (new tests + existing `TestImportTxt` still green)

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/core.py tests/test_core.py
git commit -m "feat: extend import_txt with series_title and series_order params"
```

---

## Task 2: Add `batch_import_folder` to `core.py`

Pure function — no Qt imports. Takes a `Path` folder and a `Database`, returns a result dict.

**Files:**
- Modify: `translation_assistant/core.py` (append after `load_glossary`)
- Modify: `tests/test_core.py` (append new class)

- [ ] **Step 1: Write the failing tests**

Add `batch_import_folder` to the import at the top of `tests/test_core.py`:

```python
from translation_assistant.core import (
    SEPARATOR,
    parse_file_content,
    build_new_file,
    save_file,
    load_glossary,
    replace_and_parse,
    build_review_text,
    calculate_progress,
    build_clipboard_output,
    lines_to_db_rows,
    db_rows_to_arrays,
    import_txt,
    export_txt,
    extract_frequent_nouns,
    batch_import_folder,
)
```

Then append this class at the end of `tests/test_core.py`:

```python
class TestBatchImportFolder:
    def _db(self):
        import sqlite3
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        return Database(":memory:", _conn=conn)

    def _txt(self, folder, name, raw="%A", translation=""):
        p = folder / name
        p.write_text(f"{raw}\n---SEPERATOR---\n{translation}\n", encoding="utf-8")
        return p

    def test_imports_all_txt_files(self, tmp_path):
        db = self._db()
        self._txt(tmp_path, "ch01.txt")
        self._txt(tmp_path, "ch02.txt")
        result = batch_import_folder(tmp_path, db)
        assert len(result["imported"]) == 2
        assert len(db.list_documents()) == 2

    def test_skips_existing_title(self, tmp_path):
        db = self._db()
        self._txt(tmp_path, "ch01.txt")
        self._txt(tmp_path, "ch02.txt")
        # Pre-import ch01 so it already exists
        import_txt(tmp_path / "ch01.txt", db, title="ch01")
        result = batch_import_folder(tmp_path, db)
        assert "ch01" in result["skipped"]
        assert "ch02" in result["imported"]
        assert len(db.list_documents()) == 2  # not 3

    def test_records_error_on_bad_file(self, tmp_path):
        db = self._db()
        bad = tmp_path / "bad.txt"
        bad.write_text("No separator here", encoding="utf-8")
        result = batch_import_folder(tmp_path, db)
        assert len(result["errors"]) == 1
        assert result["errors"][0][0] == "bad"
        assert len(result["imported"]) == 0

    def test_empty_folder_returns_zeros(self, tmp_path):
        db = self._db()
        result = batch_import_folder(tmp_path, db)
        assert result == {"imported": [], "skipped": [], "errors": [], "warnings": []}

    def test_assigns_series_title_and_order(self, tmp_path):
        db = self._db()
        self._txt(tmp_path, "ch01.txt")
        self._txt(tmp_path, "ch02.txt")
        batch_import_folder(tmp_path, db, series_title="My Novel")
        docs = sorted(db.list_documents(), key=lambda d: d["series_order"])
        assert docs[0]["series_title"] == "My Novel"
        assert docs[0]["series_order"] == 0
        assert docs[1]["series_order"] == 1

    def test_csv_creates_profile_and_glossary(self, tmp_path):
        from translation_assistant.db import Database
        import sqlite3
        db = Database(":memory:", _conn=sqlite3.connect(":memory:"))
        self._txt(tmp_path, "ch01.txt")
        csv = tmp_path / "MyProfile.csv"
        csv.write_text("hello,こんにちは\nworld,世界\n", encoding="utf-8")
        batch_import_folder(tmp_path, db, series_title="S")
        assert db.get_profile_id("MyProfile") is not None
        glossary = db.get_glossary("MyProfile")
        assert ("hello", "こんにちは") in glossary
        assert db.get_series_profile("S") == "MyProfile"

    def test_csv_without_series_no_series_profile_row(self, tmp_path):
        from translation_assistant.db import Database
        import sqlite3
        db = Database(":memory:", _conn=sqlite3.connect(":memory:"))
        self._txt(tmp_path, "ch01.txt")
        csv = tmp_path / "Glossary.csv"
        csv.write_text("hi,やあ\n", encoding="utf-8")
        batch_import_folder(tmp_path, db, series_title="")
        assert db.get_profile_id("Glossary") is not None
        assert db.get_series_profile("Glossary") == ""  # no link

    def test_multiple_csvs_warns_skips_glossary(self, tmp_path):
        db = self._db()
        self._txt(tmp_path, "ch01.txt")
        (tmp_path / "A.csv").write_text("a,b\n", encoding="utf-8")
        (tmp_path / "B.csv").write_text("c,d\n", encoding="utf-8")
        result = batch_import_folder(tmp_path, db)
        assert len(result["warnings"]) == 1
        assert "Multiple CSV" in result["warnings"][0]
        assert db.get_profile_id("A") is None
        assert db.get_profile_id("B") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_core.py::TestBatchImportFolder -v
```

Expected: all FAILED — `cannot import name 'batch_import_folder' from 'translation_assistant.core'`

- [ ] **Step 3: Implement `batch_import_folder` in `core.py`**

Add after the `load_glossary` function (after line 198):

```python
def batch_import_folder(
    folder: Path,
    db,
    *,
    series_title: str = "",
) -> dict:
    """Import all ---SEPERATOR--- TXT files from folder into the DB.

    Returns {"imported": [str], "skipped": [str], "errors": [(str, str)], "warnings": [str]}.
    Skips files whose title already exists. Alphabetical order = series_order.
    If exactly one CSV found, imports it as a glossary profile.
    """
    imported: list[str] = []
    skipped: list[str] = []
    errors: list[tuple[str, str]] = []
    warnings: list[str] = []

    txt_files = sorted(folder.glob("*.txt"))
    csv_files = list(folder.glob("*.csv"))

    if len(csv_files) > 1:
        warnings.append(
            f"Multiple CSV files found ({len(csv_files)}); glossary import skipped."
        )
    elif len(csv_files) == 1:
        csv_path = csv_files[0]
        profile_name = csv_path.stem
        pairs = load_glossary(csv_path)
        if db.get_profile_id(profile_name) is None:
            db.create_profile(profile_name)
        db.set_glossary(profile_name, pairs)
        if series_title:
            db.set_series_profile(series_title, profile_name)

    existing = {d["title"] for d in db.list_documents()}

    for i, path in enumerate(txt_files):
        stem = path.stem
        if stem in existing:
            skipped.append(stem)
            continue
        try:
            import_txt(path, db, title=stem, series_title=series_title, series_order=i)
            imported.append(stem)
        except Exception as exc:
            errors.append((stem, str(exc)))

    return {"imported": imported, "skipped": skipped, "errors": errors, "warnings": warnings}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_core.py::TestBatchImportFolder tests/test_core.py::TestImportTxtSeries -v
```

Expected: all PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest -q
```

Expected: all pass (no regressions to existing tests)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/core.py tests/test_core.py
git commit -m "feat: add batch_import_folder to core"
```

---

## Task 3: Create `BatchImportDialog`

New `QDialog` in `ui/dlg_batch_import.py`. Uses a `QStackedWidget` to switch between input phase and summary phase. No unit tests — dialog tests are manual per project convention.

**Files:**
- Create: `translation_assistant/ui/dlg_batch_import.py`

- [ ] **Step 1: Create the file**

Create `translation_assistant/ui/dlg_batch_import.py` with this content:

```python
"""
Batch Import Dialog — imports a folder of TXT files into the DB.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from translation_assistant.db import Database
from translation_assistant.settings import AppSettings


class BatchImportDialog(QDialog):

    def __init__(self, db: Database, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._settings = settings
        self._folder: Path | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Import Folder")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)
        self._stack.addWidget(self._build_input_page())
        self._stack.addWidget(self._build_summary_page())

    def _build_input_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        folder_row = QHBoxLayout()
        self._folder_label = QLabel("No folder selected.")
        self._folder_label.setWordWrap(True)
        folder_row.addWidget(self._folder_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        series_row = QHBoxLayout()
        series_row.addWidget(QLabel("Series name:"))
        self._series_edit = QLineEdit()
        self._series_edit.setPlaceholderText("(leave blank for ungrouped)")
        series_row.addWidget(self._series_edit, 1)
        layout.addLayout(series_row)

        self._import_btn = QPushButton("Import")
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._on_import)
        layout.addWidget(self._import_btn)

        return page

    def _build_summary_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(QLabel("<b>Import complete.</b>"))
        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)
        layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        return page

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Import")
        if not folder:
            return
        self._folder = Path(folder)
        self._folder_label.setText(str(self._folder))
        self._series_edit.setText(self._folder.name)
        self._import_btn.setEnabled(True)

    def _on_import(self) -> None:
        from translation_assistant.core import batch_import_folder
        series_title = self._series_edit.text().strip()
        result = batch_import_folder(self._folder, self._db, series_title=series_title)

        lines = [
            f"Imported:  {len(result['imported'])}",
            f"Skipped:   {len(result['skipped'])}  (already exist)",
            f"Errors:    {len(result['errors'])}",
        ]
        if result["warnings"]:
            lines.append("")
            lines.extend(f"Warning: {w}" for w in result["warnings"])
        if result["skipped"]:
            lines.append("")
            lines.append("Skipped: " + ", ".join(result["skipped"]))
        if result["errors"]:
            lines.append("")
            for stem, msg in result["errors"]:
                lines.append(f"Error: {stem} — {msg}")

        self._summary_label.setText("\n".join(lines))
        self._stack.setCurrentIndex(1)
```

- [ ] **Step 2: Verify import works**

```bash
source .venv/bin/activate
python -c "from translation_assistant.ui.dlg_batch_import import BatchImportDialog; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add translation_assistant/ui/dlg_batch_import.py
git commit -m "feat: add BatchImportDialog"
```

---

## Task 4: Wire action in `main_widget.py` and `combined_window.py`

Add `action_batch_import` to `main_widget` and expose it in the File menu via `combined_window`.

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
- Modify: `translation_assistant/ui/combined_window.py`

- [ ] **Step 1: Add action and handler to `main_widget.py`**

In `_build_actions()`, after the `action_import` block (after line 137):

```python
        self.action_batch_import = QAction("Import Folder…", self)
        self.action_batch_import.triggered.connect(self._on_batch_import)
```

Add the handler method — place it directly after `_on_import` (after line 849):

```python
    def _on_batch_import(self) -> None:
        from translation_assistant.ui.dlg_batch_import import BatchImportDialog
        dlg = BatchImportDialog(self._db, self._settings, parent=self)
        dlg.exec()
```

- [ ] **Step 2: Wire into File menu in `combined_window.py`**

In `_setup_menubar`, after `file_menu.addAction(ta.action_import)` (line 72):

```python
        file_menu.addAction(ta.action_batch_import)
```

- [ ] **Step 3: Run full test suite**

```bash
pytest -q
```

Expected: all pass

- [ ] **Step 4: Smoke-test the UI manually**

```bash
python -m translation_assistant.main
```

- Open File menu → verify "Import Folder…" appears after "Import from file…"
- Click "Import Folder…" → dialog opens with "No folder selected." and disabled Import button
- Click Browse → pick a folder containing at least one valid TXT file and one CSV
- Verify series name pre-fills with folder name; edit it; click Import
- Verify summary shows correct counts with no crash
- Click Close → dialog dismisses; open the document list (`Ctrl+O`) to confirm documents imported

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py
git commit -m "feat: add Import Folder action to File menu"
```

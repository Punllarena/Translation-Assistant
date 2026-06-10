# New Series Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split "New" into "New Document" / "New Series", add a toolbar, and allow series creation from both the toolbar and Manage Series dialog.

**Architecture:** A new `NewSeriesDialog` handles series creation logic. Actions are built in `TranslationAssistantWidget` and surfaced in the `CombinedMainWindow` menu and a new toolbar. `get_series_list_full()` and `get_series_list()` are extended to include series that exist only in `series_profiles` (no documents yet).

**Tech Stack:** PySide6, SQLite (via `translation_assistant.db.Database`), pytest

---

## File Map

| Status | File | Change |
|--------|------|--------|
| Create | `translation_assistant/ui/dlg_new_series.py` | New dialog — title, URL, profile checkbox |
| Create | `tests/test_dlg_new_series.py` | Unit tests for NewSeriesDialog |
| Modify | `translation_assistant/db.py` | Fix `get_series_list_full` + `get_series_list` to include profile-only series |
| Modify | `tests/test_db.py` | New tests for extended query behaviour |
| Modify | `translation_assistant/ui/main_widget.py` | Split `action_new` → `action_new_doc` + `action_new_series` |
| Modify | `translation_assistant/ui/combined_window.py` | Update File menu + add toolbar |
| Modify | `translation_assistant/ui/dlg_series.py` | Add "New Series…" button |

**Do NOT touch:** `translation_assistant/ui/main_window.py` (legacy standalone window, used only by tests).

---

## Task 1: Create `NewSeriesDialog` (TDD)

**Files:**
- Create: `translation_assistant/ui/dlg_new_series.py`
- Create: `tests/test_dlg_new_series.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dlg_new_series.py`:

```python
"""
Tests for NewSeriesDialog.
All tests bypass exec() — call _on_accept() directly and inspect state.
"""
import sqlite3
import pytest
from unittest.mock import patch

from PySide6.QtWidgets import QDialog

from translation_assistant.db import Database
from translation_assistant.ui.dlg_new_series import NewSeriesDialog


@pytest.fixture
def mem_db(qapp):
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return db


class TestNewSeriesDialog:
    def test_instantiates(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        assert dlg is not None

    def test_empty_title_rejected(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("")
        with patch("translation_assistant.ui.dlg_new_series.QMessageBox.warning"):
            dlg._on_accept()
        assert dlg.result() != QDialog.DialogCode.Accepted

    def test_series_url_saved(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("https://ncode.syosetu.com/n1234ab/")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert mem_db.get_series_url("My Series") == "https://ncode.syosetu.com/n1234ab/"

    def test_empty_url_accepted(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert dlg.result() == QDialog.DialogCode.Accepted

    def test_profile_created_when_checked(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(True)
        dlg._on_accept()
        assert mem_db.get_profile_id("My Series") is not None
        assert mem_db.get_series_profile("My Series") == "My Series"

    def test_profile_not_created_when_unchecked(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert mem_db.get_profile_id("My Series") is None

    def test_duplicate_series_url_updated(self, qapp, mem_db):
        mem_db.set_series_url("My Series", "https://old.url/")
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("https://new.url/")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert mem_db.get_series_url("My Series") == "https://new.url/"

    def test_profile_already_exists_no_error(self, qapp, mem_db):
        mem_db.create_profile("My Series")
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(True)
        dlg._on_accept()
        assert mem_db.get_profile_id("My Series") is not None
        assert dlg.result() == QDialog.DialogCode.Accepted

    def test_series_title_property(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert dlg.series_title == "My Series"

    def test_created_profile_property_when_checked(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(True)
        dlg._on_accept()
        assert dlg.created_profile == "My Series"

    def test_created_profile_property_when_unchecked(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert dlg.created_profile == ""
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate
pytest tests/test_dlg_new_series.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `dlg_new_series` doesn't exist yet.

- [ ] **Step 3: Create `translation_assistant/ui/dlg_new_series.py`**

```python
"""
New Series dialog — registers a series (title, URL, optional profile) without requiring a document.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from translation_assistant.db import Database


class NewSeriesDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._series_title = ""
        self._created_profile = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("New Series")
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setSpacing(4)

        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Required")
        form.addRow("Series Title:", self._title_edit)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("e.g. https://ncode.syosetu.com/n1234ab/")
        form.addRow("Syosetu URL:", self._url_edit)

        layout.addLayout(form)

        self._profile_check = QCheckBox("Create new profile for this series")
        layout.addWidget(self._profile_check)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        create_btn = QPushButton("Create")
        create_btn.setDefault(True)
        create_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(create_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._title_edit.setFocus()

    def _on_accept(self) -> None:
        title = self._title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "New Series", "Series title is required.")
            return
        url = self._url_edit.text().strip()
        self._db.set_series_url(title, url)
        if self._profile_check.isChecked():
            if self._db.get_profile_id(title) is None:
                self._db.create_profile(title)
            self._db.set_series_profile(title, title)
            self._created_profile = title
        self._series_title = title
        self.accept()

    @property
    def series_title(self) -> str:
        return self._series_title

    @property
    def created_profile(self) -> str:
        return self._created_profile
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_dlg_new_series.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/dlg_new_series.py tests/test_dlg_new_series.py
git commit -m "feat: add NewSeriesDialog with tests"
```

---

## Task 2: Fix DB queries to include profile-only series

**Background:** `get_series_list_full()` and `get_series_list()` currently only return series that have at least one document. A series created via `NewSeriesDialog` only inserts into `series_profiles` — it won't appear in the Manage Series table until this fix.

**Files:**
- Modify: `translation_assistant/db.py:256-324`
- Modify: `tests/test_db.py` (add new tests at end of series section)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py` after the existing `test_get_series_list_full_excludes_no_series` test (around line 629):

```python
def test_get_series_list_full_includes_profile_only_series(db):
    """Series registered via set_series_url (no documents) must appear."""
    db.set_series_url("Ghost Series", "https://ncode.syosetu.com/n0001aa/")
    result = db.get_series_list_full()
    assert len(result) == 1
    assert result[0]["title"] == "Ghost Series"
    assert result[0]["url"] == "https://ncode.syosetu.com/n0001aa/"
    assert result[0]["chapter_count"] == 0


def test_get_series_list_full_mixed_document_and_profile_only(db):
    """Series with documents and profile-only series both appear, sorted."""
    db.create_document("D1", series_title="Beta", series_order=1, chapter_title="")
    db.set_series_url("Alpha", "https://ncode.syosetu.com/n0001aa/")
    result = db.get_series_list_full()
    titles = [r["title"] for r in result]
    assert titles == ["Alpha", "Beta"]
    alpha = next(r for r in result if r["title"] == "Alpha")
    assert alpha["chapter_count"] == 0
    beta = next(r for r in result if r["title"] == "Beta")
    assert beta["chapter_count"] == 1


def test_get_series_list_includes_profile_only_series(db):
    """get_series_list() must include series from series_profiles with no documents."""
    db.set_series_url("Ghost Series", "")
    result = db.get_series_list()
    assert "Ghost Series" in result


def test_get_series_list_no_duplicates_when_both_exist(db):
    """Series appearing in both documents and series_profiles shows once."""
    db.create_document("D1", series_title="Alpha", series_order=1, chapter_title="")
    db.set_series_url("Alpha", "https://ncode.syosetu.com/n0001aa/")
    result = db.get_series_list()
    assert result.count("Alpha") == 1
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
pytest tests/test_db.py::test_get_series_list_full_includes_profile_only_series tests/test_db.py::test_get_series_list_full_mixed_document_and_profile_only tests/test_db.py::test_get_series_list_includes_profile_only_series tests/test_db.py::test_get_series_list_no_duplicates_when_both_exist -v
```

Expected: all 4 FAIL.

- [ ] **Step 3: Confirm existing tests still pass (baseline)**

```bash
pytest tests/test_db.py -v -k "series"
```

Expected: all existing series tests PASS (so you have a clean before state).

- [ ] **Step 4: Update `get_series_list_full` in `translation_assistant/db.py`**

Replace the method body (lines ~307–324):

```python
def get_series_list_full(self) -> list[dict]:
    rows = self._conn.execute(
        """
        SELECT
            all_series.title,
            COALESCE(sp.syosetu_url, '')  AS url,
            COUNT(d.id)                   AS chapter_count,
            COALESCE(sp.profile_name, '') AS profile_name
        FROM (
            SELECT DISTINCT series_title AS title
              FROM documents WHERE series_title != ''
            UNION
            SELECT DISTINCT series_title AS title
              FROM series_profiles WHERE series_title != ''
        ) all_series
        LEFT JOIN documents d       ON d.series_title  = all_series.title
        LEFT JOIN series_profiles sp ON sp.series_title = all_series.title
        GROUP BY all_series.title
        ORDER BY all_series.title
        """
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: Update `get_series_list` in `translation_assistant/db.py`**

Replace the method body (lines ~256–261):

```python
def get_series_list(self) -> list[str]:
    rows = self._conn.execute(
        """
        SELECT title FROM (
            SELECT DISTINCT series_title AS title
              FROM documents WHERE series_title != ''
            UNION
            SELECT DISTINCT series_title AS title
              FROM series_profiles WHERE series_title != ''
        ) ORDER BY title
        """
    ).fetchall()
    return [r[0] for r in rows]
```

- [ ] **Step 6: Run all series-related DB tests**

```bash
pytest tests/test_db.py -v -k "series"
```

Expected: all PASS (new 4 + existing series tests).

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
pytest -q
```

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "fix(db): include profile-only series in get_series_list and get_series_list_full"
```

---

## Task 3: Update `main_widget.py` — split `action_new` into two actions

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`

- [ ] **Step 1: In `_build_actions()`, replace `action_new` with `action_new_doc` + `action_new_series`**

Find this block (around line 124–127):

```python
self.action_new = QAction("New (CTRL+N)", self)
self.action_new.triggered.connect(self._on_new)
self.action_new.setShortcut("Ctrl+N")
```

Replace with:

```python
self.action_new_doc = QAction("New Document (CTRL+N)", self)
self.action_new_doc.triggered.connect(self._on_new_doc)
self.action_new_doc.setShortcut("Ctrl+N")

self.action_new_series = QAction("New Series", self)
self.action_new_series.triggered.connect(self._on_new_series)
```

- [ ] **Step 2: Rename `_on_new` to `_on_new_doc`**

Find (around line 738):

```python
def _on_new(self) -> None:
```

Replace with:

```python
def _on_new_doc(self) -> None:
```

Body is unchanged.

- [ ] **Step 3: Add `_on_new_series` handler**

Add after `_on_new_doc` (around line 751):

```python
def _on_new_series(self) -> None:
    if self._db is None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "New Series", "No database open.")
        return
    from translation_assistant.ui.dlg_new_series import NewSeriesDialog
    from translation_assistant.ui.dlg_series import SeriesManagerDialog
    with self._topmost_suspended():
        dlg = NewSeriesDialog(self._db, parent=self)
        if dlg.exec():
            dlg2 = SeriesManagerDialog(self._db, parent=self)
            dlg2.exec()
```

- [ ] **Step 4: Run test suite**

```bash
pytest -q
```

Expected: all PASS. (`main_window.py` still has `action_new` — that's intentional, leave it.)

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/main_widget.py
git commit -m "feat(widget): split action_new into action_new_doc and action_new_series"
```

---

## Task 4: Update `combined_window.py` — File menu + toolbar

**Files:**
- Modify: `translation_assistant/ui/combined_window.py`

- [ ] **Step 1: Update File menu in `_setup_menubar()`**

Find (around line 67):

```python
file_menu.addAction(ta.action_new)
```

Replace with:

```python
file_menu.addAction(ta.action_new_doc)
file_menu.addAction(ta.action_new_series)
```

- [ ] **Step 2: Add `_setup_toolbar()` method**

Add after `_setup_menubar()` (around line 125):

```python
def _setup_toolbar(self) -> None:
    tb = self.addToolBar("Main")
    tb.setMovable(False)
    ta = self._ta_widget
    tb.addAction(ta.action_new_doc)
    tb.addAction(ta.action_new_series)
```

- [ ] **Step 3: Call `_setup_toolbar()` from `__init__`**

Find in `__init__` (around line 39):

```python
self._setup_menubar()
self._restore_splitter()
```

Replace with:

```python
self._setup_menubar()
self._setup_toolbar()
self._restore_splitter()
```

- [ ] **Step 4: Run test suite**

```bash
pytest -q
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/combined_window.py
git commit -m "feat(combined): add toolbar with New Document and New Series; update File menu"
```

---

## Task 5: Update `dlg_series.py` — add "New Series…" button

**Files:**
- Modify: `translation_assistant/ui/dlg_series.py`

- [ ] **Step 1: Add "New Series…" button to the button row**

Find `_setup_ui` button row section (around line 42–55):

```python
btn_row = QHBoxLayout()
btn_row.addStretch()
self._set_url_btn = QPushButton("Set URL…")
```

Replace with:

```python
btn_row = QHBoxLayout()
btn_row.addStretch()
self._new_series_btn = QPushButton("New Series…")
self._new_series_btn.clicked.connect(self._on_new_series)
self._set_url_btn = QPushButton("Set URL…")
```

Also add `self._new_series_btn` to the layout. Find:

```python
btn_row.addWidget(self._set_url_btn)
btn_row.addWidget(self._fetch_btn)
btn_row.addWidget(close_btn)
```

Replace with:

```python
btn_row.addWidget(self._new_series_btn)
btn_row.addWidget(self._set_url_btn)
btn_row.addWidget(self._fetch_btn)
btn_row.addWidget(close_btn)
```

- [ ] **Step 2: Add `_on_new_series` handler**

Add after `_on_fetch` (around line 103):

```python
def _on_new_series(self) -> None:
    from translation_assistant.ui.dlg_new_series import NewSeriesDialog
    dlg = NewSeriesDialog(self._db, parent=self)
    if dlg.exec():
        self._load()
```

- [ ] **Step 3: Run full test suite**

```bash
pytest -q
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add translation_assistant/ui/dlg_series.py
git commit -m "feat(series-manager): add New Series button"
```

---

## Self-Review

**Spec coverage:**
- ✅ "New Series fillables: Series Title, checkbox to use New Profile, Syosetu URL" → `NewSeriesDialog` Task 1
- ✅ "Allow adding new series in Manage Series" → Task 5 `_on_new_series` in `dlg_series.py`
- ✅ "Replace New with New Document and New Series in main toolbar" → Task 4 toolbar
- ✅ "Replace New with New Document and New Series in menu" → Task 3 + 4
- ✅ After New Series, open Manage Series (Option B from design) → Task 3 `_on_new_series`
- ✅ DB fix for profile-only series visibility → Task 2 (identified during planning)
- ✅ `main_window.py` not touched

**Placeholder scan:** No TBDs, TODOs, or vague steps. All code blocks are complete.

**Type consistency:**
- `action_new_doc` — defined Task 3, used Task 4 ✅
- `action_new_series` — defined Task 3, used Task 4 ✅
- `_on_new_doc` — renamed Task 3 ✅
- `_on_new_series` — added Task 3 ✅
- `NewSeriesDialog._title_edit`, `._url_edit`, `._profile_check`, `._on_accept()` — defined Task 1, used in tests Task 1 ✅
- `dlg.series_title`, `dlg.created_profile` — properties defined Task 1, tested Task 1 ✅

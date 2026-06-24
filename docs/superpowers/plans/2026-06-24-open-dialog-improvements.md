# Open Document Dialog Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add progress color coding, doc-count headers, sort combo, preview pane, and source text editor to `OpenDocumentDialog`.

**Architecture:** All changes land in `translation_assistant/ui/dlg_open.py`. No new files. New imports from Qt and existing `core.py` functions reused for source editor save pipeline.

**Tech Stack:** PySide6, SQLite via `db.py`, `core.build_new_file`, `core.parse_file_content`

## Global Constraints

- Python 3.10+; PySide6 only (no PyQt5)
- `dlg_open.py` only — do not touch `main_widget.py`, `db.py`, or `core.py`
- Run tests with: `source .venv/bin/activate && pytest tests/test_dlg_open.py -q`
- Full suite: `pytest -q`
- Activate venv before every command: `source .venv/bin/activate`

---

### Task 1: Progress color coding + doc-count on series headers

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py` — `_load_documents`, imports
- Modify: `tests/test_dlg_open.py` — fix 2 broken assertions, add 3 new tests

**Interfaces:**
- Produces: `_load_documents()` sets `QColor` on Progress column; group header text = `"Series (N)"`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dlg_open.py` inside `class TestOpenDocumentDialog`:

```python
def test_progress_zero_percent_color(self, qapp, mem_db):
    from PySide6.QtGui import QColor
    doc_id = mem_db.create_document("Story")
    # no lines → 0%
    dlg = OpenDocumentDialog(mem_db)
    leaf = _first_leaf(dlg)
    assert leaf.foreground(1).color().name() == "#888888"

def test_progress_partial_color(self, qapp, mem_db):
    from PySide6.QtGui import QColor
    doc_id = mem_db.create_document("Story")
    mem_db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Trans"},
        {"line_number": 1, "prefix": "%", "raw_text": "B", "translated_text": ""},
    ])
    dlg = OpenDocumentDialog(mem_db)
    leaf = _first_leaf(dlg)
    assert leaf.foreground(1).color().name() == "#c8a000"

def test_progress_complete_color(self, qapp, mem_db):
    doc_id = mem_db.create_document("Story")
    mem_db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Trans"},
    ])
    dlg = OpenDocumentDialog(mem_db)
    leaf = _first_leaf(dlg)
    assert leaf.foreground(1).color().name() == "#2a8a2a"

def test_series_header_shows_doc_count(self, qapp, mem_db):
    mem_db.create_document("C1", series_title="Novel", series_order=1, chapter_title="Ch 1")
    mem_db.create_document("C2", series_title="Novel", series_order=2, chapter_title="Ch 2")
    dlg = OpenDocumentDialog(mem_db)
    r = _root(dlg)
    group = r.child(0)
    assert "(2)" in group.text(0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_dlg_open.py::TestOpenDocumentDialog::test_progress_zero_percent_color tests/test_dlg_open.py::TestOpenDocumentDialog::test_series_header_shows_doc_count -v
```

Expected: FAIL (no color set, no count in header)

- [ ] **Step 3: Add QColor/QFont to imports in `dlg_open.py`**

Change the top of `dlg_open.py`:

```python
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout,
)
```

- [ ] **Step 4: Update `_load_documents` to set colors and doc counts**

Replace the `for doc in sorted(...)` block in `_load_documents`:

```python
def _load_documents(self) -> None:
    self._tree.clear()
    self._doc_ids.clear()
    self._source_urls.clear()

    docs = self._db.list_documents()
    if not docs:
        return

    groups: dict[str, QTreeWidgetItem] = {}
    group_counts: dict[str, int] = {}

    for doc in sorted(docs, key=lambda d: (d["series_title"] or _NO_SERIES, d["series_order"])):
        series = doc["series_title"] or _NO_SERIES
        if series not in groups:
            group_item = QTreeWidgetItem(self._tree, [series, "", ""])
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)
            groups[series] = group_item
            group_counts[series] = 0

        display = doc["chapter_title"] if doc["chapter_title"] else doc["title"]
        progress = f"{doc['progress']}%"
        last_edited = _fmt_date(doc.get("updated_at", ""))
        leaf = QTreeWidgetItem(groups[series], [display, progress, last_edited])
        leaf.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        pct = doc["progress"]
        if pct == 0:
            leaf.setForeground(1, QColor("#888888"))
        elif pct == 100:
            leaf.setForeground(1, QColor("#2a8a2a"))
        else:
            leaf.setForeground(1, QColor("#c8a000"))

        self._doc_ids[id(leaf)] = doc["id"]
        self._source_urls[id(leaf)] = doc.get("source_url", "")
        group_counts[series] += 1

    for series, group_item in groups.items():
        count = group_counts[series]
        group_item.setText(0, f"{series} ({count})")

    self._tree.expandAll()
```

- [ ] **Step 5: Fix two existing tests that break due to `" (N)"` in group header text**

In `tests/test_dlg_open.py`, update:

```python
# OLD:
def test_grouped_doc_appears_under_series(self, qapp, mem_db):
    mem_db.create_document("Ch1", series_title="My Novel", series_order=1, chapter_title="Chapter 1")
    dlg = OpenDocumentDialog(mem_db)
    assert "My Novel" in _group_names(dlg)
    assert "Chapter 1" in _all_leaf_titles(dlg)

# NEW:
def test_grouped_doc_appears_under_series(self, qapp, mem_db):
    mem_db.create_document("Ch1", series_title="My Novel", series_order=1, chapter_title="Chapter 1")
    dlg = OpenDocumentDialog(mem_db)
    assert any(n.startswith("My Novel") for n in _group_names(dlg))
    assert "Chapter 1" in _all_leaf_titles(dlg)
```

```python
# OLD:
novel_group = next(r.child(i) for i in range(r.childCount()) if r.child(i).text(0) == "Novel")

# NEW:
novel_group = next(r.child(i) for i in range(r.childCount()) if r.child(i).text(0).startswith("Novel"))
```

- [ ] **Step 6: Run all new + related tests**

```bash
source .venv/bin/activate && pytest tests/test_dlg_open.py -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "feat(dlg_open): progress color coding and series doc-count headers"
```

---

### Task 2: Sort combo

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py` — `_setup_ui`, imports, `_load_documents`
- Modify: `tests/test_dlg_open.py` — 4 new tests

**Interfaces:**
- Consumes: `_load_documents()` from Task 1 (sort logic added inside it)
- Produces: `self._sort_combo: QComboBox` with indices 0–4

- [ ] **Step 1: Write the failing tests**

Add to `class TestOpenDocumentDialog` in `tests/test_dlg_open.py`:

```python
def test_sort_combo_exists(self, qapp, mem_db):
    dlg = OpenDocumentDialog(mem_db)
    assert hasattr(dlg, "_sort_combo")

def test_sort_last_edited_newest_first(self, qapp, mem_db):
    id_old = mem_db.create_document("OldDoc", chapter_title="OldDoc")
    id_new = mem_db.create_document("NewDoc", chapter_title="NewDoc")
    mem_db._conn.execute(
        "UPDATE documents SET updated_at = '2023-01-01 00:00:00' WHERE id = ?", (id_old,)
    )
    mem_db._conn.execute(
        "UPDATE documents SET updated_at = '2025-06-01 00:00:00' WHERE id = ?", (id_new,)
    )
    mem_db._conn.commit()
    dlg = OpenDocumentDialog(mem_db)
    dlg._sort_combo.setCurrentIndex(1)  # Last Edited
    titles = _all_leaf_titles(dlg)
    assert titles.index("NewDoc") < titles.index("OldDoc")

def test_sort_progress_asc(self, qapp, mem_db):
    id_done = mem_db.create_document("Done", chapter_title="Done")
    id_none = mem_db.create_document("None", chapter_title="None")
    mem_db.save_lines(id_done, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "T"},
    ])
    # id_none has no lines → 0%
    dlg = OpenDocumentDialog(mem_db)
    dlg._sort_combo.setCurrentIndex(2)  # Progress ↑
    titles = _all_leaf_titles(dlg)
    assert titles.index("None") < titles.index("Done")

def test_sort_title_alpha(self, qapp, mem_db):
    mem_db.create_document("Zebra", chapter_title="Zebra")
    mem_db.create_document("Apple", chapter_title="Apple")
    dlg = OpenDocumentDialog(mem_db)
    dlg._sort_combo.setCurrentIndex(4)  # Title A→Z
    titles = _all_leaf_titles(dlg)
    assert titles.index("Apple") < titles.index("Zebra")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_dlg_open.py::TestOpenDocumentDialog::test_sort_combo_exists tests/test_dlg_open.py::TestOpenDocumentDialog::test_sort_last_edited_newest_first -v
```

Expected: FAIL (`_sort_combo` not found)

- [ ] **Step 3: Add `QComboBox` to imports in `dlg_open.py`**

```python
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout,
)
```

- [ ] **Step 4: Add sort combo to `_setup_ui`**

Replace:

```python
self._filter_edit = QLineEdit()
self._filter_edit.setPlaceholderText("Filter by title…")
self._filter_edit.textChanged.connect(self._apply_filter)
layout.addWidget(self._filter_edit)
```

With:

```python
top_row = QHBoxLayout()
self._filter_edit = QLineEdit()
self._filter_edit.setPlaceholderText("Filter by title…")
self._filter_edit.textChanged.connect(self._apply_filter)
top_row.addWidget(self._filter_edit)

self._sort_combo = QComboBox()
self._sort_combo.addItems([
    "Series Order",
    "Last Edited",
    "Progress ↑",
    "Progress ↓",
    "Title A→Z",
])
self._sort_combo.currentIndexChanged.connect(self._load_documents)
top_row.addWidget(self._sort_combo)
layout.addLayout(top_row)
```

- [ ] **Step 5: Add sort logic to `_load_documents`**

Replace the `for doc in sorted(...)` line at the start of the loop in `_load_documents`:

```python
idx = self._sort_combo.currentIndex() if hasattr(self, "_sort_combo") else 0
_display = lambda d: d["chapter_title"] if d["chapter_title"] else d["title"]
if idx == 1:  # Last Edited
    docs_sorted = sorted(docs, key=lambda d: d["updated_at"] or "", reverse=True)
elif idx == 2:  # Progress ↑
    docs_sorted = sorted(docs, key=lambda d: (d["progress"], d["series_title"] or _NO_SERIES, d["series_order"]))
elif idx == 3:  # Progress ↓
    docs_sorted = sorted(docs, key=lambda d: (-d["progress"], d["series_title"] or _NO_SERIES, d["series_order"]))
elif idx == 4:  # Title A→Z
    docs_sorted = sorted(docs, key=lambda d: (d["series_title"] or _NO_SERIES, _display(d)))
else:  # Series Order (default)
    docs_sorted = sorted(docs, key=lambda d: (d["series_title"] or _NO_SERIES, d["series_order"]))

for doc in docs_sorted:
```

(Remove the old `for doc in sorted(...)` line and replace with `for doc in docs_sorted:`)

- [ ] **Step 6: Run all tests**

```bash
source .venv/bin/activate && pytest tests/test_dlg_open.py -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "feat(dlg_open): sort combo for tree ordering"
```

---

### Task 3: Preview pane

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py` — `_setup_ui`, `_on_selection_changed`, imports
- Modify: `tests/test_dlg_open.py` — 3 new tests

**Interfaces:**
- Consumes: `db.get_lines(doc_id)` → `list[dict]` with keys `prefix`, `raw_text`
- Produces: `self._preview: QPlainTextEdit` (read-only)

- [ ] **Step 1: Write the failing tests**

Add to `class TestOpenDocumentDialog`:

```python
def test_preview_pane_exists(self, qapp, mem_db):
    dlg = OpenDocumentDialog(mem_db)
    assert hasattr(dlg, "_preview")

def test_preview_loads_on_selection(self, qapp, mem_db):
    doc_id = mem_db.create_document("Story")
    mem_db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "First line", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "Second line", "translated_text": ""},
    ])
    dlg = OpenDocumentDialog(mem_db)
    leaf = _first_leaf(dlg)
    dlg._tree.setCurrentItem(leaf)
    text = dlg._preview.toPlainText()
    assert "First line" in text
    assert "Second line" in text

def test_preview_clears_when_no_selection(self, qapp, mem_db):
    doc_id = mem_db.create_document("Story")
    mem_db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Some text", "translated_text": ""},
    ])
    dlg = OpenDocumentDialog(mem_db)
    leaf = _first_leaf(dlg)
    dlg._tree.setCurrentItem(leaf)
    dlg._tree.setCurrentItem(None)
    assert dlg._preview.toPlainText() == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_dlg_open.py::TestOpenDocumentDialog::test_preview_pane_exists tests/test_dlg_open.py::TestOpenDocumentDialog::test_preview_loads_on_selection -v
```

Expected: FAIL (`_preview` not found)

- [ ] **Step 3: Add `QFont`, `QPlainTextEdit`, `QSplitter` to imports**

```python
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)
```

- [ ] **Step 4: Add preview pane to `_setup_ui`**

Replace:

```python
layout.addWidget(self._tree)
```

With:

```python
self._splitter = QSplitter(Qt.Orientation.Vertical)
self._splitter.addWidget(self._tree)

self._preview = QPlainTextEdit()
self._preview.setReadOnly(True)
preview_font = QFont("monospace")
preview_font.setPointSize(9)
self._preview.setFont(preview_font)
self._splitter.addWidget(self._preview)
self._splitter.setSizes([300, 80])
layout.addWidget(self._splitter)
```

- [ ] **Step 5: Load preview on selection change**

In `_on_selection_changed`, add preview update at the end:

```python
def _on_selection_changed(self) -> None:
    leaf = self._current_leaf()
    is_leaf = leaf is not None
    self._open_btn.setEnabled(is_leaf)
    self._edit_btn.setEnabled(is_leaf)
    self._delete_btn.setEnabled(is_leaf)
    has_url = is_leaf and bool(self._source_urls.get(id(leaf), ""))
    self._refetch_btn.setEnabled(has_url)

    if not is_leaf:
        self._preview.setPlainText("")
    else:
        doc_id = self._doc_ids[id(leaf)]
        rows = self._db.get_lines(doc_id)
        lines = [r["raw_text"] for r in rows if r["raw_text"]][:8]
        self._preview.setPlainText("\n".join(lines))
```

- [ ] **Step 6: Run all tests**

```bash
source .venv/bin/activate && pytest tests/test_dlg_open.py -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "feat(dlg_open): preview pane shows first lines of selected document"
```

---

### Task 4: Source text editor

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py` — add `_EditSourceDialog`, `_on_edit_source`, `_edit_source_btn`, update `_on_selection_changed`, `_setup_ui`
- Modify: `tests/test_dlg_open.py` — 4 new tests

**Interfaces:**
- Consumes: `db.get_lines(doc_id)` → strips `raw_text`; `db.replace_raw_content(doc_id, raw_lines)`
- Consumes: `core.build_new_file(text: str) -> str`, `core.parse_file_content(text: str) -> tuple[list[str], list[str], str]`
- Produces: `self._edit_source_btn: QPushButton`; `_EditSourceDialog(doc_id, doc_title, db, parent)`

- [ ] **Step 1: Write the failing tests**

Add to `class TestOpenDocumentDialog`:

```python
def test_edit_source_btn_exists(self, qapp, mem_db):
    dlg = OpenDocumentDialog(mem_db)
    assert hasattr(dlg, "_edit_source_btn")

def test_edit_source_btn_disabled_initially(self, qapp, mem_db):
    mem_db.create_document("Doc")
    dlg = OpenDocumentDialog(mem_db)
    assert not dlg._edit_source_btn.isEnabled()

def test_edit_source_btn_enabled_on_selection(self, qapp, mem_db):
    mem_db.create_document("Doc")
    dlg = OpenDocumentDialog(mem_db)
    dlg._tree.setCurrentItem(_first_leaf(dlg))
    assert dlg._edit_source_btn.isEnabled()
```

Add `TestEditSourceDialog` class after the existing test class:

```python
class TestEditSourceDialog:
    def test_loads_raw_text_stripping_prefix(self, qapp, mem_db):
        from translation_assistant.ui.dlg_open import _EditSourceDialog
        doc_id = mem_db.create_document("Story")
        mem_db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Hello world", "translated_text": ""},
            {"line_number": 1, "prefix": "$", "raw_text": "Continuation", "translated_text": ""},
        ])
        dlg = _EditSourceDialog(doc_id, "Story", mem_db)
        text = dlg._editor.toPlainText()
        assert "Hello world" in text
        assert "Continuation" in text
        assert "%" not in text
        assert "$" not in text

    def test_save_updates_db_raw_content(self, qapp, mem_db):
        from translation_assistant.ui.dlg_open import _EditSourceDialog
        doc_id = mem_db.create_document("Story")
        mem_db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Originl", "translated_text": "Trans"},
        ])
        dlg = _EditSourceDialog(doc_id, "Story", mem_db)
        dlg._editor.setPlainText("Original")
        dlg._on_save()
        lines = mem_db.get_lines(doc_id)
        assert any(r["raw_text"] == "Original" for r in lines)

    def test_save_preserves_existing_translations(self, qapp, mem_db):
        from translation_assistant.ui.dlg_open import _EditSourceDialog
        doc_id = mem_db.create_document("Story")
        mem_db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Hello", "translated_text": "Bonjour"},
        ])
        dlg = _EditSourceDialog(doc_id, "Story", mem_db)
        dlg._editor.setPlainText("Hello")  # same text, no structural change
        dlg._on_save()
        lines = mem_db.get_lines(doc_id)
        assert lines[0]["translated_text"] == "Bonjour"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_dlg_open.py::TestOpenDocumentDialog::test_edit_source_btn_exists tests/test_dlg_open.py::TestEditSourceDialog -v
```

Expected: FAIL (no `_edit_source_btn`, no `_EditSourceDialog`)

- [ ] **Step 3: Add `_EditSourceDialog` class to `dlg_open.py`**

Add after `_EditMetadataDialog`:

```python
class _EditSourceDialog(QDialog):
    def __init__(self, doc_id: int, doc_title: str, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._doc_id = doc_id
        self._db = db
        self.setWindowTitle(f"Edit Source — {doc_title}")
        self.setMinimumSize(500, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._editor = QPlainTextEdit()
        editor_font = QFont("monospace")
        editor_font.setPointSize(10)
        self._editor.setFont(editor_font)
        layout.addWidget(self._editor)

        rows = self._db.get_lines(doc_id)
        text = "\n".join(r["raw_text"] for r in rows)
        self._editor.setPlainText(text)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_save(self) -> None:
        from translation_assistant.core import build_new_file, parse_file_content
        text = self._editor.toPlainText()
        formatted = build_new_file(text)
        raw_lines, _, _ = parse_file_content(formatted)
        self._db.replace_raw_content(self._doc_id, raw_lines)
        self.accept()
```

- [ ] **Step 4: Add "Edit Source…" button to `_setup_ui` in `OpenDocumentDialog`**

In the button row setup, add `_edit_source_btn` between `_edit_btn` and `_delete_btn`:

```python
self._edit_source_btn = QPushButton("Edit Source…")
self._edit_source_btn.setEnabled(False)
self._edit_source_btn.clicked.connect(self._on_edit_source)
```

And add it to `btn_row`:

```python
btn_row.addWidget(self._open_btn)
btn_row.addWidget(self._edit_btn)
btn_row.addWidget(self._edit_source_btn)
btn_row.addWidget(self._delete_btn)
btn_row.addWidget(self._refetch_btn)
btn_row.addWidget(cancel_btn)
```

- [ ] **Step 5: Wire `_on_selection_changed` and add `_on_edit_source`**

In `_on_selection_changed`, add:

```python
self._edit_source_btn.setEnabled(is_leaf)
```

(after the existing `self._delete_btn.setEnabled(is_leaf)` line)

Add method:

```python
def _on_edit_source(self) -> None:
    leaf = self._current_leaf()
    if leaf is None:
        return
    doc_id = self._doc_ids[id(leaf)]
    dlg = _EditSourceDialog(doc_id, leaf.text(0), self._db, parent=self)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        self._load_documents()
```

- [ ] **Step 6: Run all tests**

```bash
source .venv/bin/activate && pytest tests/test_dlg_open.py -q
```

Expected: all pass

- [ ] **Step 7: Run full suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "feat(dlg_open): source text editor with build_new_file pipeline"
```

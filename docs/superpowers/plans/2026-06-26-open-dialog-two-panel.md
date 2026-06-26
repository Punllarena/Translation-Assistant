# Open Document Dialog — Two-Panel Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-tree Open Document dialog with a two-panel layout (series list | chapters), remove the preview pane and sort combo, add a `#` column, sortable column headers, and a chapter right-click context menu.

**Architecture:** `OpenDocumentDialog` is split into a series `QListWidget` (left) and a flat chapter `QTreeWidget` (right) joined by a horizontal `QSplitter`. `_load_series()` populates the left panel; selecting a series calls `_load_chapters(series_raw)` which fills the right panel with flat top-level items. Sort state is tracked in `self._sort_col / _sort_asc`; clicking a column header re-sorts in Python.

**Tech Stack:** PySide6, SQLite via `Database`, `AppSettings` (QSettings wrapper), pytest.

## Global Constraints

- Never write to `QSettings` directly — use `AppSettings` properties only.
- Never import `sqlite3` outside `db.py`.
- No Qt imports in `core.py`.
- Keep `self._tree` as the name of the chapter `QTreeWidget` (test compat).
- Chapter tree columns: 0=`#`, 1=`Title`, 2=`Progress`, 3=`Last Edited`.
- Series `UserRole` data = raw series name (`""` for unseries docs, matching `series_title or ""`).

---

### Task 1: Add `open_dialog_last_series` to `AppSettings`

**Files:**
- Modify: `translation_assistant/settings.py:176` (insert before `save`)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `AppSettings.open_dialog_last_series: str` (get/set)

- [ ] **Step 1: Write failing test**

In `tests/test_settings.py`, add at the bottom:

```python
def test_open_dialog_last_series_default(tmp_settings):
    assert tmp_settings.open_dialog_last_series == ""

def test_open_dialog_last_series_roundtrip(tmp_settings):
    tmp_settings.open_dialog_last_series = "My Novel"
    assert tmp_settings.open_dialog_last_series == "My Novel"
```

- [ ] **Step 2: Run to confirm failure**

```
source .venv/bin/activate && pytest tests/test_settings.py::test_open_dialog_last_series_default -xq
```

Expected: `AttributeError: 'AppSettings' object has no attribute 'open_dialog_last_series'`

- [ ] **Step 3: Implement in `settings.py`**

Insert before the `def save(self)` line at `translation_assistant/settings.py`:

```python
    # --- Open dialog: last selected series ---

    @property
    def open_dialog_last_series(self) -> str:
        return self._qs.value("OpenDialogLastSeries", "")

    @open_dialog_last_series.setter
    def open_dialog_last_series(self, value: str) -> None:
        self._qs.setValue("OpenDialogLastSeries", value)

```

- [ ] **Step 4: Run tests**

```
pytest tests/test_settings.py::test_open_dialog_last_series_default tests/test_settings.py::test_open_dialog_last_series_roundtrip -xq
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/settings.py tests/test_settings.py
git commit -m "feat(settings): add open_dialog_last_series property"
```

---

### Task 2: Two-Panel Layout Skeleton + Test Infrastructure Update

Rewrites `_setup_ui`, removes preview and sort combo, adds `#` column. Many existing tests break; update them here. The dialog will not be interactive yet (series loading comes in Task 3).

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py` (full `_setup_ui` rewrite + helper method stubs)
- Modify: `tests/test_dlg_open.py` (update helpers, remove/update broken tests)

**Interfaces:**
- Produces:
  - `dlg._series_list: QListWidget` — left panel
  - `dlg._tree: QTreeWidget` — right panel, 4 cols (#/Title/Progress/Last Edited)
  - `dlg._filter_edit: QLineEdit` — above right panel
  - `dlg._sort_col: int` — current sort column (default 0)
  - `dlg._sort_asc: bool` — sort direction (default True)
  - No `dlg._preview`, no `dlg._sort_combo`

- [ ] **Step 1: Rewrite `_setup_ui` in `dlg_open.py`**

Replace the entire `_setup_ui` method. Also update imports at the top (remove `QPlainTextEdit`, add `QListWidget` — it's already imported via `QTreeWidget` in PySide6's combined import; ensure `QListWidget`, `QListWidgetItem` are imported).

Replace the import block at the top of the file:

```python
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSpinBox,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)
```

Replace `_setup_ui`:

```python
    def _setup_ui(self) -> None:
        self.setWindowTitle("Open Document")
        self.setMinimumSize(780, 460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter chapters…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        outer.addWidget(self._filter_edit)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._series_list = QListWidget()
        self._series_list.setFixedWidth(220)
        self._series_list.currentItemChanged.connect(self._on_series_selected)
        self._series_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._series_list.customContextMenuRequested.connect(self._on_series_context_menu)
        self._splitter.addWidget(self._series_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["#", "Title", "Progress", "Last Edited"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionsClickable(True)
        self._tree.header().sectionClicked.connect(self._sort_chapters)
        self._tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self._tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self._tree.currentItemChanged.connect(self._on_chapter_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.itemActivated.connect(self._on_item_activated)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_chapter_context_menu)
        right_layout.addWidget(self._tree)

        self._splitter.addWidget(right)
        self._splitter.setStretchFactor(1, 1)
        outer.addWidget(self._splitter)

        self._sort_col = 0
        self._sort_asc = True

        btn_row = QHBoxLayout()
        self._open_btn = QPushButton("Open")
        self._open_btn.setEnabled(False)
        self._open_btn.setDefault(True)
        self._open_btn.clicked.connect(self._on_open)
        self._edit_btn = QPushButton("Edit…")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit)
        self._edit_source_btn = QPushButton("Edit Source…")
        self._edit_source_btn.setEnabled(False)
        self._edit_source_btn.clicked.connect(self._on_edit_source)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setEnabled(False)
        self._delete_btn.setStyleSheet("color: red;")
        self._delete_btn.clicked.connect(self._on_delete)
        self._refetch_btn = QPushButton("Re-fetch")
        self._refetch_btn.setEnabled(False)
        self._refetch_btn.clicked.connect(self._on_refetch)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        for btn in (self._open_btn, self._edit_btn, self._edit_source_btn,
                    self._delete_btn, self._refetch_btn, cancel_btn):
            btn_row.addWidget(btn)
        outer.addLayout(btn_row)
```

Also add `from PySide6.QtWidgets import QWidget` to the import (or include it in the combined import above — `QWidget` is in `PySide6.QtWidgets`).

Full import line (replace existing):

```python
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSpinBox,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
```

- [ ] **Step 2: Rename `_on_selection_changed` → `_on_chapter_selection_changed`**

Replace the existing `_on_selection_changed` method:

```python
    def _on_chapter_selection_changed(self) -> None:
        leaf = self._current_leaf()
        is_leaf = leaf is not None
        self._open_btn.setEnabled(is_leaf)
        self._edit_btn.setEnabled(is_leaf)
        self._edit_source_btn.setEnabled(is_leaf)
        self._delete_btn.setEnabled(is_leaf)
        has_url = is_leaf and bool(self._source_urls.get(id(leaf), ""))
        self._refetch_btn.setEnabled(has_url)
```

Update `_current_leaf` to remove the childCount check (no groups in chapter tree):

```python
    def _current_leaf(self) -> QTreeWidgetItem | None:
        return self._tree.currentItem()
```

- [ ] **Step 3: Add stub methods for new behaviour (implement in later tasks)**

Add these stubs (they'll be replaced in Tasks 3–5):

```python
    def _load_series(self) -> None:
        pass

    def _load_chapters(self, series_raw: str) -> None:
        pass

    def _on_series_selected(self, current, _prev) -> None:
        if current is None:
            self._tree.clear()
            self._doc_ids.clear()
            self._source_urls.clear()
            return
        self._load_chapters(current.data(Qt.ItemDataRole.UserRole))

    def _sort_chapters(self, col: int) -> None:
        pass

    def _on_chapter_context_menu(self, pos) -> None:
        pass

    def _on_series_context_menu(self, pos) -> None:
        pass

    def _current_series_raw(self) -> str | None:
        item = self._series_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _restore_series(self, series_raw: str | None) -> None:
        if series_raw is None:
            if self._series_list.count():
                self._series_list.setCurrentRow(0)
            return
        for i in range(self._series_list.count()):
            if self._series_list.item(i).data(Qt.ItemDataRole.UserRole) == series_raw:
                self._series_list.setCurrentRow(i)
                return
        if self._series_list.count():
            self._series_list.setCurrentRow(0)
```

- [ ] **Step 4: Update `_load_documents` call sites**

`_load_documents` is called by `__init__` and several action handlers. In the new design it no longer exists; it's replaced by `_load_series()`. Update `__init__`:

Replace:
```python
        self._setup_ui()
        self._load_documents()
        if current_doc_id is not None:
            self._select_doc(current_doc_id)
```

With:
```python
        self._setup_ui()
        self._load_series()
        if current_doc_id is not None:
            self._select_doc(current_doc_id)
        elif self._series_list.count():
            self._series_list.setCurrentRow(0)
```

Also update `_do_edit` (currently calls `self._load_documents()`):

```python
    def _do_edit(self, doc_id: int, series_title: str, series_order: int, chapter_title: str) -> None:
        self._db.update_document_metadata(
            doc_id,
            series_title=series_title,
            series_order=series_order,
            chapter_title=chapter_title,
        )
        series_raw = self._current_series_raw()
        self._load_series()
        self._restore_series(series_raw)
        self._select_doc(doc_id)
```

Update `_on_edit_source`:

```python
    def _on_edit_source(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        doc_id = self._doc_ids[id(leaf)]
        dlg = _EditSourceDialog(doc_id, leaf.text(1), self._db, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            series_raw = self._current_series_raw()
            self._load_series()
            self._restore_series(series_raw)
            self._select_doc(doc_id)
```

Update `_on_refetch_done`:

```python
    def _on_refetch_done(self, doc_id: int, title: str, content: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        from translation_assistant.core import build_new_file, parse_file_content
        formatted = build_new_file(f"{title}\n\n{content}" if title else content)
        raw_lines, _, _ = parse_file_content(formatted)
        self._db.replace_raw_content(doc_id, raw_lines)
        self._refetch_worker = None
        self._refetch_btn.setText("Re-fetch")
        series_raw = self._current_series_raw()
        self._load_series()
        self._restore_series(series_raw)
        self._select_doc(doc_id)
        QMessageBox.information(self, "Re-fetch", "Content re-fetched successfully.")
```

Update `_on_delete` to use flat tree and reload:

```python
    def _on_delete(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        title = leaf.text(1)
        answer = QMessageBox.question(
            self,
            "Delete Document",
            f'Delete "{title}"? This cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        doc_id = self._doc_ids.pop(id(leaf), None)
        if doc_id is not None:
            self._db.delete_document(doc_id)
        series_raw = self._current_series_raw()
        self._load_series()
        self._restore_series(series_raw)
```

Update `_on_item_double_clicked` and `_on_item_activated` to use col 0 check removed (no groups):

```python
    def _on_item_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        self._selected_doc_id = self._doc_ids[id(item)]
        self.accept()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        self._selected_doc_id = self._doc_ids[id(item)]
        self.accept()
```

Update `_on_open`:

```python
    def _on_open(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        self._selected_doc_id = self._doc_ids[id(leaf)]
        self.accept()
```

Update `_select_doc` to work with flat chapter tree (series selection first):

```python
    def _select_doc(self, doc_id: int) -> None:
        doc = self._db.get_document(doc_id)
        if not doc:
            return
        series_raw = doc["series_title"] or ""
        # Select the series (triggers _load_chapters)
        for i in range(self._series_list.count()):
            if self._series_list.item(i).data(Qt.ItemDataRole.UserRole) == series_raw:
                self._series_list.setCurrentRow(i)
                break
        # Find chapter in (now-loaded) tree
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if self._doc_ids.get(id(item)) == doc_id:
                self._tree.setCurrentItem(item)
                self._tree.scrollToItem(item)
                return
```

Remove the old `_on_context_menu` method entirely (replaced by `_on_series_context_menu` and `_on_chapter_context_menu` stubs above).

Also remove the old `_open_series_manager` method — it'll be called from `_on_series_context_menu` in Task 5. Actually keep it, just remove its caller:

Keep:
```python
    def _open_series_manager(self) -> None:
        from translation_assistant.ui.dlg_series import SeriesManagerDialog
        dlg = SeriesManagerDialog(self._db, parent=self)
        dlg.exec()
```

Update `_on_edit` to use col 1 for title (leaf.text(1) is Title now):

The `_on_edit` method does `doc = self._db.get_document(doc_id)` so the title isn't needed from the item. No change needed.

Update `_on_refetch` to use col 1 for title in refetch confirmation... looking at the code:

```python
    def _on_refetch(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from translation_assistant.scraper import FetchWorker
        leaf = self._current_leaf()
        if leaf is None:
            return
        doc_id = self._doc_ids[id(leaf)]
        url = self._source_urls.get(id(leaf), "")
        if not url:
            return
        answer = QMessageBox.question(
            self,
            "Re-fetch",
            f"Re-fetch content from:\n{url}\n\nExisting translations will be preserved by line position.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for btn in (self._open_btn, self._edit_btn, self._delete_btn, self._refetch_btn):
            btn.setEnabled(False)
        self._refetch_btn.setText("Fetching…")
        self._refetch_worker = FetchWorker(url, parent=self)
        self._refetch_worker.finished.connect(
            lambda title, content: self._on_refetch_done(doc_id, title, content)
        )
        self._refetch_worker.error.connect(self._on_refetch_error)
        self._refetch_worker.start()
```

(No changes needed here.)

- [ ] **Step 5: Update `tests/test_dlg_open.py` helpers and broken tests**

Replace the helper functions at the top of the test file:

```python
# ---------------------------------------------------------------------------
# Helpers — new two-panel API
# ---------------------------------------------------------------------------

def _series_names(dlg: OpenDocumentDialog) -> list[str]:
    """Text of all series list items."""
    return [dlg._series_list.item(i).text() for i in range(dlg._series_list.count())]


def _select_series(dlg: OpenDocumentDialog, starts_with: str) -> None:
    """Select a series in the left panel by prefix match."""
    for i in range(dlg._series_list.count()):
        if dlg._series_list.item(i).text().startswith(starts_with):
            dlg._series_list.setCurrentRow(i)
            return


def _chapter_titles(dlg: OpenDocumentDialog) -> list[str]:
    """Title (col 1) of all visible chapter tree items."""
    return [
        dlg._tree.topLevelItem(i).text(1)
        for i in range(dlg._tree.topLevelItemCount())
    ]


def _first_chapter(dlg: OpenDocumentDialog):
    """First item in the chapter tree, or None."""
    if dlg._tree.topLevelItemCount() == 0:
        return None
    return dlg._tree.topLevelItem(0)


# Keep _first_leaf as alias so unchanged tests still work.
_first_leaf = _first_chapter


def _chapter_is_hidden(dlg: OpenDocumentDialog, title: str) -> bool:
    for i in range(dlg._tree.topLevelItemCount()):
        item = dlg._tree.topLevelItem(i)
        if item.text(1) == title:
            return item.isHidden()
    return True


# Remove old helpers that no longer apply:
# _root, _group_names, _all_leaf_titles, _first_leaf_is_hidden
```

Remove the old helper functions `_root`, `_group_names`, `_all_leaf_titles`, `_first_leaf_is_hidden`.

Now update individual tests:

**Remove** (delete these test methods entirely — they test removed features or old structure):
- `test_series_header_not_selectable` — no tree group headers
- `test_preview_pane_exists`
- `test_preview_loads_on_selection`
- `test_preview_clears_when_no_selection`
- `test_no_series_context_menu_suppressed` — context menu moved to series list
- `test_sort_combo_exists`

**Update** these tests:

`test_shows_no_groups_when_db_empty`:
```python
def test_shows_no_groups_when_db_empty(self, qapp, mem_db):
    dlg = OpenDocumentDialog(mem_db)
    assert dlg._series_list.count() == 0
    assert dlg._tree.topLevelItemCount() == 0
```

`test_ungrouped_doc_appears_under_no_series`:
```python
def test_ungrouped_doc_appears_under_no_series(self, qapp, mem_db):
    mem_db.create_document("My Story")
    dlg = OpenDocumentDialog(mem_db)
    assert any(n.startswith("(No Series)") for n in _series_names(dlg))
    _select_series(dlg, "(No Series)")
    assert "My Story" in _chapter_titles(dlg)
```

`test_grouped_doc_appears_under_series`:
```python
def test_grouped_doc_appears_under_series(self, qapp, mem_db):
    mem_db.create_document("Ch1", series_title="My Novel", series_order=1, chapter_title="Chapter 1")
    dlg = OpenDocumentDialog(mem_db)
    assert any(n.startswith("My Novel") for n in _series_names(dlg))
    _select_series(dlg, "My Novel")
    assert "Chapter 1" in _chapter_titles(dlg)
```

`test_documents_grouped_correctly`:
```python
def test_documents_grouped_correctly(self, qapp, mem_db):
    mem_db.create_document("C1", series_title="Novel", series_order=1, chapter_title="Ch 1")
    mem_db.create_document("C2", series_title="Novel", series_order=2, chapter_title="Ch 2")
    mem_db.create_document("Standalone")
    dlg = OpenDocumentDialog(mem_db)
    names = _series_names(dlg)
    assert any(n.startswith("Novel") for n in names)
    assert any(n.startswith("(No Series)") for n in names)
    _select_series(dlg, "Novel")
    assert len(_chapter_titles(dlg)) == 2
```

`test_progress_shown_for_document` — Progress is now col 2:
```python
def test_progress_shown_for_document(self, qapp, mem_db):
    doc_id = mem_db.create_document("Story")
    mem_db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Translated"},
        {"line_number": 1, "prefix": "%", "raw_text": "B", "translated_text": ""},
    ])
    dlg = OpenDocumentDialog(mem_db)
    leaf = _first_chapter(dlg)
    assert leaf is not None
    assert "50%" in leaf.text(2)
```

`test_series_header_shows_doc_count`:
```python
def test_series_header_shows_doc_count(self, qapp, mem_db):
    mem_db.create_document("C1", series_title="Novel", series_order=1, chapter_title="Ch 1")
    mem_db.create_document("C2", series_title="Novel", series_order=2, chapter_title="Ch 2")
    dlg = OpenDocumentDialog(mem_db)
    novel_entry = next(n for n in _series_names(dlg) if n.startswith("Novel"))
    assert "(2)" in novel_entry
```

`test_last_edited_column_exists` — Last Edited is now col 3:
```python
def test_last_edited_column_exists(self, qapp, mem_db):
    mem_db.create_document("Doc")
    dlg = OpenDocumentDialog(mem_db)
    assert dlg._tree.columnCount() == 4
    leaf = _first_chapter(dlg)
    assert leaf is not None
    assert leaf.text(3) != ""
```

`test_sort_last_edited_newest_first` — use `_sort_chapters(3)`:
```python
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
    dlg._sort_chapters(3)   # Last Edited ascending first
    dlg._sort_chapters(3)   # toggle → descending (newest first)
    titles = _chapter_titles(dlg)
    assert titles.index("NewDoc") < titles.index("OldDoc")
```

`test_sort_progress_asc` — use `_sort_chapters(2)`:
```python
def test_sort_progress_asc(self, qapp, mem_db):
    id_done = mem_db.create_document("Done", chapter_title="Done")
    id_none = mem_db.create_document("None", chapter_title="None")
    mem_db.save_lines(id_done, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "T"},
    ])
    dlg = OpenDocumentDialog(mem_db)
    dlg._sort_chapters(2)  # Progress ascending
    titles = _chapter_titles(dlg)
    assert titles.index("None") < titles.index("Done")
```

`test_sort_title_alpha` — use `_sort_chapters(1)`:
```python
def test_sort_title_alpha(self, qapp, mem_db):
    mem_db.create_document("Zebra", chapter_title="Zebra")
    mem_db.create_document("Apple", chapter_title="Apple")
    dlg = OpenDocumentDialog(mem_db)
    dlg._sort_chapters(1)  # Title A→Z
    titles = _chapter_titles(dlg)
    assert titles.index("Apple") < titles.index("Zebra")
```

`test_filter_hides_non_matching_leaves`:
```python
def test_filter_hides_non_matching_leaves(self, qapp, mem_db):
    mem_db.create_document("Alpha", chapter_title="Alpha")
    mem_db.create_document("Beta", chapter_title="Beta")
    dlg = OpenDocumentDialog(mem_db)
    dlg._filter_edit.setText("Alpha")
    assert not _chapter_is_hidden(dlg, "Alpha")
    assert _chapter_is_hidden(dlg, "Beta")
```

`test_filter_shows_all_on_clear`:
```python
def test_filter_shows_all_on_clear(self, qapp, mem_db):
    mem_db.create_document("Alpha", chapter_title="Alpha")
    mem_db.create_document("Beta", chapter_title="Beta")
    dlg = OpenDocumentDialog(mem_db)
    dlg._filter_edit.setText("Alpha")
    dlg._filter_edit.setText("")
    assert not _chapter_is_hidden(dlg, "Alpha")
    assert not _chapter_is_hidden(dlg, "Beta")
```

`test_current_doc_preselected` — title is now col 1:
```python
def test_current_doc_preselected(self, qapp, mem_db):
    doc_id = mem_db.create_document("My Doc")
    dlg = OpenDocumentDialog(mem_db, current_doc_id=doc_id)
    current = dlg._tree.currentItem()
    assert current is not None
    assert current.text(1) == "My Doc"
```

`test_do_edit_refreshes_tree`:
```python
def test_do_edit_refreshes_tree(self, qapp, mem_db):
    doc_id = mem_db.create_document("Old", chapter_title="Old Chapter")
    dlg = OpenDocumentDialog(mem_db)
    dlg._do_edit(doc_id, "", 0, "New Chapter")
    assert "New Chapter" in _chapter_titles(dlg)
    assert "Old Chapter" not in _chapter_titles(dlg)
```

`test_progress_zero_percent_color`, `test_progress_partial_color`, `test_progress_complete_color` — foreground now col 2:
```python
def test_progress_zero_percent_color(self, qapp, mem_db):
    mem_db.create_document("Story")
    dlg = OpenDocumentDialog(mem_db)
    leaf = _first_chapter(dlg)
    assert leaf.foreground(2).color().name() == "#888888"

def test_progress_partial_color(self, qapp, mem_db):
    doc_id = mem_db.create_document("Story")
    mem_db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Trans"},
        {"line_number": 1, "prefix": "%", "raw_text": "B", "translated_text": ""},
    ])
    dlg = OpenDocumentDialog(mem_db)
    leaf = _first_chapter(dlg)
    assert leaf.foreground(2).color().name() == "#c8a000"

def test_progress_complete_color(self, qapp, mem_db):
    doc_id = mem_db.create_document("Story")
    mem_db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Trans"},
    ])
    dlg = OpenDocumentDialog(mem_db)
    leaf = _first_chapter(dlg)
    assert leaf.foreground(2).color().name() == "#2a8a2a"
```

`test_edit_source_restores_selection_after_save`:
```python
def test_edit_source_restores_selection_after_save(self, qapp, mem_db):
    from unittest.mock import patch
    from translation_assistant.ui.dlg_open import _EditSourceDialog
    doc_id = mem_db.create_document("Story")
    mem_db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Hello", "translated_text": ""},
    ])
    dlg = OpenDocumentDialog(mem_db)
    dlg._tree.setCurrentItem(_first_chapter(dlg))
    with patch.object(_EditSourceDialog, "exec", return_value=QDialog.DialogCode.Accepted):
        with patch.object(_EditSourceDialog, "_on_save"):
            dlg._on_edit_source()
    current = dlg._tree.currentItem()
    assert current is not None
```

Add new test for chapter tree having 4 columns and `#` column:
```python
def test_chapter_tree_has_four_columns(self, qapp, mem_db):
    dlg = OpenDocumentDialog(mem_db)
    assert dlg._tree.columnCount() == 4
    assert dlg._tree.headerItem().text(0) == "#"
    assert dlg._tree.headerItem().text(1) == "Title"

def test_hash_column_shows_series_order(self, qapp, mem_db):
    mem_db.create_document("Ch", series_title="S", series_order=5, chapter_title="Ch")
    dlg = OpenDocumentDialog(mem_db)
    leaf = _first_chapter(dlg)
    assert leaf is not None
    assert leaf.text(0) == "5"

def test_no_preview_widget(self, qapp, mem_db):
    dlg = OpenDocumentDialog(mem_db)
    assert not hasattr(dlg, "_preview")

def test_no_sort_combo(self, qapp, mem_db):
    dlg = OpenDocumentDialog(mem_db)
    assert not hasattr(dlg, "_sort_combo")

def test_series_list_exists(self, qapp, mem_db):
    dlg = OpenDocumentDialog(mem_db)
    assert hasattr(dlg, "_series_list")
```

- [ ] **Step 6: Run tests**

```
source .venv/bin/activate && pytest tests/test_dlg_open.py -x --tb=short 2>&1 | head -60
```

At this point many tests will still fail because `_load_series` / `_load_chapters` are stubs. That's expected. The structural tests (`test_chapter_tree_has_four_columns`, `test_no_preview_widget`, etc.) should pass.

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "refactor(dlg_open): two-panel skeleton, remove preview/sort-combo"
```

---

### Task 3: Series Loading and Chapter Loading

Implements `_load_series()`, `_load_chapters()`, `_apply_filter()` for flat tree, and auto-selection.

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py`

**Interfaces:**
- Consumes: `dlg._series_list`, `dlg._tree`, `dlg._doc_ids`, `dlg._source_urls` (from Task 2)
- Produces: working series ↔ chapter navigation

- [ ] **Step 1: Run existing tests to see current failure set**

```
source .venv/bin/activate && pytest tests/test_dlg_open.py -q 2>&1 | tail -20
```

Note which tests are failing and why.

- [ ] **Step 2: Implement `_load_series`**

Replace the stub `_load_series` in `dlg_open.py`:

```python
    def _load_series(self) -> None:
        self._series_list.clear()
        docs = self._db.list_documents()

        series_counts: dict[str, int] = {}
        for doc in docs:
            key = doc["series_title"] or ""
            series_counts[key] = series_counts.get(key, 0) + 1

        if "" in series_counts:
            item = QListWidgetItem(f"{_NO_SERIES} ({series_counts['']})")
            item.setData(Qt.ItemDataRole.UserRole, "")
            self._series_list.addItem(item)

        for name in sorted(k for k in series_counts if k):
            item = QListWidgetItem(f"{name} ({series_counts[name]})")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._series_list.addItem(item)
```

- [ ] **Step 3: Implement `_load_chapters`**

Replace the stub `_load_chapters` in `dlg_open.py`:

```python
_CHAPTER_HEADERS = ["#", "Title", "Progress", "Last Edited"]

    def _load_chapters(self, series_raw: str) -> None:
        self._tree.clear()
        self._doc_ids.clear()
        self._source_urls.clear()

        docs = self._db.list_documents()
        docs = [d for d in docs if (d["series_title"] or "") == series_raw]
        docs.sort(key=lambda d: (d["series_order"], d["title"]))

        for doc in docs:
            display = doc["chapter_title"] if doc["chapter_title"] else doc["title"]
            progress_pct = doc["progress"]
            item = QTreeWidgetItem([
                str(doc["series_order"]),
                display,
                f"{progress_pct}%",
                _fmt_date(doc.get("updated_at", "")),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, doc["series_order"])
            item.setData(2, Qt.ItemDataRole.UserRole, progress_pct)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            if progress_pct == 0:
                item.setForeground(2, QColor("#888888"))
            elif progress_pct == 100:
                item.setForeground(2, QColor("#2a8a2a"))
            else:
                item.setForeground(2, QColor("#c8a000"))

            self._doc_ids[id(item)] = doc["id"]
            self._source_urls[id(item)] = doc.get("source_url", "")
            self._tree.addTopLevelItem(item)

        self._apply_filter(self._filter_edit.text())
        self._update_sort_header()
```

Note: `_CHAPTER_HEADERS` goes at module level (before the class), not inside the method.

- [ ] **Step 4: Update `_apply_filter` for flat tree**

Replace existing `_apply_filter`:

```python
    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            match = not query or query in item.text(1).lower()
            item.setHidden(not match)
```

- [ ] **Step 5: Run the tests**

```
source .venv/bin/activate && pytest tests/test_dlg_open.py -x --tb=short 2>&1 | head -80
```

Most tests should pass now. Sort tests will still fail (stub). Confirm the series/chapter navigation tests pass.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/dlg_open.py
git commit -m "feat(dlg_open): implement series and chapter loading"
```

---

### Task 4: Column Sort on Header Click

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py`

**Interfaces:**
- Consumes: `self._sort_col`, `self._sort_asc`, `self._tree` (from Task 2)
- Produces: `_sort_chapters(col: int)`, `_update_sort_header()`

- [ ] **Step 1: Implement `_update_sort_header` and `_sort_chapters`**

Replace the stub `_sort_chapters` in `dlg_open.py`:

```python
    _SORT_KEYS = {
        0: lambda item: item.data(0, Qt.ItemDataRole.UserRole) or 0,
        1: lambda item: item.text(1).lower(),
        2: lambda item: item.data(2, Qt.ItemDataRole.UserRole) or 0,
        3: lambda item: item.text(3),
    }

    def _sort_chapters(self, col: int) -> None:
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        count = self._tree.topLevelItemCount()
        items = [self._tree.takeTopLevelItem(0) for _ in range(count)]
        key_fn = self._SORT_KEYS.get(col, lambda item: item.text(1).lower())
        items.sort(key=key_fn, reverse=not self._sort_asc)
        for item in items:
            self._tree.addTopLevelItem(item)
        self._update_sort_header()

    def _update_sort_header(self) -> None:
        headers = ["#", "Title", "Progress", "Last Edited"]
        for col, label in enumerate(headers):
            if col == self._sort_col:
                arrow = " ▲" if self._sort_asc else " ▼"
            else:
                arrow = ""
            self._tree.headerItem().setText(col, label + arrow)
```

Note: `_SORT_KEYS` is a class attribute (place it inside the class body, before the methods).

- [ ] **Step 2: Run sort tests**

```
source .venv/bin/activate && pytest tests/test_dlg_open.py -k "sort" -v
```

Expected: all sort tests pass.

- [ ] **Step 3: Run full test suite**

```
source .venv/bin/activate && pytest tests/test_dlg_open.py -q
```

Expected: all tests pass (or only unrelated pre-existing failures).

- [ ] **Step 4: Commit**

```bash
git add translation_assistant/ui/dlg_open.py
git commit -m "feat(dlg_open): sortable column headers with asc/desc toggle"
```

---

### Task 5: Context Menus (Chapter and Series)

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py`

**Interfaces:**
- Consumes: `_current_leaf()`, `_doc_ids`, `_source_urls`, `_series_list` (Task 2/3)
- Produces: `_on_chapter_context_menu`, `_on_series_context_menu` (functional)

- [ ] **Step 1: Write test for chapter context menu open action**

Add to `TestOpenDocumentDialog` in `tests/test_dlg_open.py`:

```python
def test_chapter_context_menu_open_triggers_accept(self, qapp, mem_db):
    from unittest.mock import patch
    from PySide6.QtWidgets import QMenu
    doc_id = mem_db.create_document("Doc")
    dlg = OpenDocumentDialog(mem_db)
    leaf = _first_chapter(dlg)
    dlg._tree.setCurrentItem(leaf)

    open_action = None
    def fake_exec(pos):
        nonlocal open_action
        open_action = dlg._tree.customContextMenuRequested
        return menu_actions[0]  # "Open" is first action

    with patch.object(QMenu, "exec", side_effect=fake_exec) as mock_exec:
        with patch.object(QMenu, "addAction", wraps=QMenu.addAction) as mock_add:
            # Just verify the menu is created without crashing
            from PySide6.QtCore import QPoint
            dlg._on_chapter_context_menu(QPoint(0, 0))
```

This is a smoke test — the menu creation must not crash even with no visible item at pos (0,0).

Actually a simpler test: verify the method exists and doesn't raise:

```python
def test_chapter_context_menu_no_crash_no_selection(self, qapp, mem_db):
    from PySide6.QtCore import QPoint
    mem_db.create_document("Doc")
    dlg = OpenDocumentDialog(mem_db)
    # No current item; menu should silently do nothing
    dlg._on_chapter_context_menu(QPoint(0, 0))

def test_series_context_menu_no_crash_for_named_series(self, qapp, mem_db):
    from unittest.mock import patch
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu
    mem_db.create_document("Ch", series_title="Novel", chapter_title="Ch")
    dlg = OpenDocumentDialog(mem_db)
    dlg._series_list.setCurrentRow(0)
    with patch.object(QMenu, "exec", return_value=None):
        dlg._on_series_context_menu(QPoint(0, 0))
```

- [ ] **Step 2: Run these tests to confirm they fail (methods are stubs)**

```
source .venv/bin/activate && pytest tests/test_dlg_open.py -k "context_menu" -v
```

- [ ] **Step 3: Implement `_on_chapter_context_menu`**

Replace stub in `dlg_open.py`:

```python
    def _on_chapter_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        self._tree.setCurrentItem(item)
        menu = QMenu(self)
        act_open = menu.addAction("Open")
        menu.addSeparator()
        act_edit = menu.addAction("Edit…")
        act_edit_src = menu.addAction("Edit Source…")
        menu.addSeparator()
        act_refetch = menu.addAction("Re-fetch")
        act_refetch.setEnabled(bool(self._source_urls.get(id(item), "")))
        menu.addSeparator()
        act_delete = menu.addAction("Delete")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen == act_open:
            self._on_open()
        elif chosen == act_edit:
            self._on_edit()
        elif chosen == act_edit_src:
            self._on_edit_source()
        elif chosen == act_refetch:
            self._on_refetch()
        elif chosen == act_delete:
            self._on_delete()
```

- [ ] **Step 4: Implement `_on_series_context_menu`**

Replace stub in `dlg_open.py`:

```python
    def _on_series_context_menu(self, pos) -> None:
        item = self._series_list.itemAt(pos)
        if item is None:
            return
        series_raw = item.data(Qt.ItemDataRole.UserRole)
        if series_raw == "":
            return  # no menu for (No Series)
        menu = QMenu(self)
        act = menu.addAction("Manage Series…")
        if menu.exec(self._series_list.viewport().mapToGlobal(pos)) == act:
            self._open_series_manager()
```

- [ ] **Step 5: Run tests**

```
source .venv/bin/activate && pytest tests/test_dlg_open.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "feat(dlg_open): chapter and series right-click context menus"
```

---

### Task 6: Series Persistence and Wire-Up in `main_widget.py`

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py`
- Modify: `translation_assistant/ui/main_widget.py:1126-1130`

**Interfaces:**
- Consumes: `AppSettings.open_dialog_last_series` (Task 1)
- Produces: dialog remembers last series across opens

- [ ] **Step 1: Write test**

Add to `tests/test_dlg_open.py`:

```python
def test_last_series_restored_on_open(self, qapp, mem_db, tmp_settings):
    from unittest.mock import MagicMock
    mem_db.create_document("Ch1", series_title="Novel A", chapter_title="Ch1")
    mem_db.create_document("Ch2", series_title="Novel B", chapter_title="Ch2")
    tmp_settings.open_dialog_last_series = "Novel B"
    dlg = OpenDocumentDialog(mem_db, settings=tmp_settings)
    selected = dlg._series_list.currentItem()
    assert selected is not None
    assert selected.data(Qt.ItemDataRole.UserRole) == "Novel B"

def test_series_selection_saved_to_settings(self, qapp, mem_db, tmp_settings):
    mem_db.create_document("Ch1", series_title="Novel A", chapter_title="Ch1")
    mem_db.create_document("Ch2", series_title="Novel B", chapter_title="Ch2")
    dlg = OpenDocumentDialog(mem_db, settings=tmp_settings)
    _select_series(dlg, "Novel A")
    assert tmp_settings.open_dialog_last_series == "Novel A"
```

Add `from PySide6.QtCore import Qt` import to tests if not present.

- [ ] **Step 2: Run to confirm failure**

```
source .venv/bin/activate && pytest tests/test_dlg_open.py -k "last_series" -v
```

Expected: `TypeError` (dialog does not accept `settings` kwarg yet)

- [ ] **Step 3: Add `settings` parameter to `OpenDocumentDialog.__init__`**

Update `__init__` signature:

```python
    def __init__(self, db: Database, parent=None, *,
                 current_doc_id: int | None = None,
                 settings=None) -> None:
        super().__init__(parent)
        self._db = db
        self._settings = settings
        self._selected_doc_id: int | None = None
        self._doc_ids: dict[int, int] = {}
        self._source_urls: dict[int, str] = {}
        self._refetch_worker = None
        self._setup_ui()
        self._load_series()
        if current_doc_id is not None:
            self._select_doc(current_doc_id)
        else:
            self._restore_initial_series()
```

Add `_restore_initial_series` method:

```python
    def _restore_initial_series(self) -> None:
        last = self._settings.open_dialog_last_series if self._settings else ""
        if last:
            for i in range(self._series_list.count()):
                if self._series_list.item(i).data(Qt.ItemDataRole.UserRole) == last:
                    self._series_list.setCurrentRow(i)
                    return
        if self._series_list.count():
            self._series_list.setCurrentRow(0)
```

Update `_on_series_selected` to save the selection:

```python
    def _on_series_selected(self, current, _prev) -> None:
        if current is None:
            self._tree.clear()
            self._doc_ids.clear()
            self._source_urls.clear()
            return
        series_raw = current.data(Qt.ItemDataRole.UserRole)
        self._load_chapters(series_raw)
        if self._settings:
            self._settings.open_dialog_last_series = series_raw
```

- [ ] **Step 4: Wire up in `main_widget.py`**

Update `_on_open` at line ~1128:

```python
    def _on_open(self) -> None:
        from translation_assistant.ui.dlg_open import OpenDocumentDialog
        with self._topmost_suspended():
            dlg = OpenDocumentDialog(
                self._db, parent=self,
                current_doc_id=self._doc_id,
                settings=self._settings,
            )
            if dlg.exec() and dlg.selected_doc_id is not None:
                self.open_document(dlg.selected_doc_id)
```

- [ ] **Step 5: Run all tests**

```
source .venv/bin/activate && pytest tests/test_dlg_open.py tests/test_settings.py -q
```

Expected: all pass.

- [ ] **Step 6: Run full test suite**

```
source .venv/bin/activate && pytest -q 2>&1 | tail -20
```

Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/dlg_open.py translation_assistant/ui/main_widget.py tests/test_dlg_open.py
git commit -m "feat(dlg_open): persist last selected series across opens"
```

---

### Task 7: Smoke Test in App

**Files:** none (manual verification)

- [ ] **Step 1: Launch app**

```
source .venv/bin/activate && python -m translation_assistant.main
```

- [ ] **Step 2: Open document dialog and verify**

1. File → Open (or Ctrl+O)
2. Left panel shows series names with counts
3. Click a series → right panel loads chapters with `#`, Title, Progress, Last Edited columns
4. Click a column header → sorts asc; click again → desc; arrow appears in header
5. Type in filter → chapters filter in real time; clear → all return
6. Right-click a chapter → menu shows Open / Edit… / Edit Source… / Re-fetch / Delete
7. Right-click a named series → "Manage Series…" appears; right-click "(No Series)" → no menu
8. Close and reopen dialog → last selected series is restored
9. Double-click a chapter → dialog closes and that document opens

- [ ] **Step 3: Final commit if any fixups needed**

```bash
git add -p
git commit -m "fix(dlg_open): post-smoke-test fixups"
```

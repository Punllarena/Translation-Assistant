# Open Dialog Volume Column Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each chapter's `volume_title` directly in `OpenDocumentDialog`'s chapter tree, so the grouping is visible without opening "Edit Volume…".

**Architecture:** No new data plumbing at all — `Database.list_documents()` already returns `volume_title` and `_load_chapters` already caches it per row in `self._volume_titles` (for the "Edit Volume…" enable/disable guard). This plan is a display-only change to `translation_assistant/ui/dlg_open.py`: one more column on the existing flat `QTreeWidget`, one more entry in `_SORT_KEYS`, one label in `_CHAPTER_HEADERS`.

**Column-index decision.** The spec asks for the Volume column to appear between "#" and "Title". The tree addresses columns by hardcoded logical index in a dozen places (`_SORT_KEYS`, `_apply_filter`, `_renumber_by_title`, `leaf.text(1)`, `setForeground(2, …)`, the alignment calls, `setData(0/2/3/4, …)`) plus ~13 test assertions, so *inserting* at logical index 1 means renumbering all of them for a cosmetic result. Instead: append the column as logical index 7 and move it into visual position 1 with `QHeaderView.moveSection(7, 1)`. Qt keeps logical indices stable under a visual section move — sort clicks, resize modes and `_update_sort_header` all keep working on logical indices — so the user sees the spec's order with zero renumbering. If a later change genuinely needs logical order to match visual order, that renumbering is a separate mechanical refactor.

**Tech Stack:** PySide6 `QTreeWidget`/`QHeaderView` only. No schema change, no new query, no new dependency.

## Global Constraints

- Display only: `_apply_filter` stays scoped to the Title column (col 1) per spec.
- `volume_title` sorts as plain text; blank sorts first. No special-casing.
- Activate the venv first: `source .venv/bin/activate`.

---

## Task 1: Volume column in the chapter tree

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py`
- Test: `tests/test_dlg_open.py`

**Interfaces:**
- Produces: chapter tree gains logical column 7 labelled `"Volume"`, displayed at visual position 1. `_CHAPTER_HEADERS` grows to 8 entries; `_SORT_KEYS` gains key `7`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dlg_open.py` (new class at the end of the file):

```python
class TestVolumeColumn:
    def test_tree_shows_volume_title_column(self, qapp, mem_db):
        mem_db.create_document("Ch 1", series_title="S", series_order=1,
                               volume_title="Vol 1", chapter_title="Ch 1")
        mem_db.create_document("Ch 2", series_title="S", series_order=2,
                               chapter_title="Ch 2")  # no volume
        dlg = OpenDocumentDialog(mem_db)
        assert dlg._tree.headerItem().text(7).startswith("Volume")
        assert dlg._tree.topLevelItem(0).text(7) == "Vol 1"
        assert dlg._tree.topLevelItem(1).text(7) == ""

    def test_volume_column_shown_after_order_column(self, qapp, mem_db):
        dlg = OpenDocumentDialog(mem_db)
        assert dlg._tree.header().visualIndex(7) == 1

    def test_volume_column_sorts_as_text(self, qapp, mem_db):
        mem_db.create_document("Ch 1", series_title="S", series_order=1,
                               volume_title="Vol 2", chapter_title="Ch 1")
        mem_db.create_document("Ch 2", series_title="S", series_order=2,
                               volume_title="Vol 1", chapter_title="Ch 2")
        dlg = OpenDocumentDialog(mem_db)
        dlg._sort_chapters(7)
        assert [dlg._tree.topLevelItem(i).text(7) for i in range(2)] == ["Vol 1", "Vol 2"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dlg_open.py::TestVolumeColumn -v`
Expected: FAIL — `IndexError`/empty header text for column 7 (the tree only has 7 columns, 0-6).

- [ ] **Step 3: Add the header label and sort key**

In `dlg_open.py` line 18:

```python
_CHAPTER_HEADERS = ["#", "Title", "Progress", "Lines", "Images", "Last Edited", "WP", "Volume"]
```

In `_SORT_KEYS` (line 41-49), add:

```python
        7: lambda item: item.text(7).lower(),
```

- [ ] **Step 4: Widen the tree and move the section visually**

In `_setup_ui` (around line 98-107), bump the column count, add the resize mode, and move the section:

```python
        self._tree.setColumnCount(8)
        ...
        self._tree.header().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        # Volume is logical col 7 but displays right after "#"; a visual move keeps
        # every other column's logical index (and all the index-keyed code) unchanged.
        self._tree.header().moveSection(7, 1)
```

- [ ] **Step 5: Populate the cell in `_load_chapters`**

In the `QTreeWidgetItem([...])` construction (around line 190-198), append one element after `_wp_cell`:

```python
                _wp_cell,
                doc.get("volume_title", "") or "",
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_dlg_open.py::TestVolumeColumn -v`
Expected: PASS

- [ ] **Step 7: Fix the column-count assertions in existing tests**

Three existing assertions hardcode the old count — `tests/test_dlg_open.py` lines ~235, ~443, ~596: `assert dlg._tree.columnCount() == 7` → `== 8`. Nothing else in the file needs touching (every other assertion uses columns 0-6, whose logical indices are unchanged).

- [ ] **Step 8: Run the full `test_dlg_open.py` suite**

Run: `pytest tests/test_dlg_open.py -v`
Expected: PASS — no regressions.

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "feat(ui): show Volume column in OpenDocumentDialog chapter tree"
```

---

## Task 2: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 2: Manual smoke test**

Run the app, **File → Open…**, select an EPUB-imported series: the Volume cell shows the volume title right after "#", blank for plain/syosetu documents. Click the Volume header to confirm the sort arrow appears there and rows reorder by volume; click again for descending. Rename a volume via **Edit Volume…** and confirm the column updates without reopening the dialog (`_do_edit_volume` already reloads the tree). Drag a row to reorder and confirm `#` renumbering still works with the moved section.

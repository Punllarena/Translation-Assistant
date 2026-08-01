# Edit Volume Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user edit the five denormalized volume-metadata columns (`volume_title`, `volume_author`, `volume_illustrator`, `volume_publisher`, `volume_identifier`) on an already-imported EPUB volume from `OpenDocumentDialog`, instead of only being able to set them once at import time.

**Architecture:** These five columns are duplicated onto every chapter row of a volume (`documents` rows sharing the same `series_title` + `volume_title`) — the same denormalization `volume_title` itself already uses, and the same convention `_on_export_epub_series` relies on when it reads them off "the first document in the volume group" (`main_widget.py:1244`). A single-row update would desync the group and make export read stale values from whichever row happens to be first, so editing must be a bulk operation scoped to the whole `(series_title, volume_title)` pair — including the rename case, where every row's `volume_title` must move together or the group silently splits in two. This is a new `Database.update_volume_metadata()` bulk-UPDATE method plus a new `_EditVolumeMetadataDialog` in `dlg_open.py`, mirroring the existing `_EditMetadataDialog`/`_on_edit`/`_do_edit` pattern already in that file for per-chapter fields.

**Tech Stack:** Same as the rest of the project — stdlib `sqlite3` (via `Database._conn`), PySide6 `QDialog`/`QFormLayout`/`QLineEdit`. No new dependencies.

## Global Constraints

- Never import `sqlite3` outside `db.py`.
- All five columns already exist on `documents` (added across the three prior EPUB plans) — no schema migration needed in this plan.
- The "Edit Volume…" button must only be enabled when the selected chapter's `volume_title` is non-empty. Calling the bulk update with an empty `volume_title` would match every plain/syosetu-imported document in the series that has no real volume grouping (they all share `volume_title == ""`), silently corrupting unrelated documents. The UI guard is the only thing preventing this — `update_volume_metadata()` itself does not special-case blank `volume_title`.
- Activate the venv before running anything: `source .venv/bin/activate`.

---

## Task 1: `Database.update_volume_metadata()` — bulk update across a volume group

**Files:**
- Modify: `translation_assistant/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `Database.update_volume_metadata(series_title: str, volume_title: str, *, new_volume_title: str, volume_author: str, volume_illustrator: str, volume_publisher: str, volume_identifier: str) -> int` — returns the number of rows updated.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
def test_update_volume_metadata_updates_all_matching_documents(db):
    doc1 = db.create_document("Ch 1", series_title="S", volume_title="V1", chapter_title="Ch 1")
    doc2 = db.create_document("Ch 2", series_title="S", volume_title="V1", chapter_title="Ch 2")
    count = db.update_volume_metadata(
        "S", "V1",
        new_volume_title="V1",
        volume_author="New Author",
        volume_illustrator="New Illustrator",
        volume_publisher="New Publisher",
        volume_identifier="urn:isbn:1111111111111",
    )
    assert count == 2
    for doc_id in (doc1, doc2):
        meta = db.get_document(doc_id)
        assert meta["volume_author"] == "New Author"
        assert meta["volume_illustrator"] == "New Illustrator"
        assert meta["volume_publisher"] == "New Publisher"
        assert meta["volume_identifier"] == "urn:isbn:1111111111111"


def test_update_volume_metadata_renames_volume_title_across_group(db):
    doc1 = db.create_document("Ch 1", series_title="S", volume_title="Old Name", chapter_title="Ch 1")
    doc2 = db.create_document("Ch 2", series_title="S", volume_title="Old Name", chapter_title="Ch 2")
    db.update_volume_metadata(
        "S", "Old Name",
        new_volume_title="New Name",
        volume_author="", volume_illustrator="", volume_publisher="", volume_identifier="",
    )
    assert db.get_document(doc1)["volume_title"] == "New Name"
    assert db.get_document(doc2)["volume_title"] == "New Name"


def test_update_volume_metadata_scoped_to_series(db):
    # Two series happen to share the volume_title string "V1" -- only the
    # matching series's documents may be touched.
    doc_s = db.create_document("Ch 1", series_title="S", volume_title="V1", chapter_title="Ch 1")
    doc_t = db.create_document("Ch 1", series_title="T", volume_title="V1", chapter_title="Ch 1")
    db.update_volume_metadata(
        "S", "V1",
        new_volume_title="V1", volume_author="Author S",
        volume_illustrator="", volume_publisher="", volume_identifier="",
    )
    assert db.get_document(doc_s)["volume_author"] == "Author S"
    assert db.get_document(doc_t)["volume_author"] == ""


def test_update_volume_metadata_does_not_touch_other_volumes(db):
    doc_v1 = db.create_document("Ch 1", series_title="S", volume_title="V1", chapter_title="Ch 1")
    doc_v2 = db.create_document("Ch 1", series_title="S", volume_title="V2", chapter_title="Ch 1")
    db.update_volume_metadata(
        "S", "V1",
        new_volume_title="V1", volume_author="Author V1",
        volume_illustrator="", volume_publisher="", volume_identifier="",
    )
    assert db.get_document(doc_v1)["volume_author"] == "Author V1"
    assert db.get_document(doc_v2)["volume_author"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -k update_volume_metadata -v`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'update_volume_metadata'`

- [ ] **Step 3: Implement `update_volume_metadata`**

Add to `db.py`, near `update_document_metadata` (around line 322):

```python
    def update_volume_metadata(self, series_title: str, volume_title: str, *,
                               new_volume_title: str,
                               volume_author: str,
                               volume_illustrator: str,
                               volume_publisher: str,
                               volume_identifier: str) -> int:
        """
        Bulk-updates the five denormalized volume-metadata columns across
        every document row sharing (series_title, volume_title) -- these
        columns are duplicated onto every chapter row (same pattern as
        volume_title itself), so a rename or metadata edit must propagate to
        every row in the group. Otherwise export's "read the first row"
        convention (main_widget.py's _on_export_epub_series) would read
        stale/mismatched values from whichever row happens to sort first.
        Returns the number of rows updated.
        """
        cur = self._conn.execute(
            "UPDATE documents SET volume_title=?, volume_author=?, volume_illustrator=?, "
            "volume_publisher=?, volume_identifier=? WHERE series_title=? AND volume_title=?",
            (new_volume_title, volume_author, volume_illustrator, volume_publisher,
             volume_identifier, series_title, volume_title),
        )
        self._conn.commit()
        return cur.rowcount
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -k update_volume_metadata -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_db.py` suite**

Run: `pytest tests/test_db.py -v`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add update_volume_metadata() for bulk volume-group edits"
```

---

## Task 2: `Database.list_documents()` exposes `volume_title`

**Files:**
- Modify: `translation_assistant/db.py` (`list_documents`)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `list_documents()`'s returned dicts gain a `"volume_title"` key. Needed by Task 3 to decide whether the "Edit Volume…" button should be enabled for the currently selected chapter, without an extra `get_document()` round-trip per row.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_list_documents_includes_volume_title(db):
    db.create_document("Ch 1", volume_title="Vol 1")
    docs = db.list_documents()
    assert docs[0]["volume_title"] == "Vol 1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -k list_documents_includes_volume_title -v`
Expected: FAIL with `KeyError: 'volume_title'`

- [ ] **Step 3: Add the column to the SELECT**

In `db.py`, `list_documents` (around line 285), add `d.volume_title` to the column list:

```python
    def list_documents(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT d.id, d.title, d.series_title, d.series_order, d.chapter_title,
                   d.updated_at, d.last_position, d.source_url, d.wp_status, d.wp_date,
                   d.volume_title,
                   CAST(COALESCE(
                       SUM(CASE WHEN TRIM(l.raw_text) != '' AND l.translated_text != '' THEN 1 ELSE 0 END) * 100
                       / NULLIF(SUM(CASE WHEN TRIM(l.raw_text) != '' THEN 1 ELSE 0 END), 0), 0
                   ) AS INTEGER) AS progress
            FROM documents d
            LEFT JOIN lines l ON l.document_id = d.id
            GROUP BY d.id
            ORDER BY d.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
```

(Only the added `d.volume_title,` line — everything else in the method is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -k list_documents_includes_volume_title -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_db.py` suite**

Run: `pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): list_documents() includes volume_title"
```

---

## Task 3: `dlg_open.py` — "Edit Volume…" button and `_EditVolumeMetadataDialog`

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py` (`OpenDocumentDialog.__init__`, `_setup_ui`, `_load_chapters`, `_on_chapter_selection_changed`; new `_on_edit_volume`/`_do_edit_volume` methods; new `_EditVolumeMetadataDialog` class)
- Test: `tests/test_dlg_open.py`

**Interfaces:**
- Consumes: `Database.update_volume_metadata` (Task 1), `list_documents()`'s `"volume_title"` key (Task 2).
- Produces: `OpenDocumentDialog._edit_volume_btn`, `OpenDocumentDialog._do_edit_volume(doc_id, series_title, old_volume_title, new_volume_title, volume_author, volume_illustrator, volume_publisher, volume_identifier) -> None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dlg_open.py`, a new class after `TestOpenDocumentDialog`:

```python
class TestEditVolumeMetadata:
    def test_edit_volume_btn_disabled_for_non_volume_document(self, qapp, mem_db):
        mem_db.create_document("Doc")  # no volume_title -- plain/legacy document
        dlg = OpenDocumentDialog(mem_db)
        dlg._tree.setCurrentItem(_first_leaf(dlg))
        assert not dlg._edit_volume_btn.isEnabled()

    def test_edit_volume_btn_enabled_for_volume_document(self, qapp, mem_db):
        mem_db.create_document("Doc", volume_title="Vol 1")
        dlg = OpenDocumentDialog(mem_db)
        dlg._tree.setCurrentItem(_first_leaf(dlg))
        assert dlg._edit_volume_btn.isEnabled()

    def test_do_edit_volume_updates_all_chapters_in_group(self, qapp, mem_db):
        doc1 = mem_db.create_document(
            "Ch 1", series_title="S", volume_title="Vol 1", chapter_title="Ch 1"
        )
        doc2 = mem_db.create_document(
            "Ch 2", series_title="S", volume_title="Vol 1", chapter_title="Ch 2"
        )
        dlg = OpenDocumentDialog(mem_db)
        dlg._do_edit_volume(
            doc1, "S", "Vol 1",
            new_volume_title="Vol 1 Renamed",
            volume_author="Author Name",
            volume_illustrator="Illustrator Name",
            volume_publisher="Publisher Name",
            volume_identifier="urn:isbn:1234567890123",
        )
        for doc_id in (doc1, doc2):
            meta = mem_db.get_document(doc_id)
            assert meta["volume_title"] == "Vol 1 Renamed"
            assert meta["volume_author"] == "Author Name"
            assert meta["volume_illustrator"] == "Illustrator Name"
            assert meta["volume_publisher"] == "Publisher Name"
            assert meta["volume_identifier"] == "urn:isbn:1234567890123"

    def test_do_edit_volume_refreshes_tree_selection(self, qapp, mem_db):
        doc_id = mem_db.create_document(
            "Ch 1", series_title="S", volume_title="Vol 1", chapter_title="Ch 1"
        )
        dlg = OpenDocumentDialog(mem_db)
        dlg._do_edit_volume(
            doc_id, "S", "Vol 1",
            new_volume_title="Vol 1",
            volume_author="Author Name", volume_illustrator="", volume_publisher="", volume_identifier="",
        )
        assert dlg._doc_ids[id(dlg._tree.currentItem())] == doc_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dlg_open.py::TestEditVolumeMetadata -v`
Expected: FAIL — `AttributeError: 'OpenDocumentDialog' object has no attribute '_edit_volume_btn'` / `'_do_edit_volume'`

- [ ] **Step 3: Add the `_volume_titles` cache and the button**

In `__init__` (around line 57), add a cache dict alongside `_source_urls`:

```python
        self._source_urls: dict[int, str] = {}
        self._volume_titles: dict[int, str] = {}
```

In `_setup_ui` (around line 126-138), add the new button next to `_edit_btn`:

```python
        self._edit_btn = QPushButton("Edit…")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit)
        self._edit_volume_btn = QPushButton("Edit Volume…")
        self._edit_volume_btn.setEnabled(False)
        self._edit_volume_btn.clicked.connect(self._on_edit_volume)
        self._edit_source_btn = QPushButton("Edit Source…")
```

And add it to the enable/disable loop and the layout loop:

```python
        for btn in (self._open_btn, self._edit_btn, self._edit_volume_btn, self._edit_source_btn,
                    self._delete_btn, self._refetch_btn, cancel_btn):
            btn_row.addWidget(btn)
```

- [ ] **Step 4: Populate the cache in `_load_chapters` and clear it in `_on_series_selected`**

In `_load_chapters` (around line 169-171), clear the new cache alongside the existing ones:

```python
        self._doc_ids.clear()
        self._source_urls.clear()
        self._volume_titles.clear()
```

Inside the per-document loop (around line 207-208), cache the volume title:

```python
            self._doc_ids[id(item)] = doc["id"]
            self._source_urls[id(item)] = doc.get("source_url", "")
            self._volume_titles[id(item)] = doc.get("volume_title", "")
            self._tree.addTopLevelItem(item)
```

In `_on_series_selected`'s empty-selection branch (around line 226-229), clear it too:

```python
        if current is None:
            self._tree.clear()
            self._doc_ids.clear()
            self._source_urls.clear()
            self._volume_titles.clear()
            return
```

- [ ] **Step 5: Wire enable/disable logic**

In `_on_chapter_selection_changed` (around line 370-378), add the new button:

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
        has_volume = is_leaf and bool(self._volume_titles.get(id(leaf), ""))
        self._edit_volume_btn.setEnabled(has_volume)
```

- [ ] **Step 6: Add `_on_edit_volume`, `_do_edit_volume`, and `_EditVolumeMetadataDialog`**

Add `_on_edit_volume` next to `_on_edit` (around line 425):

```python
    def _on_edit_volume(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        doc_id = self._doc_ids[id(leaf)]
        doc = self._db.get_document(doc_id)
        dlg = _EditVolumeMetadataDialog(
            volume_title=doc["volume_title"],
            volume_author=doc["volume_author"],
            volume_illustrator=doc["volume_illustrator"],
            volume_publisher=doc["volume_publisher"],
            volume_identifier=doc["volume_identifier"],
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._do_edit_volume(
                doc_id, doc["series_title"], doc["volume_title"],
                new_volume_title=dlg.volume_title,
                volume_author=dlg.volume_author,
                volume_illustrator=dlg.volume_illustrator,
                volume_publisher=dlg.volume_publisher,
                volume_identifier=dlg.volume_identifier,
            )
```

Add `_do_edit_volume` next to `_do_edit` (around line 505):

```python
    def _do_edit_volume(self, doc_id: int, series_title: str, old_volume_title: str, *,
                        new_volume_title: str, volume_author: str, volume_illustrator: str,
                        volume_publisher: str, volume_identifier: str) -> None:
        self._db.update_volume_metadata(
            series_title, old_volume_title,
            new_volume_title=new_volume_title,
            volume_author=volume_author,
            volume_illustrator=volume_illustrator,
            volume_publisher=volume_publisher,
            volume_identifier=volume_identifier,
        )
        series_raw = self._current_series_raw()
        self._load_series()
        self._restore_series(series_raw)
        self._select_doc(doc_id)
```

Add the new dialog class next to `_EditMetadataDialog` (around line 587):

```python
class _EditVolumeMetadataDialog(QDialog):
    def __init__(self, *, volume_title: str, volume_author: str, volume_illustrator: str,
                 volume_publisher: str, volume_identifier: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Volume Metadata")
        self.setMinimumWidth(380)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setSpacing(4)

        self._volume_edit = QLineEdit(volume_title)
        form.addRow("Volume Title:", self._volume_edit)

        self._author_edit = QLineEdit(volume_author)
        form.addRow("Author:", self._author_edit)

        self._illustrator_edit = QLineEdit(volume_illustrator)
        form.addRow("Illustrator:", self._illustrator_edit)

        self._publisher_edit = QLineEdit(volume_publisher)
        form.addRow("Publisher:", self._publisher_edit)

        self._identifier_edit = QLineEdit(volume_identifier)
        form.addRow("ISBN:", self._identifier_edit)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Save")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    @property
    def volume_title(self) -> str:
        return self._volume_edit.text().strip()

    @property
    def volume_author(self) -> str:
        return self._author_edit.text().strip()

    @property
    def volume_illustrator(self) -> str:
        return self._illustrator_edit.text().strip()

    @property
    def volume_publisher(self) -> str:
        return self._publisher_edit.text().strip()

    @property
    def volume_identifier(self) -> str:
        return self._identifier_edit.text().strip()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_dlg_open.py::TestEditVolumeMetadata -v`
Expected: PASS

- [ ] **Step 8: Run the full `test_dlg_open.py` suite**

Run: `pytest tests/test_dlg_open.py -v`
Expected: PASS — every prior test in the file still passes (the new cache/button are additive; `_do_edit`/`_EditMetadataDialog` are untouched).

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "feat(ui): OpenDocumentDialog gets an Edit Volume… action for volume-wide metadata"
```

---

## Task 4: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -q`
Expected: PASS — all tests green, including everything added in Tasks 1-3.

- [ ] **Step 2: Manual smoke test**

Run the app, import one of the real EPUB files in `EPUB/` via **File → Import EPUB…**, then open **File → Open…**, select an imported chapter, and confirm **Edit Volume…** is enabled and prefilled with the real BookWalker author/illustrator/publisher/ISBN from that import. Change one field (e.g. the Author), save, re-open the dialog to confirm it stuck, then use **File → Export Series EPUB…** and open the resulting `.epub`'s OPF to confirm the edited value made it into the export (not the original imported value). Also confirm a plain (non-EPUB) document shows **Edit Volume…** disabled. This step is exploratory — its purpose is to catch anything the synthetic fixtures couldn't (e.g. the button state interacting with the existing `_edit_btn`/`_edit_source_btn` layout).

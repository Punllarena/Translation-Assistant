# EPUB Metadata for Scraped Series Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a scraped (non-epub-imported) series get an author/illustrator/publisher/identifier/cover/volume-title attached before EPUB export, via a "Set EPUB Metadata…" dialog in Series Manager.

**Architecture:** Four new/changed `db.py` methods do the actual writes (they operate on the existing `documents.volume_*` columns and `document_images` table — no schema change). A new standalone `SeriesEpubMetadataDialog` (mirrors `ImportEpubDialog`'s shape: own file, own test file, all logic reachable without calling `.exec()`) prefills from the DB and performs the writes on save. `dlg_series.py` gets one new context-menu action that opens it, mirroring the existing "Set WP Fields…" action.

**Tech Stack:** PySide6 (QDialog/QFormLayout/QFileDialog), sqlite3 via the existing `Database` class.

## Global Constraints

- Single volume only: the dialog always operates on the `volume_title=""` bucket a scraped series' docs already share. No multi-volume grouping UI.
- Never import `sqlite3` outside `db.py` (per CLAUDE.md) — all new queries live in `Database` methods.
- Follow `ImportEpubDialog`'s testing convention: dialogs must be fully exercisable without calling `QDialog.exec()`.

---

### Task 1: DB layer — volume metadata and cover read/write methods

**Files:**
- Modify: `translation_assistant/db.py` (add methods after `volume_has_cover`, around line 479)
- Test: `tests/test_db.py` (add after `test_volume_has_cover_isolated_by_volume`, around line 361)

**Interfaces:**
- Produces:
  - `Database.get_document_ids_by_volume(series_title: str, volume_title: str) -> list[int]`
  - `Database.get_volume_metadata(series_title: str, volume_title: str) -> dict` — keys `volume_title, volume_author, volume_illustrator, volume_publisher, volume_identifier, has_cover`
  - `Database.update_volume_metadata(series_title: str, volume_title: str, *, author: str = "", illustrator: str = "", publisher: str = "", identifier: str = "") -> int` — returns affected row count
  - `Database.set_volume_title(series_title: str, old_volume_title: str, new_volume_title: str) -> None`
  - `Database.replace_document_cover(document_id: int, src_path: str, data: bytes) -> None`
  - `Database.clear_document_cover(document_id: int) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py` right after `test_volume_has_cover_isolated_by_volume` (line 361):

```python
def test_get_document_ids_by_volume_filters_by_series_and_volume(db):
    d1 = db.create_document("Ch 1", series_title="S", volume_title="V1")
    db.create_document("Ch 1", series_title="S", volume_title="V2")
    db.create_document("Ch 1", series_title="Other", volume_title="V1")
    assert db.get_document_ids_by_volume("S", "V1") == [d1]


def test_get_document_ids_by_volume_orders_by_series_order(db):
    db.create_document("Ch 2", series_title="S", volume_title="V1", series_order=2)
    d1 = db.create_document("Ch 1", series_title="S", volume_title="V1", series_order=1)
    ids = db.get_document_ids_by_volume("S", "V1")
    assert ids[0] == d1


def test_get_volume_metadata_defaults_when_no_docs(db):
    meta = db.get_volume_metadata("Nope", "")
    assert meta == {
        "volume_title": "", "volume_author": "", "volume_illustrator": "",
        "volume_publisher": "", "volume_identifier": "", "has_cover": False,
    }


def test_get_volume_metadata_reads_existing_values(db):
    db.create_document(
        "Ch 1", series_title="S", volume_title="",
        volume_author="A", volume_illustrator="I",
        volume_publisher="P", volume_identifier="urn:x",
    )
    meta = db.get_volume_metadata("S", "")
    assert meta["volume_author"] == "A"
    assert meta["volume_illustrator"] == "I"
    assert meta["volume_publisher"] == "P"
    assert meta["volume_identifier"] == "urn:x"
    assert meta["has_cover"] is False


def test_get_volume_metadata_has_cover_true_after_cover_added(db):
    doc_id = db.create_document("Ch 1", series_title="S", volume_title="")
    db.add_document_image(doc_id, 0, True, "cover.jpg", b"data")
    assert db.get_volume_metadata("S", "")["has_cover"] is True


def test_update_volume_metadata_writes_all_docs_in_bucket(db):
    d1 = db.create_document("Ch 1", series_title="S", volume_title="")
    d2 = db.create_document("Ch 2", series_title="S", volume_title="")
    affected = db.update_volume_metadata(
        "S", "", author="A", illustrator="I", publisher="P", identifier="urn:x",
    )
    assert affected == 2
    for doc_id in (d1, d2):
        meta = db.get_document(doc_id)
        assert meta["volume_author"] == "A"
        assert meta["volume_illustrator"] == "I"
        assert meta["volume_publisher"] == "P"
        assert meta["volume_identifier"] == "urn:x"


def test_update_volume_metadata_does_not_touch_other_series(db):
    other = db.create_document("Ch 1", series_title="Other", volume_title="")
    db.create_document("Ch 1", series_title="S", volume_title="")
    db.update_volume_metadata("S", "", author="A")
    assert db.get_document(other)["volume_author"] == ""


def test_set_volume_title_moves_docs_to_new_bucket(db):
    d1 = db.create_document("Ch 1", series_title="S", volume_title="")
    db.set_volume_title("S", "", "My Volume")
    assert db.get_document(d1)["volume_title"] == "My Volume"


def test_set_volume_title_scoped_to_series(db):
    other = db.create_document("Ch 1", series_title="Other", volume_title="")
    db.create_document("Ch 1", series_title="S", volume_title="")
    db.set_volume_title("S", "", "My Volume")
    assert db.get_document(other)["volume_title"] == ""


def test_replace_document_cover_inserts_when_none_exists(db):
    doc_id = db.create_document("Ch 1")
    db.replace_document_cover(doc_id, "cover.jpg", b"data")
    images = db.get_document_images(doc_id)
    assert len(images) == 1
    assert images[0]["is_cover"] == 1
    assert images[0]["data"] == b"data"


def test_replace_document_cover_removes_old_cover_first(db):
    doc_id = db.create_document("Ch 1")
    db.add_document_image(doc_id, 0, True, "old.jpg", b"old")
    db.replace_document_cover(doc_id, "new.jpg", b"new")
    images = db.get_document_images(doc_id)
    assert len(images) == 1
    assert images[0]["src_path"] == "new.jpg"
    assert images[0]["data"] == b"new"


def test_replace_document_cover_leaves_non_cover_images_alone(db):
    doc_id = db.create_document("Ch 1")
    db.add_document_image(doc_id, 1, False, "inline.jpg", b"inline")
    db.replace_document_cover(doc_id, "cover.jpg", b"cover")
    images = db.get_document_images(doc_id)
    assert len(images) == 2
    assert {im["src_path"] for im in images} == {"inline.jpg", "cover.jpg"}


def test_clear_document_cover_removes_cover_only(db):
    doc_id = db.create_document("Ch 1")
    db.add_document_image(doc_id, 0, True, "cover.jpg", b"cover")
    db.add_document_image(doc_id, 1, False, "inline.jpg", b"inline")
    db.clear_document_cover(doc_id)
    images = db.get_document_images(doc_id)
    assert len(images) == 1
    assert images[0]["src_path"] == "inline.jpg"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_db.py -k "volume_metadata or document_ids_by_volume or set_volume_title or document_cover" -v`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'get_document_ids_by_volume'` (and similar for the other new methods).

- [ ] **Step 3: Implement the methods**

In `translation_assistant/db.py`, insert immediately after `volume_has_cover` (currently ends at line 479, right before `get_document_ids_by_series` at line 481):

```python
    def get_document_ids_by_volume(self, series_title: str, volume_title: str) -> list[int]:
        rows = self._conn.execute(
            "SELECT id FROM documents WHERE series_title = ? AND volume_title = ? "
            "ORDER BY series_order",
            (series_title, volume_title),
        ).fetchall()
        return [r[0] for r in rows]

    def get_volume_metadata(self, series_title: str, volume_title: str) -> dict:
        row = self._conn.execute(
            "SELECT volume_title, volume_author, volume_illustrator, "
            "volume_publisher, volume_identifier FROM documents "
            "WHERE series_title = ? AND volume_title = ? LIMIT 1",
            (series_title, volume_title),
        ).fetchone()
        if row is None:
            return {
                "volume_title": "", "volume_author": "", "volume_illustrator": "",
                "volume_publisher": "", "volume_identifier": "", "has_cover": False,
            }
        meta = dict(row)
        meta["has_cover"] = self.volume_has_cover(series_title, volume_title)
        return meta

    def update_volume_metadata(self, series_title: str, volume_title: str, *,
                               author: str = "", illustrator: str = "",
                               publisher: str = "", identifier: str = "") -> int:
        cur = self._conn.execute(
            "UPDATE documents SET volume_author = ?, volume_illustrator = ?, "
            "volume_publisher = ?, volume_identifier = ? "
            "WHERE series_title = ? AND volume_title = ?",
            (author, illustrator, publisher, identifier, series_title, volume_title),
        )
        self._conn.commit()
        return cur.rowcount

    def set_volume_title(self, series_title: str, old_volume_title: str, new_volume_title: str) -> None:
        self._conn.execute(
            "UPDATE documents SET volume_title = ? WHERE series_title = ? AND volume_title = ?",
            (new_volume_title, series_title, old_volume_title),
        )
        self._conn.commit()

    def replace_document_cover(self, document_id: int, src_path: str, data: bytes) -> None:
        self._conn.execute(
            "DELETE FROM document_images WHERE document_id = ? AND is_cover = 1",
            (document_id,),
        )
        self._conn.execute(
            "INSERT INTO document_images (document_id, anchor_position, is_cover, src_path, data) "
            "VALUES (?, 0, 1, ?, ?)",
            (document_id, src_path, data),
        )
        self._conn.commit()

    def clear_document_cover(self, document_id: int) -> None:
        self._conn.execute(
            "DELETE FROM document_images WHERE document_id = ? AND is_cover = 1",
            (document_id,),
        )
        self._conn.commit()

```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_db.py -k "volume_metadata or document_ids_by_volume or set_volume_title or document_cover" -v`
Expected: all PASS.

- [ ] **Step 5: Run the full DB test file to check for regressions**

Run: `source .venv/bin/activate && pytest tests/test_db.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add volume metadata and cover read/write methods"
```

---

### Task 2: SeriesEpubMetadataDialog

**Files:**
- Create: `translation_assistant/ui/dlg_series_epub_metadata.py`
- Test: Create `tests/test_dlg_series_epub_metadata.py`

**Interfaces:**
- Consumes: `Database.get_volume_metadata`, `Database.update_volume_metadata`, `Database.set_volume_title`, `Database.get_document_ids_by_volume`, `Database.replace_document_cover`, `Database.clear_document_cover` (all from Task 1).
- Produces: `SeriesEpubMetadataDialog(db: Database, series_title: str, parent=None)` — a `QDialog` subclass. Public widgets for testing: `_volume_edit`, `_author_edit`, `_illustrator_edit`, `_publisher_edit`, `_identifier_edit`, `_cover_label`. Handler methods: `_on_browse_cover()`, `_on_clear_cover()`, `_on_save()`. `_on_save()` performs all DB writes and calls `self.accept()`; it does not require `.exec()` to run.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dlg_series_epub_metadata.py`:

```python
"""
Tests for SeriesEpubMetadataDialog.
All tests bypass exec() — call internal methods directly and inspect state,
same convention as test_dlg_import_epub.py.
"""
import sqlite3

import pytest

from translation_assistant.db import Database
from translation_assistant.ui.dlg_series_epub_metadata import SeriesEpubMetadataDialog


@pytest.fixture
def mem_db(qapp):
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return db


class TestSeriesEpubMetadataDialog:
    def test_instantiates(self, qapp, mem_db):
        mem_db.create_document("Ch 1", series_title="S", volume_title="")
        dlg = SeriesEpubMetadataDialog(mem_db, "S")
        assert dlg is not None

    def test_prefills_from_existing_metadata(self, qapp, mem_db):
        mem_db.create_document(
            "Ch 1", series_title="S", volume_title="My Vol",
            volume_author="A", volume_illustrator="I",
            volume_publisher="P", volume_identifier="urn:x",
        )
        dlg = SeriesEpubMetadataDialog(mem_db, "S")
        assert dlg._volume_edit.text() == "My Vol"
        assert dlg._author_edit.text() == "A"
        assert dlg._illustrator_edit.text() == "I"
        assert dlg._publisher_edit.text() == "P"
        assert dlg._identifier_edit.text() == "urn:x"

    def test_cover_label_shows_none_when_no_cover(self, qapp, mem_db):
        mem_db.create_document("Ch 1", series_title="S", volume_title="")
        dlg = SeriesEpubMetadataDialog(mem_db, "S")
        assert dlg._cover_label.text() == "None"

    def test_cover_label_shows_set_when_cover_exists(self, qapp, mem_db):
        doc_id = mem_db.create_document("Ch 1", series_title="S", volume_title="")
        mem_db.add_document_image(doc_id, 0, True, "cover.jpg", b"data")
        dlg = SeriesEpubMetadataDialog(mem_db, "S")
        assert dlg._cover_label.text() != "None"

    def test_on_save_writes_metadata_to_all_docs_in_bucket(self, qapp, mem_db):
        d1 = mem_db.create_document("Ch 1", series_title="S", volume_title="")
        d2 = mem_db.create_document("Ch 2", series_title="S", volume_title="")
        dlg = SeriesEpubMetadataDialog(mem_db, "S")
        dlg._author_edit.setText("New Author")
        dlg._on_save()
        assert mem_db.get_document(d1)["volume_author"] == "New Author"
        assert mem_db.get_document(d2)["volume_author"] == "New Author"

    def test_on_save_changes_volume_title(self, qapp, mem_db):
        d1 = mem_db.create_document("Ch 1", series_title="S", volume_title="")
        dlg = SeriesEpubMetadataDialog(mem_db, "S")
        dlg._volume_edit.setText("Renamed Volume")
        dlg._on_save()
        assert mem_db.get_document(d1)["volume_title"] == "Renamed Volume"

    def test_on_save_accepts_dialog(self, qapp, mem_db):
        mem_db.create_document("Ch 1", series_title="S", volume_title="")
        dlg = SeriesEpubMetadataDialog(mem_db, "S")
        from PySide6.QtWidgets import QDialog
        dlg._on_save()
        assert dlg.result() == QDialog.DialogCode.Accepted

    def test_on_browse_cover_sets_pending_cover_and_updates_label(self, qapp, mem_db, tmp_path, monkeypatch):
        cover_path = tmp_path / "cover.jpg"
        cover_path.write_bytes(b"imgdata")
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_series_epub_metadata.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(cover_path), ""),
        )
        mem_db.create_document("Ch 1", series_title="S", volume_title="")
        dlg = SeriesEpubMetadataDialog(mem_db, "S")
        dlg._on_browse_cover()
        assert dlg._cover_label.text() == "cover.jpg"

    def test_on_save_writes_picked_cover(self, qapp, mem_db, tmp_path, monkeypatch):
        cover_path = tmp_path / "cover.jpg"
        cover_path.write_bytes(b"imgdata")
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_series_epub_metadata.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(cover_path), ""),
        )
        doc_id = mem_db.create_document("Ch 1", series_title="S", volume_title="")
        dlg = SeriesEpubMetadataDialog(mem_db, "S")
        dlg._on_browse_cover()
        dlg._on_save()
        images = mem_db.get_document_images(doc_id)
        assert len(images) == 1
        assert images[0]["is_cover"] == 1
        assert images[0]["data"] == b"imgdata"

    def test_on_clear_cover_removes_existing_cover_on_save(self, qapp, mem_db):
        doc_id = mem_db.create_document("Ch 1", series_title="S", volume_title="")
        mem_db.add_document_image(doc_id, 0, True, "cover.jpg", b"data")
        dlg = SeriesEpubMetadataDialog(mem_db, "S")
        dlg._on_clear_cover()
        dlg._on_save()
        assert mem_db.get_document_images(doc_id) == []

    def test_save_without_touching_cover_leaves_it_alone(self, qapp, mem_db):
        doc_id = mem_db.create_document("Ch 1", series_title="S", volume_title="")
        mem_db.add_document_image(doc_id, 0, True, "cover.jpg", b"data")
        dlg = SeriesEpubMetadataDialog(mem_db, "S")
        dlg._author_edit.setText("Someone")
        dlg._on_save()
        images = mem_db.get_document_images(doc_id)
        assert len(images) == 1
        assert images[0]["src_path"] == "cover.jpg"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_dlg_series_epub_metadata.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'translation_assistant.ui.dlg_series_epub_metadata'`.

- [ ] **Step 3: Implement the dialog**

Create `translation_assistant/ui/dlg_series_epub_metadata.py`:

```python
"""
Set EPUB Metadata dialog — attaches author/illustrator/publisher/identifier
and a cover image to a series' single (volume_title="") document bucket, so
scraped series can produce a properly-tagged EPUB without being re-imported
through ImportEpubDialog. Single-volume only: see
docs/superpowers/specs/2026-07-31-epub-metadata-for-scraped-series-design.md.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from translation_assistant.db import Database

_IMAGE_FILTER = "Images (*.jpg *.jpeg *.png *.gif *.webp)"


class SeriesEpubMetadataDialog(QDialog):

    def __init__(self, db: Database, series_title: str, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._series_title = series_title
        self._volume_title = ""  # the single bucket this dialog always operates on
        self._pending_cover_path: str | None = None
        self._cover_cleared = False
        self._setup_ui()
        self._load()

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"Set EPUB Metadata — {self._series_title}")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._volume_edit = QLineEdit()
        form.addRow("Volume Title:", self._volume_edit)
        self._author_edit = QLineEdit()
        form.addRow("Author:", self._author_edit)
        self._illustrator_edit = QLineEdit()
        form.addRow("Illustrator:", self._illustrator_edit)
        self._publisher_edit = QLineEdit()
        form.addRow("Publisher:", self._publisher_edit)
        self._identifier_edit = QLineEdit()
        form.addRow("ISBN:", self._identifier_edit)

        cover_row = QHBoxLayout()
        self._cover_label = QLabel("None")
        cover_row.addWidget(self._cover_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse_cover)
        cover_row.addWidget(browse_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._on_clear_cover)
        cover_row.addWidget(clear_btn)
        form.addRow("Cover:", cover_row)

        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load(self) -> None:
        meta = self._db.get_volume_metadata(self._series_title, self._volume_title)
        self._volume_edit.setText(meta["volume_title"])
        self._author_edit.setText(meta["volume_author"])
        self._illustrator_edit.setText(meta["volume_illustrator"])
        self._publisher_edit.setText(meta["volume_publisher"])
        self._identifier_edit.setText(meta["volume_identifier"])
        if meta["has_cover"]:
            self._cover_label.setText("(existing cover)")

    def _on_browse_cover(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Cover Image", "", _IMAGE_FILTER)
        if not path:
            return
        self._pending_cover_path = path
        self._cover_cleared = False
        self._cover_label.setText(Path(path).name)

    def _on_clear_cover(self) -> None:
        self._pending_cover_path = None
        self._cover_cleared = True
        self._cover_label.setText("None")

    def _on_save(self) -> None:
        new_title = self._volume_edit.text().strip()
        if new_title != self._volume_title:
            self._db.set_volume_title(self._series_title, self._volume_title, new_title)
            self._volume_title = new_title

        self._db.update_volume_metadata(
            self._series_title, self._volume_title,
            author=self._author_edit.text().strip(),
            illustrator=self._illustrator_edit.text().strip(),
            publisher=self._publisher_edit.text().strip(),
            identifier=self._identifier_edit.text().strip(),
        )

        if self._pending_cover_path is not None or self._cover_cleared:
            doc_ids = self._db.get_document_ids_by_volume(self._series_title, self._volume_title)
            if doc_ids:
                first_doc_id = doc_ids[0]
                if self._pending_cover_path is not None:
                    data = Path(self._pending_cover_path).read_bytes()
                    self._db.replace_document_cover(first_doc_id, self._pending_cover_path, data)
                else:
                    self._db.clear_document_cover(first_doc_id)

        self.accept()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_dlg_series_epub_metadata.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/dlg_series_epub_metadata.py tests/test_dlg_series_epub_metadata.py
git commit -m "feat(ui): add SeriesEpubMetadataDialog for scraped-series EPUB metadata"
```

---

### Task 3: Wire "Set EPUB Metadata…" into Series Manager

**Files:**
- Modify: `translation_assistant/ui/dlg_series.py`
- Test: Modify `tests/test_dialogs.py`

**Interfaces:**
- Consumes: `SeriesEpubMetadataDialog(db, series_title, parent=None)` from Task 2.
- Produces: `SeriesManagerDialog._set_epub_action` (QAction), `SeriesManagerDialog._on_set_epub_metadata()`.

- [ ] **Step 1: Write the failing test**

In `tests/test_dialogs.py`, modify `test_series_manager_has_context_menu_actions` (line 887) to also assert the new action exists:

```python
def test_series_manager_has_context_menu_actions(qapp, mem_db):
    from translation_assistant.ui.dlg_series import SeriesManagerDialog
    dlg = SeriesManagerDialog(mem_db)
    assert hasattr(dlg, "_set_url_action")
    assert hasattr(dlg, "_set_wp_action")
    assert hasattr(dlg, "_set_epub_action")
    assert hasattr(dlg, "_add_profile_action")
    assert hasattr(dlg, "_import_profile_action")
    assert hasattr(dlg, "_open_toc_action")
    dlg.reject()
```

Add a new test after it (after the existing open-toc tests, before the "Add Profile" section around line 924):

```python
def test_series_manager_set_epub_metadata_opens_dialog(qapp, mem_db):
    from translation_assistant.ui.dlg_series import SeriesManagerDialog
    from unittest.mock import MagicMock, patch
    mem_db.create_document("Ch 1", series_title="My Series", volume_title="")
    dlg = SeriesManagerDialog(mem_db)
    dlg._table.setCurrentCell(0, 0)
    mock_instance = MagicMock()
    with patch(
        "translation_assistant.ui.dlg_series.SeriesEpubMetadataDialog",
        return_value=mock_instance,
    ) as mock_cls:
        dlg._on_set_epub_metadata()
    mock_cls.assert_called_once_with(mem_db, "My Series", parent=dlg)
    mock_instance.exec.assert_called_once()
    dlg.reject()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_dialogs.py -k "series_manager_has_context_menu_actions or series_manager_set_epub_metadata" -v`
Expected: FAIL — `test_series_manager_has_context_menu_actions` fails on the new `_set_epub_action` assertion; `test_series_manager_set_epub_metadata_opens_dialog` fails with `AttributeError: 'SeriesManagerDialog' object has no attribute '_on_set_epub_metadata'`.

- [ ] **Step 3: Wire the action**

In `translation_assistant/ui/dlg_series.py`, add the import at the top (after the existing `from translation_assistant.db import Database` at line 16):

```python
from translation_assistant.ui.dlg_series_epub_metadata import SeriesEpubMetadataDialog
```

Add the action next to `_set_wp_action` (after line 56):

```python
        self._set_epub_action = QAction("Set EPUB Metadata…", self)
        self._set_epub_action.triggered.connect(self._on_set_epub_metadata)
```

Add it to the context menu, next to `_set_wp_action` (after line 121, `menu.addAction(self._set_wp_action)`):

```python
        menu.addAction(self._set_epub_action)
```

Add the handler method, next to `_on_set_wp_fields` (after it ends, before `_on_add_profile` at line 259):

```python
    def _on_set_epub_metadata(self) -> None:
        s = self._current_series()
        if s is None:
            return
        dlg = SeriesEpubMetadataDialog(self._db, s["title"], parent=self)
        dlg.exec()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_dialogs.py -k "series_manager" -v`
Expected: all PASS.

- [ ] **Step 5: Run the full test suite**

Run: `source .venv/bin/activate && pytest -q`
Expected: all PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/dlg_series.py tests/test_dialogs.py
git commit -m "feat(ui): wire Set EPUB Metadata… action into Series Manager"
```

---

## Self-Review Notes

- **Spec coverage:** DB methods (Task 1), dialog with all fields + cover picker (Task 2), Series Manager wiring (Task 3) — all three spec sections covered. Single-volume scope respected throughout (dialog hardcodes `volume_title=""` as the bucket it reads/writes).
- **Type consistency:** `get_volume_metadata` return dict keys (`volume_title`, `volume_author`, `volume_illustrator`, `volume_publisher`, `volume_identifier`, `has_cover`) match what `SeriesEpubMetadataDialog._load` reads in Task 2. `SeriesEpubMetadataDialog.__init__(db, series_title, parent=None)` signature matches both its own tests and the `dlg_series.py` call site in Task 3.
- **No placeholders:** every step has runnable code, no TBDs.

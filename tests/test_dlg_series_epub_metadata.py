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

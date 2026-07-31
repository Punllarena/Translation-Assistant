"""
Tests for ImportEpubDialog.
All tests bypass exec() — call internal methods directly and inspect state.
Synthetic EPUB fixtures only (EPUB/ sample files are gitignored, manual-test only).
"""
import sqlite3
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from translation_assistant.db import Database
from translation_assistant.ui.dlg_import_epub import ImportEpubDialog

from .test_epub import _CONTAINER_XML, _OPF_EPUB3, _NAV_XHTML, _OPF_EPUB3_COVER, _OPF_EPUB3_METADATA


@pytest.fixture
def mem_db(qapp):
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return db


def _make_epub(tmp_path: Path, *, ch1="<p>" + "A" * 600 + "。</p>", ch2="<p>Short.</p>") -> Path:
    """ch1 defaults to >=500 chars (default-checked); ch2 defaults short (unchecked)."""
    path = tmp_path / "vol.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _OPF_EPUB3)
        zf.writestr("OEBPS/nav.xhtml", _NAV_XHTML)
        zf.writestr("OEBPS/text/ch1.xhtml", f"<html><body>{ch1}</body></html>")
        zf.writestr("OEBPS/text/ch2.xhtml", f"<html><body>{ch2}</body></html>")
    return path


class TestImportEpubDialog:
    def test_instantiates(self, qapp, mem_db):
        dlg = ImportEpubDialog(mem_db)
        assert dlg is not None

    def test_browse_populates_series_and_volume_fields(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        assert dlg._series_edit.text() == "Test Volume"
        assert dlg._volume_edit.text() == "Test Volume"

    def test_long_chapter_default_checked(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        assert dlg._chapter_list.item(0).checkState() == Qt.CheckState.Checked

    def test_short_chapter_default_unchecked(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        assert dlg._chapter_list.item(1).checkState() == Qt.CheckState.Unchecked

    def test_import_creates_documents_with_volume_title(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        dlg._series_edit.setText("My Series")
        dlg._volume_edit.setText("Volume 1")
        dlg._chapter_list.item(1).setCheckState(Qt.CheckState.Checked)  # include the short one too
        dlg._on_import()
        titles = mem_db.get_volume_chapter_titles("My Series", "Volume 1")
        assert titles == {"Chapter 1", "Chapter 2"}

    def test_import_series_order_increments_from_next(self, qapp, mem_db, tmp_path, monkeypatch):
        mem_db.create_document("existing", series_title="My Series", series_order=5)
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        dlg._series_edit.setText("My Series")
        dlg._volume_edit.setText("Volume 1")
        dlg._on_import()
        doc_ids = mem_db.get_document_ids_by_series("My Series")
        orders = [mem_db.get_document(d)["series_order"] for d in doc_ids]
        assert orders == [5, 6]  # existing doc keeps 5; new chapter (ch1 only — ch2 unchecked) gets 6

    def test_reimport_skips_already_imported_chapter(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg1 = ImportEpubDialog(mem_db)
        dlg1._on_browse()
        dlg1._series_edit.setText("My Series")
        dlg1._volume_edit.setText("Volume 1")
        dlg1._on_import()

        dlg2 = ImportEpubDialog(mem_db)
        dlg2._on_browse()
        dlg2._series_edit.setText("My Series")
        dlg2._volume_edit.setText("Volume 1")
        dlg2._chapter_list.item(1).setCheckState(Qt.CheckState.Checked)
        dlg2._on_import()

        doc_ids = mem_db.get_document_ids_by_series("My Series")
        assert len(doc_ids) == 2  # Chapter 1 not duplicated; Chapter 2 added once

    def test_source_url_not_set_to_chapter_href(self, qapp, mem_db, tmp_path, monkeypatch):
        """A zip-internal href is not fetchable — it must not enable Re-fetch."""
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        dlg._series_edit.setText("My Series")
        dlg._volume_edit.setText("Volume 1")
        dlg._on_import()
        doc_id = mem_db.get_document_ids_by_series("My Series")[0]
        assert mem_db.get_document(doc_id)["source_url"] == ""


class TestImportEpubBlankTitles:
    def _browsed_dialog(self, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        return dlg

    def _run(self, dlg, series, volume, monkeypatch):
        warned = []
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QMessageBox.warning",
            lambda *a, **kw: warned.append(a),
        )
        dlg._series_edit.setText(series)
        dlg._volume_edit.setText(volume)
        dlg._on_import()
        return warned

    def test_blank_series_title_warns_and_imports_nothing(self, qapp, mem_db, tmp_path, monkeypatch):
        dlg = self._browsed_dialog(mem_db, tmp_path, monkeypatch)
        warned = self._run(dlg, "", "Volume 1", monkeypatch)
        assert warned
        assert mem_db.list_documents() == []

    def test_blank_volume_title_warns_and_imports_nothing(self, qapp, mem_db, tmp_path, monkeypatch):
        dlg = self._browsed_dialog(mem_db, tmp_path, monkeypatch)
        warned = self._run(dlg, "My Series", "", monkeypatch)
        assert warned
        assert mem_db.list_documents() == []

    def test_whitespace_only_title_treated_as_blank(self, qapp, mem_db, tmp_path, monkeypatch):
        dlg = self._browsed_dialog(mem_db, tmp_path, monkeypatch)
        warned = self._run(dlg, "   ", "Volume 1", monkeypatch)
        assert warned
        assert mem_db.list_documents() == []


def _make_epub_with_illustration(tmp_path: Path) -> Path:
    path = tmp_path / "illust_vol.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _OPF_EPUB3_COVER)
        zf.writestr("OEBPS/nav.xhtml", _NAV_XHTML.replace(
            '<li><a href="text/ch2.xhtml">Chapter 2</a></li>', ""
        ))
        zf.writestr("OEBPS/images/cover.jpg", b"fake-cover-bytes")
        body = '<p>' + "A" * 600 + '。</p><p><img class="fit" src="../images/inline.png"/></p>'
        zf.writestr("OEBPS/text/ch1.xhtml", f"<html><body>{body}</body></html>")
        zf.writestr("OEBPS/images/inline.png", b"fake-inline-bytes")
    return path


class TestImportEpubImages:
    def test_import_attaches_inline_image(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub_with_illustration(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        dlg._series_edit.setText("S")
        dlg._volume_edit.setText("V1")
        dlg._on_import()
        doc_id = mem_db.get_document_ids_by_series("S")[0]
        images = mem_db.get_document_images(doc_id)
        inline = [im for im in images if not im["is_cover"]]
        assert len(inline) == 1
        assert inline[0]["data"] == b"fake-inline-bytes"

    def test_import_attaches_cover_to_first_document(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub_with_illustration(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        dlg._series_edit.setText("S")
        dlg._volume_edit.setText("V1")
        dlg._on_import()
        doc_id = mem_db.get_document_ids_by_series("S")[0]
        images = mem_db.get_document_images(doc_id)
        cover = [im for im in images if im["is_cover"]]
        assert len(cover) == 1
        assert cover[0]["data"] == b"fake-cover-bytes"

    def test_reimport_does_not_duplicate_cover(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub_with_illustration(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg1 = ImportEpubDialog(mem_db)
        dlg1._on_browse()
        dlg1._series_edit.setText("S")
        dlg1._volume_edit.setText("V1")
        dlg1._on_import()

        # Second batch against the same volume (e.g. re-running import to
        # pick up a chapter left unchecked the first time).
        dlg2 = ImportEpubDialog(mem_db)
        dlg2._on_browse()
        dlg2._series_edit.setText("S")
        dlg2._volume_edit.setText("V1")
        dlg2._on_import()  # Chapter 1 already imported -> skipped; nothing new to attach a cover to

        assert mem_db.volume_has_cover("S", "V1") is True
        all_covers = [
            im for doc_id in mem_db.get_document_ids_by_series("S")
            for im in mem_db.get_document_images(doc_id) if im["is_cover"]
        ]
        assert len(all_covers) == 1


class TestImportEpubMetadataFields:
    def test_fields_prefilled_from_opf(self, qapp, mem_db, tmp_path, monkeypatch):
        path = tmp_path / "meta_vol.epub"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("META-INF/container.xml", _CONTAINER_XML)
            zf.writestr("OEBPS/content.opf", _OPF_EPUB3_METADATA)
            zf.writestr("OEBPS/nav.xhtml", _NAV_XHTML.replace(
                '<li><a href="text/ch2.xhtml">Chapter 2</a></li>', ""
            ))
            zf.writestr("OEBPS/text/ch1.xhtml", "<html><body><p>Hello.</p></body></html>")
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        assert dlg._author_edit.text() == "Author Name"
        assert dlg._illustrator_edit.text() == "Illustrator Name"
        assert dlg._publisher_edit.text() == "Test Publisher"
        assert dlg._identifier_edit.text() == "urn:isbn:1234567890123"

    def test_fields_editable_and_applied_to_created_documents(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        dlg._series_edit.setText("S")
        dlg._volume_edit.setText("V1")
        dlg._author_edit.setText("Custom Author")
        dlg._illustrator_edit.setText("Custom Illustrator")
        dlg._publisher_edit.setText("Custom Publisher")
        dlg._identifier_edit.setText("urn:isbn:0000000000000")
        dlg._on_import()
        doc_id = mem_db.get_document_ids_by_series("S")[0]
        meta = mem_db.get_document(doc_id)
        assert meta["volume_author"] == "Custom Author"
        assert meta["volume_illustrator"] == "Custom Illustrator"
        assert meta["volume_publisher"] == "Custom Publisher"
        assert meta["volume_identifier"] == "urn:isbn:0000000000000"

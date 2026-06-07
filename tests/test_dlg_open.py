"""
Tests for OpenDocumentDialog (dlg_open.py) — Stage E.
"""
import sqlite3
import pytest

from translation_assistant.db import Database
from translation_assistant.ui.dlg_open import OpenDocumentDialog


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    return Database(":memory:", _conn=conn)


class TestOpenDocumentDialog:
    def test_instantiates_with_empty_db(self, qapp, mem_db):
        dlg = OpenDocumentDialog(mem_db)
        assert dlg is not None

    def test_shows_no_rows_when_db_empty(self, qapp, mem_db):
        dlg = OpenDocumentDialog(mem_db)
        assert dlg._table.rowCount() == 0

    def test_shows_documents_in_table(self, qapp, mem_db):
        mem_db.create_document("My Story")
        mem_db.create_document("Another Doc")
        dlg = OpenDocumentDialog(mem_db)
        titles = [dlg._table.item(r, 0).text() for r in range(dlg._table.rowCount())]
        assert "My Story" in titles
        assert "Another Doc" in titles

    def test_selected_doc_id_none_initially(self, qapp, mem_db):
        mem_db.create_document("Doc")
        dlg = OpenDocumentDialog(mem_db)
        assert dlg.selected_doc_id is None

    def test_open_btn_disabled_with_no_selection(self, qapp, mem_db):
        mem_db.create_document("Doc")
        dlg = OpenDocumentDialog(mem_db)
        assert not dlg._open_btn.isEnabled()

    def test_open_btn_enabled_on_row_select(self, qapp, mem_db):
        mem_db.create_document("Doc")
        dlg = OpenDocumentDialog(mem_db)
        dlg._table.selectRow(0)
        assert dlg._open_btn.isEnabled()

    def test_selected_doc_id_set_on_accept(self, qapp, mem_db):
        doc_id = mem_db.create_document("My Story")
        dlg = OpenDocumentDialog(mem_db)
        dlg._table.selectRow(0)
        dlg._on_open()
        assert dlg.selected_doc_id == doc_id

    def test_delete_removes_document_from_db(self, qapp, mem_db):
        mem_db.create_document("To Delete")
        dlg = OpenDocumentDialog(mem_db)
        dlg._table.selectRow(0)
        dlg._on_delete()
        assert mem_db.list_documents() == []

    def test_delete_removes_row_from_table(self, qapp, mem_db):
        mem_db.create_document("To Delete")
        dlg = OpenDocumentDialog(mem_db)
        dlg._table.selectRow(0)
        dlg._on_delete()
        assert dlg._table.rowCount() == 0

    def test_double_click_accepts_dialog(self, qapp, mem_db):
        doc_id = mem_db.create_document("Quick Open")
        dlg = OpenDocumentDialog(mem_db)
        # Simulate double-click by calling the handler directly
        dlg._on_row_double_clicked(0, 0)
        assert dlg.selected_doc_id == doc_id

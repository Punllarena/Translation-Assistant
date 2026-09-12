import sqlite3

from translation_assistant.db import Database
from translation_assistant.ui.dlg_find_replace import FindReplaceDialog


def _db_with_series() -> Database:
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    doc1 = db.create_document("Alpha Ch1", series_title="Alpha", chapter_title="Ch1")
    db.save_lines(doc1, [
        {"line_number": 0, "prefix": "%", "raw_text": "r0", "translated_text": "The Cat meowed"},
        {"line_number": 1, "prefix": "%", "raw_text": "r1", "translated_text": "Nothing here"},
    ])
    doc2 = db.create_document("Alpha Ch2", series_title="Alpha", chapter_title="Ch2")
    db.save_lines(doc2, [
        {"line_number": 0, "prefix": "%", "raw_text": "r0", "translated_text": "The cat ran"},
    ])
    return db


def test_search_populates_table(qapp):
    db = _db_with_series()
    dlg = FindReplaceDialog(db, "Alpha")
    dlg._find_edit.setText("cat")
    dlg._on_search()
    assert dlg._table.rowCount() == 2


def test_replace_selected_writes_to_db(qapp):
    db = _db_with_series()
    dlg = FindReplaceDialog(db, "Alpha")
    dlg._find_edit.setText("cat")
    dlg._replace_edit.setText("dog")
    dlg._on_search()
    dlg._table.selectRow(0)
    dlg._on_replace_selected()
    lines = db.get_lines(db.get_document_ids_by_series("Alpha")[0])
    assert lines[0]["translated_text"] == "The dog meowed"
    assert dlg._table.rowCount() == 1


def test_replace_all_updates_every_match(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    db = _db_with_series()
    dlg = FindReplaceDialog(db, "Alpha")
    dlg._find_edit.setText("cat")
    dlg._replace_edit.setText("dog")
    dlg._on_search()
    dlg._on_replace_all()
    doc_ids = db.get_document_ids_by_series("Alpha")
    texts = [ln["translated_text"] for doc_id in doc_ids for ln in db.get_lines(doc_id)]
    assert "The dog meowed" in texts
    assert "The dog ran" in texts
    assert dlg._table.rowCount() == 0


def test_on_replaced_callback_invoked(qapp):
    db = _db_with_series()
    seen = []
    dlg = FindReplaceDialog(db, "Alpha", on_replaced=seen.append)
    dlg._find_edit.setText("cat")
    dlg._on_search()
    dlg._table.selectRow(0)
    dlg._on_replace_selected()
    assert len(seen) == 1


def test_case_sensitive_excludes_different_case(qapp):
    db = _db_with_series()
    dlg = FindReplaceDialog(db, "Alpha")
    dlg._find_edit.setText("Cat")
    dlg._case_check.setChecked(True)
    dlg._on_search()
    assert dlg._table.rowCount() == 1

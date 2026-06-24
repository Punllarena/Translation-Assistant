"""
Tests for OpenDocumentDialog (dlg_open.py) — Stage J.

The dialog now uses a QTreeWidget grouped by series. Ungrouped documents
appear under a "(No Series)" group. Each leaf item represents a document;
series group items are headers and cannot be opened.
"""
import sqlite3
import pytest

from translation_assistant.db import Database
from translation_assistant.ui.dlg_open import OpenDocumentDialog


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    return Database(":memory:", _conn=conn)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _root(dlg: OpenDocumentDialog):
    return dlg._tree.invisibleRootItem()

def _group_names(dlg: OpenDocumentDialog) -> list[str]:
    r = _root(dlg)
    return [r.child(i).text(0) for i in range(r.childCount())]

def _all_leaf_titles(dlg: OpenDocumentDialog) -> list[str]:
    r = _root(dlg)
    titles = []
    for i in range(r.childCount()):
        group = r.child(i)
        for j in range(group.childCount()):
            titles.append(group.child(j).text(0))
    return titles

def _first_leaf(dlg: OpenDocumentDialog):
    r = _root(dlg)
    for i in range(r.childCount()):
        group = r.child(i)
        if group.childCount():
            return group.child(0)
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOpenDocumentDialog:
    def test_instantiates_with_empty_db(self, qapp, mem_db):
        dlg = OpenDocumentDialog(mem_db)
        assert dlg is not None

    def test_shows_no_groups_when_db_empty(self, qapp, mem_db):
        dlg = OpenDocumentDialog(mem_db)
        assert _root(dlg).childCount() == 0

    def test_ungrouped_doc_appears_under_no_series(self, qapp, mem_db):
        mem_db.create_document("My Story")
        dlg = OpenDocumentDialog(mem_db)
        assert any(n.startswith("(No Series)") for n in _group_names(dlg))
        assert "My Story" in _all_leaf_titles(dlg)

    def test_grouped_doc_appears_under_series(self, qapp, mem_db):
        mem_db.create_document("Ch1", series_title="My Novel", series_order=1, chapter_title="Chapter 1")
        dlg = OpenDocumentDialog(mem_db)
        assert any(n.startswith("My Novel") for n in _group_names(dlg))
        assert "Chapter 1" in _all_leaf_titles(dlg)

    def test_documents_grouped_correctly(self, qapp, mem_db):
        mem_db.create_document("C1", series_title="Novel", series_order=1, chapter_title="Ch 1")
        mem_db.create_document("C2", series_title="Novel", series_order=2, chapter_title="Ch 2")
        mem_db.create_document("Standalone")
        dlg = OpenDocumentDialog(mem_db)
        groups = _group_names(dlg)
        assert any(n.startswith("Novel") for n in groups)
        assert any(n.startswith("(No Series)") for n in groups)
        # Novel group has 2 children
        r = _root(dlg)
        novel_group = next(r.child(i) for i in range(r.childCount()) if r.child(i).text(0).startswith("Novel"))
        assert novel_group.childCount() == 2

    def test_progress_shown_for_document(self, qapp, mem_db):
        doc_id = mem_db.create_document("Story")
        mem_db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Translated"},
            {"line_number": 1, "prefix": "%", "raw_text": "B", "translated_text": ""},
        ])
        dlg = OpenDocumentDialog(mem_db)
        leaf = _first_leaf(dlg)
        assert leaf is not None
        assert "50%" in leaf.text(1)

    def test_series_header_not_selectable(self, qapp, mem_db):
        from PySide6.QtCore import Qt
        mem_db.create_document("Doc", series_title="Series A", chapter_title="Ch")
        dlg = OpenDocumentDialog(mem_db)
        r = _root(dlg)
        group = r.child(0)
        flags = group.flags()
        assert not (flags & Qt.ItemFlag.ItemIsSelectable)

    def test_selected_doc_id_none_initially(self, qapp, mem_db):
        mem_db.create_document("Doc")
        dlg = OpenDocumentDialog(mem_db)
        assert dlg.selected_doc_id is None

    def test_open_btn_disabled_with_no_selection(self, qapp, mem_db):
        mem_db.create_document("Doc")
        dlg = OpenDocumentDialog(mem_db)
        assert not dlg._open_btn.isEnabled()

    def test_open_btn_enabled_on_leaf_select(self, qapp, mem_db):
        mem_db.create_document("Doc")
        dlg = OpenDocumentDialog(mem_db)
        leaf = _first_leaf(dlg)
        dlg._tree.setCurrentItem(leaf)
        assert dlg._open_btn.isEnabled()

    def test_selected_doc_id_set_on_open(self, qapp, mem_db):
        doc_id = mem_db.create_document("My Story")
        dlg = OpenDocumentDialog(mem_db)
        leaf = _first_leaf(dlg)
        dlg._tree.setCurrentItem(leaf)
        dlg._on_open()
        assert dlg.selected_doc_id == doc_id

    def test_delete_requires_confirmation(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        mem_db.create_document("To Delete")
        dlg = OpenDocumentDialog(mem_db)
        dlg._tree.setCurrentItem(_first_leaf(dlg))
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No) as mock_q:
            dlg._on_delete()
            assert mock_q.called
        assert len(mem_db.list_documents()) == 1  # not deleted

    def test_delete_confirmed_removes_document(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        mem_db.create_document("To Delete")
        dlg = OpenDocumentDialog(mem_db)
        dlg._tree.setCurrentItem(_first_leaf(dlg))
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            dlg._on_delete()
        assert mem_db.list_documents() == []

    def test_delete_removes_document_from_db(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        mem_db.create_document("To Delete")
        dlg = OpenDocumentDialog(mem_db)
        leaf = _first_leaf(dlg)
        dlg._tree.setCurrentItem(leaf)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            dlg._on_delete()
        assert mem_db.list_documents() == []

    def test_delete_removes_leaf_from_tree(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        mem_db.create_document("To Delete")
        dlg = OpenDocumentDialog(mem_db)
        leaf = _first_leaf(dlg)
        dlg._tree.setCurrentItem(leaf)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            dlg._on_delete()
        assert _first_leaf(dlg) is None

    def test_delete_removes_empty_group(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        mem_db.create_document("Only Doc")
        dlg = OpenDocumentDialog(mem_db)
        leaf = _first_leaf(dlg)
        dlg._tree.setCurrentItem(leaf)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            dlg._on_delete()
        assert _root(dlg).childCount() == 0

    def test_double_click_opens_doc(self, qapp, mem_db):
        doc_id = mem_db.create_document("Quick Open")
        dlg = OpenDocumentDialog(mem_db)
        leaf = _first_leaf(dlg)
        dlg._on_item_double_clicked(leaf, 0)
        assert dlg.selected_doc_id == doc_id

    def test_filter_hides_non_matching_leaves(self, qapp, mem_db):
        mem_db.create_document("Alpha", chapter_title="Alpha")
        mem_db.create_document("Beta", chapter_title="Beta")
        dlg = OpenDocumentDialog(mem_db)
        dlg._filter_edit.setText("Alpha")
        visible = [t for t in _all_leaf_titles(dlg)
                   if not _first_leaf_is_hidden(dlg, t)]
        assert "Alpha" in visible
        assert "Beta" not in visible

    def test_filter_shows_all_on_clear(self, qapp, mem_db):
        mem_db.create_document("Alpha", chapter_title="Alpha")
        mem_db.create_document("Beta", chapter_title="Beta")
        dlg = OpenDocumentDialog(mem_db)
        dlg._filter_edit.setText("Alpha")
        dlg._filter_edit.setText("")
        visible = [t for t in _all_leaf_titles(dlg)
                   if not _first_leaf_is_hidden(dlg, t)]
        assert "Alpha" in visible
        assert "Beta" in visible

    def test_last_edited_column_exists(self, qapp, mem_db):
        mem_db.create_document("Doc")
        dlg = OpenDocumentDialog(mem_db)
        assert dlg._tree.columnCount() >= 3
        leaf = _first_leaf(dlg)
        assert leaf.text(2) != ""  # last-edited not blank

    def test_edit_btn_disabled_initially(self, qapp, mem_db):
        mem_db.create_document("Doc")
        dlg = OpenDocumentDialog(mem_db)
        assert not dlg._edit_btn.isEnabled()

    def test_edit_btn_enabled_on_leaf_select(self, qapp, mem_db):
        mem_db.create_document("Doc")
        dlg = OpenDocumentDialog(mem_db)
        dlg._tree.setCurrentItem(_first_leaf(dlg))
        assert dlg._edit_btn.isEnabled()

    def test_do_edit_updates_db_metadata(self, qapp, mem_db):
        doc_id = mem_db.create_document("Old")
        dlg = OpenDocumentDialog(mem_db)
        dlg._do_edit(doc_id, "Series A", 2, "New Chapter")
        doc = mem_db.get_document(doc_id)
        assert doc["series_title"] == "Series A"
        assert doc["series_order"] == 2
        assert doc["chapter_title"] == "New Chapter"

    def test_do_edit_refreshes_tree(self, qapp, mem_db):
        doc_id = mem_db.create_document("Old", chapter_title="Old Chapter")
        dlg = OpenDocumentDialog(mem_db)
        dlg._do_edit(doc_id, "", 0, "New Chapter")
        assert "New Chapter" in _all_leaf_titles(dlg)
        assert "Old Chapter" not in _all_leaf_titles(dlg)

    def test_current_doc_preselected(self, qapp, mem_db):
        doc_id = mem_db.create_document("My Doc")
        dlg = OpenDocumentDialog(mem_db, current_doc_id=doc_id)
        current = dlg._tree.currentItem()
        assert current is not None
        assert current.childCount() == 0  # it's a leaf
        assert current.text(0) == "My Doc"

    def test_no_crash_when_current_doc_not_in_db(self, qapp, mem_db):
        mem_db.create_document("My Doc")
        dlg = OpenDocumentDialog(mem_db, current_doc_id=9999)
        # Should not raise; just no pre-selection
        assert dlg is not None

    def test_refetch_btn_exists(self, qapp, mem_db):
        dlg = OpenDocumentDialog(mem_db)
        assert hasattr(dlg, "_refetch_btn")

    def test_refetch_btn_disabled_with_no_selection(self, qapp, mem_db):
        mem_db.create_document("Doc", source_url="https://ncode.syosetu.com/n1234ab/1/")
        dlg = OpenDocumentDialog(mem_db)
        assert not dlg._refetch_btn.isEnabled()

    def test_refetch_btn_disabled_when_doc_has_no_url(self, qapp, mem_db):
        mem_db.create_document("Doc")  # no source_url
        dlg = OpenDocumentDialog(mem_db)
        leaf = _first_leaf(dlg)
        dlg._tree.setCurrentItem(leaf)
        assert not dlg._refetch_btn.isEnabled()

    def test_refetch_btn_enabled_when_doc_has_url_and_selected(self, qapp, mem_db):
        mem_db.create_document("Doc", source_url="https://ncode.syosetu.com/n1234ab/1/")
        dlg = OpenDocumentDialog(mem_db)
        leaf = _first_leaf(dlg)
        dlg._tree.setCurrentItem(leaf)
        assert dlg._refetch_btn.isEnabled()

    def test_on_refetch_done_replaces_raw_content_in_db(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        doc_id = mem_db.create_document(
            "Ch1", source_url="https://ncode.syosetu.com/n1234ab/1/"
        )
        mem_db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Old line", "translated_text": "Trans"},
        ])

        dlg = OpenDocumentDialog(mem_db)
        with patch.object(QMessageBox, "information"):
            dlg._on_refetch_done(doc_id, "New Title", "New body text.")

        lines = mem_db.get_lines(doc_id)
        # First line should be the new title
        assert lines[0]["raw_text"] == "New Title"

    def test_on_refetch_done_preserves_translations(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        doc_id = mem_db.create_document(
            "Ch1", source_url="https://ncode.syosetu.com/n1234ab/1/"
        )
        mem_db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Old Title", "translated_text": "MyTrans"},
        ])

        dlg = OpenDocumentDialog(mem_db)
        with patch.object(QMessageBox, "information"):
            dlg._on_refetch_done(doc_id, "Old Title", "Same body.")

        lines = mem_db.get_lines(doc_id)
        assert lines[0]["translated_text"] == "MyTrans"

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


def _first_leaf_is_hidden(dlg, title: str) -> bool:
    r = _root(dlg)
    for i in range(r.childCount()):
        group = r.child(i)
        for j in range(group.childCount()):
            child = group.child(j)
            if child.text(0) == title:
                return child.isHidden()
    return True

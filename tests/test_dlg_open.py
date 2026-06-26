"""
Tests for OpenDocumentDialog (dlg_open.py) — two-panel redesign.

The dialog now uses a QListWidget (left) for series selection and a flat
QTreeWidget (right) for chapters. Series group headers are gone; each top-level
tree item is a chapter.
"""
import sqlite3
import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog
from translation_assistant.db import Database
from translation_assistant.ui.dlg_open import OpenDocumentDialog


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    return Database(":memory:", _conn=conn)


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOpenDocumentDialog:
    def test_instantiates_with_empty_db(self, qapp, mem_db):
        dlg = OpenDocumentDialog(mem_db)
        assert dlg is not None

    def test_shows_no_groups_when_db_empty(self, qapp, mem_db):
        dlg = OpenDocumentDialog(mem_db)
        assert dlg._series_list.count() == 0
        assert dlg._tree.topLevelItemCount() == 0

    def test_ungrouped_doc_appears_under_no_series(self, qapp, mem_db):
        mem_db.create_document("My Story")
        dlg = OpenDocumentDialog(mem_db)
        assert any(n.startswith("(No Series)") for n in _series_names(dlg))
        _select_series(dlg, "(No Series)")
        assert "My Story" in _chapter_titles(dlg)

    def test_grouped_doc_appears_under_series(self, qapp, mem_db):
        mem_db.create_document("Ch1", series_title="My Novel", series_order=1, chapter_title="Chapter 1")
        dlg = OpenDocumentDialog(mem_db)
        assert any(n.startswith("My Novel") for n in _series_names(dlg))
        _select_series(dlg, "My Novel")
        assert "Chapter 1" in _chapter_titles(dlg)

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
        assert dlg._tree.topLevelItemCount() == 0

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
        assert not _chapter_is_hidden(dlg, "Alpha")
        assert _chapter_is_hidden(dlg, "Beta")

    def test_filter_shows_all_on_clear(self, qapp, mem_db):
        mem_db.create_document("Alpha", chapter_title="Alpha")
        mem_db.create_document("Beta", chapter_title="Beta")
        dlg = OpenDocumentDialog(mem_db)
        dlg._filter_edit.setText("Alpha")
        dlg._filter_edit.setText("")
        assert not _chapter_is_hidden(dlg, "Alpha")
        assert not _chapter_is_hidden(dlg, "Beta")

    def test_last_edited_column_exists(self, qapp, mem_db):
        mem_db.create_document("Doc")
        dlg = OpenDocumentDialog(mem_db)
        assert dlg._tree.columnCount() == 4
        leaf = _first_chapter(dlg)
        assert leaf is not None
        assert leaf.text(3) != ""

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
        assert "New Chapter" in _chapter_titles(dlg)
        assert "Old Chapter" not in _chapter_titles(dlg)

    def test_current_doc_preselected(self, qapp, mem_db):
        doc_id = mem_db.create_document("My Doc")
        dlg = OpenDocumentDialog(mem_db, current_doc_id=doc_id)
        current = dlg._tree.currentItem()
        assert current is not None
        assert current.text(1) == "My Doc"

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

    def test_series_header_shows_doc_count(self, qapp, mem_db):
        mem_db.create_document("C1", series_title="Novel", series_order=1, chapter_title="Ch 1")
        mem_db.create_document("C2", series_title="Novel", series_order=2, chapter_title="Ch 2")
        dlg = OpenDocumentDialog(mem_db)
        novel_entry = next(n for n in _series_names(dlg) if n.startswith("Novel"))
        assert "(2)" in novel_entry

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

    def test_sort_title_alpha(self, qapp, mem_db):
        mem_db.create_document("Zebra", chapter_title="Zebra")
        mem_db.create_document("Apple", chapter_title="Apple")
        dlg = OpenDocumentDialog(mem_db)
        dlg._sort_chapters(1)  # Title A→Z
        titles = _chapter_titles(dlg)
        assert titles.index("Apple") < titles.index("Zebra")

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

    # ------------------------------------------------------------------
    # New structural tests
    # ------------------------------------------------------------------

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

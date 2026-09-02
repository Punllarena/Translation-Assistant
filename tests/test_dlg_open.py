"""
Tests for OpenDocumentDialog (dlg_open.py) — two-panel redesign.

The dialog now uses a QListWidget (left) for series selection and a flat
QTreeWidget (right) for chapters. Series group headers are gone; each top-level
tree item is a chapter.
"""
import sqlite3
import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMenu
from translation_assistant.db import Database
from translation_assistant.ui.dlg_open import OpenDocumentDialog, _EditVolumeMetadataDialog


class _NoExecMenu(QMenu):
    """QMenu whose exec() never opens a real (blocking) menu."""

    def exec(self, *args, **kwargs):
        return None


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
        assert dlg._tree.columnCount() == 8
        leaf = _first_chapter(dlg)
        assert leaf is not None
        assert leaf.text(5) != ""

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

    def test_chapter_tree_has_five_columns(self, qapp, mem_db):
        dlg = OpenDocumentDialog(mem_db)
        assert dlg._tree.columnCount() == 8
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
        from unittest.mock import patch
        from PySide6.QtCore import QPoint
        mem_db.create_document("Doc")
        dlg = OpenDocumentDialog(mem_db)
        # patch.object(QMenu, "exec") does not work: shiboken resolves builtin
        # methods on the C++ wrapper, bypassing the patched class attribute,
        # so a real blocking menu would open. Swap the class in the module.
        with patch("translation_assistant.ui.dlg_open.QMenu", _NoExecMenu):
            dlg._on_chapter_context_menu(QPoint(0, 0))

    def test_series_context_menu_no_crash_for_named_series(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtCore import QPoint
        mem_db.create_document("Ch", series_title="Novel", chapter_title="Ch")
        dlg = OpenDocumentDialog(mem_db)
        dlg._series_list.setCurrentRow(0)
        with patch("translation_assistant.ui.dlg_open.QMenu", _NoExecMenu):
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

    def test_filter_clears_when_switching_series(self, qapp, mem_db):
        mem_db.create_document("Ch1", series_title="A", chapter_title="Alpha")
        mem_db.create_document("Ch2", series_title="B", chapter_title="Beta")
        dlg = OpenDocumentDialog(mem_db)
        _select_series(dlg, "A")
        dlg._filter_edit.setText("Alpha")
        assert dlg._filter_edit.text() == "Alpha"
        _select_series(dlg, "B")
        assert dlg._filter_edit.text() == ""

    def test_sort_resets_when_switching_series(self, qapp, mem_db):
        mem_db.create_document("C1", series_title="A", series_order=1, chapter_title="C1")
        mem_db.create_document("C2", series_title="B", series_order=1, chapter_title="C2")
        dlg = OpenDocumentDialog(mem_db)
        _select_series(dlg, "A")
        dlg._sort_chapters(5)  # sort by Last Edited
        assert dlg._sort_col == 5
        _select_series(dlg, "B")
        assert dlg._sort_col == 0  # reset to default
        assert dlg._sort_asc is True
        assert "▲" in dlg._tree.headerItem().text(0)  # column 0 has arrow
        assert "▲" not in dlg._tree.headerItem().text(5)  # Last Edited has no arrow


class TestEditVolumeMetadata:
    def test_edit_volume_btn_enabled_for_non_volume_document(self, qapp, mem_db):
        # Enabled even with no volume yet, so the chapter can be assigned one.
        mem_db.create_document("Doc")  # no volume_title -- plain/legacy document
        dlg = OpenDocumentDialog(mem_db)
        dlg._tree.setCurrentItem(_first_leaf(dlg))
        assert dlg._edit_volume_btn.isEnabled()

    def test_do_edit_volume_assigns_lone_chapter_without_sweeping_series(self, qapp, mem_db):
        a = mem_db.create_document("Ch A", series_title="S", chapter_title="Ch A")
        b = mem_db.create_document("Ch B", series_title="S", chapter_title="Ch B")
        dlg = OpenDocumentDialog(mem_db)
        dlg._do_edit_volume(
            a, "S", "",
            new_volume_title="Vol 1",
            volume_author="Auth", volume_illustrator="", volume_publisher="", volume_identifier="",
        )
        assert mem_db.get_document(a)["volume_title"] == "Vol 1"
        assert mem_db.get_document(b)["volume_title"] == ""  # untouched

    def test_do_edit_volume_lone_chapter_joins_existing_volume_metadata(self, qapp, mem_db):
        mem_db.create_document(
            "Ch 1", series_title="S", volume_title="Vol 1", chapter_title="Ch 1",
            volume_author="Real Author", volume_identifier="urn:isbn:9",
        )
        new = mem_db.create_document("Ch 2", series_title="S", chapter_title="Ch 2")
        dlg = OpenDocumentDialog(mem_db)
        dlg._do_edit_volume(
            new, "S", "",
            new_volume_title="Vol 1",
            volume_author="", volume_illustrator="", volume_publisher="", volume_identifier="",
        )
        meta = mem_db.get_document(new)
        assert meta["volume_title"] == "Vol 1"
        assert meta["volume_author"] == "Real Author"
        assert meta["volume_identifier"] == "urn:isbn:9"

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

    def test_do_edit_volume_detects_collision_and_prompts(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        doc_a = mem_db.create_document("Ch 1", series_title="S", volume_title="A", chapter_title="Ch 1")
        mem_db.create_document("Ch 2", series_title="S", volume_title="B", chapter_title="Ch 2")
        mem_db.create_document("Ch 3", series_title="S", volume_title="B", chapter_title="Ch 3")
        dlg = OpenDocumentDialog(mem_db)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No) as mock_q:
            dlg._do_edit_volume(
                doc_a, "S", "A",
                new_volume_title="B", volume_author="", volume_illustrator="",
                volume_publisher="", volume_identifier="",
            )
        mock_q.assert_called_once()
        assert "2 chapter(s)" in mock_q.call_args.args[2]

    def test_do_edit_volume_merge_confirmed_calls_merge_true(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        doc_a = mem_db.create_document("Ch 1", series_title="S", volume_title="A", chapter_title="Ch 1")
        doc_b = mem_db.create_document("Ch 2", series_title="S", volume_title="B", chapter_title="Ch 2")
        dlg = OpenDocumentDialog(mem_db)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dlg._do_edit_volume(
                doc_a, "S", "A",
                new_volume_title="B", volume_author="Merged", volume_illustrator="",
                volume_publisher="", volume_identifier="",
            )
        for doc_id in (doc_a, doc_b):
            meta = mem_db.get_document(doc_id)
            assert meta["volume_title"] == "B"
            assert meta["volume_author"] == "Merged"

    def test_do_edit_volume_merge_cancelled_aborts(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        doc_a = mem_db.create_document("Ch 1", series_title="S", volume_title="A", chapter_title="Ch 1")
        doc_b = mem_db.create_document("Ch 2", series_title="S", volume_title="B", chapter_title="Ch 2")
        dlg = OpenDocumentDialog(mem_db)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            dlg._do_edit_volume(
                doc_a, "S", "A",
                new_volume_title="B", volume_author="Merged", volume_illustrator="",
                volume_publisher="", volume_identifier="",
            )
        assert mem_db.get_document(doc_a)["volume_title"] == "A"
        assert mem_db.get_document(doc_a)["volume_author"] == ""
        assert mem_db.get_document(doc_b)["volume_title"] == "B"

    def test_do_edit_volume_no_collision_skips_prompt(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        doc_a = mem_db.create_document("Ch 1", series_title="S", volume_title="A", chapter_title="Ch 1")
        dlg = OpenDocumentDialog(mem_db)
        with patch.object(QMessageBox, "question") as mock_q:
            dlg._do_edit_volume(
                doc_a, "S", "A",
                new_volume_title="C", volume_author="", volume_illustrator="",
                volume_publisher="", volume_identifier="",
            )
        mock_q.assert_not_called()
        assert mem_db.get_document(doc_a)["volume_title"] == "C"

    def test_prefill_from_existing_volume_fills_blank_fields(self, qapp, mem_db):
        mem_db.create_document(
            "Ch 1", series_title="S", volume_title="Vol 1", chapter_title="Ch 1",
            volume_author="Real Author", volume_illustrator="Real Illust",
            volume_publisher="Real Pub", volume_identifier="urn:isbn:9",
        )
        dlg = _EditVolumeMetadataDialog(
            volume_title="", volume_author="", volume_illustrator="",
            volume_publisher="", volume_identifier="",
            db=mem_db, series_title="S",
        )
        dlg._volume_edit.setText("Vol 1")
        dlg._prefill_from_volume()
        assert dlg._author_edit.text() == "Real Author"
        assert dlg._illustrator_edit.text() == "Real Illust"
        assert dlg._publisher_edit.text() == "Real Pub"
        assert dlg._identifier_edit.text() == "urn:isbn:9"

    def test_prefill_does_not_clobber_typed_fields_or_unknown_volume(self, qapp, mem_db):
        mem_db.create_document(
            "Ch 1", series_title="S", volume_title="Vol 1", chapter_title="Ch 1",
            volume_author="Real Author",
        )
        dlg = _EditVolumeMetadataDialog(
            volume_title="", volume_author="Typed Author", volume_illustrator="",
            volume_publisher="", volume_identifier="",
            db=mem_db, series_title="S",
        )
        dlg._volume_edit.setText("Vol 1")
        dlg._prefill_from_volume()
        assert dlg._author_edit.text() == "Typed Author"  # not clobbered

        dlg._volume_edit.setText("No Such Vol")
        dlg._illustrator_edit.setText("")
        dlg._prefill_from_volume()
        assert dlg._illustrator_edit.text() == ""  # unknown volume -> no-op

    def test_blank_volume_title_rejected_on_accept(self, qapp):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        dlg = _EditVolumeMetadataDialog(
            volume_title="Vol 1",
            volume_author="",
            volume_illustrator="",
            volume_publisher="",
            volume_identifier="",
        )
        dlg._volume_edit.setText("")
        with patch.object(QMessageBox, "warning") as mock_warn:
            dlg.accept()
            mock_warn.assert_called_once()
        assert dlg.result() != QDialog.DialogCode.Accepted


def test_open_dialog_has_five_columns(qapp, mem_db):
    dlg = OpenDocumentDialog(mem_db)
    assert dlg._tree.columnCount() == 8
    dlg.reject()


def test_open_dialog_wp_column_shows_pub_badge(qapp, mem_db):
    doc_id = mem_db.create_document("Ch 1", series_title="S", series_order=1, chapter_title="Ch 1")
    mem_db.set_document_wp_status(doc_id, "publish", "https://ex.com/ch1/")
    dlg = OpenDocumentDialog(mem_db)
    # Select series S
    for i in range(dlg._series_list.count()):
        if dlg._series_list.item(i).data(Qt.ItemDataRole.UserRole) == "S":
            dlg._series_list.setCurrentRow(i)
            break
    assert dlg._tree.topLevelItemCount() == 1
    assert dlg._tree.topLevelItem(0).text(6) == "pub"
    dlg.reject()


def test_open_dialog_wp_column_shows_sched_badge(qapp, mem_db):
    doc_id = mem_db.create_document("Ch 1", series_title="S", series_order=1, chapter_title="Ch 1")
    mem_db.set_document_wp_status(doc_id, "future", None)
    dlg = OpenDocumentDialog(mem_db)
    for i in range(dlg._series_list.count()):
        if dlg._series_list.item(i).data(Qt.ItemDataRole.UserRole) == "S":
            dlg._series_list.setCurrentRow(i)
            break
    assert dlg._tree.topLevelItem(0).text(6) == "sched"
    dlg.reject()


def test_open_dialog_wp_column_blank_when_null(qapp, mem_db):
    mem_db.create_document("Ch 1", series_title="S", series_order=1, chapter_title="Ch 1")
    dlg = OpenDocumentDialog(mem_db)
    for i in range(dlg._series_list.count()):
        if dlg._series_list.item(i).data(Qt.ItemDataRole.UserRole) == "S":
            dlg._series_list.setCurrentRow(i)
            break
    assert dlg._tree.topLevelItem(0).text(6) == ""
    dlg.reject()


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


# ---------------------------------------------------------------------------
# Persisted reordering (renumber by title + drag-drop persist)
# ---------------------------------------------------------------------------

class TestReorder:
    def _make_dlg(self, mem_db, qapp):
        a = mem_db.create_document("f1", series_title="S", series_order=1,
                                   chapter_title="Chapter 10")
        b = mem_db.create_document("f2", series_title="S", series_order=2,
                                   chapter_title="Chapter 2")
        c = mem_db.create_document("f3", series_title="S", series_order=3,
                                   chapter_title="Chapter 1")
        dlg = OpenDocumentDialog(mem_db)
        _select_series(dlg, "S")
        return dlg, (a, b, c)

    def test_renumber_by_title_natural_sort(self, qapp, mem_db):
        dlg, (a, b, c) = self._make_dlg(mem_db, qapp)
        dlg._renumber_by_title()
        assert mem_db.get_document(c)["series_order"] == 1  # Chapter 1
        assert mem_db.get_document(b)["series_order"] == 2  # Chapter 2
        assert mem_db.get_document(a)["series_order"] == 3  # Chapter 10
        assert _chapter_titles(dlg) == ["Chapter 1", "Chapter 2", "Chapter 10"]

    def test_persist_tree_order_saves_visual_order(self, qapp, mem_db):
        dlg, (a, b, c) = self._make_dlg(mem_db, qapp)
        # simulate a drag: move last item to the top
        item = dlg._tree.takeTopLevelItem(2)
        dlg._tree.insertTopLevelItem(0, item)
        dlg._persist_tree_order()
        assert mem_db.get_document(c)["series_order"] == 1
        assert mem_db.get_document(a)["series_order"] == 2
        assert mem_db.get_document(b)["series_order"] == 3
        # '#' column refreshed to match
        nums = [dlg._tree.topLevelItem(i).text(0) for i in range(3)]
        assert nums == ["1", "2", "3"]

    def test_drag_drop_mode_enabled(self, qapp, mem_db):
        dlg, _ = self._make_dlg(mem_db, qapp)
        from PySide6.QtWidgets import QTreeWidget
        assert dlg._tree.dragDropMode() == QTreeWidget.DragDropMode.InternalMove
        item = dlg._tree.topLevelItem(0)
        assert not (item.flags() & Qt.ItemFlag.ItemIsDropEnabled)


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


def _mk_series_chapters(db, titles, *, series="S"):
    ids = []
    for i, t in enumerate(titles, start=1):
        doc_id = db.create_document(
            t, series_title=series, series_order=i, chapter_title=t
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": f"{t}-l0",
             "translated_text": f"{t}-t0"},
        ])
        ids.append(doc_id)
    return ids


def _select_leaves(dlg, doc_ids):
    dlg._tree.clearSelection()
    for i in range(dlg._tree.topLevelItemCount()):
        item = dlg._tree.topLevelItem(i)
        if dlg._doc_ids.get(id(item)) in doc_ids:
            item.setSelected(True)


class TestMergeChapters:
    def test_tree_allows_multi_selection(self, qapp, mem_db):
        from PySide6.QtWidgets import QAbstractItemView
        dlg = OpenDocumentDialog(mem_db)
        assert dlg._tree.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection

    def test_merge_noop_with_single_selection(self, qapp, mem_db):
        ids = _mk_series_chapters(mem_db, ["A", "B"])
        dlg = OpenDocumentDialog(mem_db)
        _select_leaves(dlg, {ids[0]})
        dlg._on_merge()
        assert len(mem_db.list_documents()) == 2

    def test_merge_combines_selected_chapters(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox, QInputDialog
        ids = _mk_series_chapters(mem_db, ["A", "B", "C"])
        dlg = OpenDocumentDialog(mem_db)
        _select_leaves(dlg, {ids[0], ids[1]})
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QInputDialog, "getText", return_value=("AB", True)):
            dlg._on_merge()
        docs = mem_db.list_documents()
        assert len(docs) == 2
        merged = mem_db.get_lines(ids[0])
        assert [ln["raw_text"] for ln in merged] == ["A-l0", "B-l0"]
        assert mem_db.get_document(ids[0])["chapter_title"] == "AB"

    def test_merge_title_prompt_prefilled_with_first_chapter(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox, QInputDialog
        ids = _mk_series_chapters(mem_db, ["Alpha", "Beta"])
        dlg = OpenDocumentDialog(mem_db)
        _select_leaves(dlg, set(ids))
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QInputDialog, "getText",
                          return_value=("Alpha", True)) as mock_text:
            dlg._on_merge()
        # prefill passed as the `text=` kwarg or 4th positional arg
        _, kwargs = mock_text.call_args
        prefill = kwargs.get("text")
        if prefill is None:
            prefill = mock_text.call_args[0][3]
        assert prefill == "Alpha"

    def test_merge_warns_when_a_chapter_is_published(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox, QInputDialog
        ids = _mk_series_chapters(mem_db, ["A", "B"])
        mem_db.set_document_wp_status(ids[1], "publish", "http://x/b", "2026-01-01", 2)
        dlg = OpenDocumentDialog(mem_db)
        _select_leaves(dlg, set(ids))
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes) as mock_q, \
             patch.object(QInputDialog, "getText", return_value=("AB", True)):
            dlg._on_merge()
        text = " ".join(str(a) for a in mock_q.call_args[0])
        assert "WordPress" in text

    def test_merge_aborted_at_confirm_changes_nothing(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        ids = _mk_series_chapters(mem_db, ["A", "B"])
        dlg = OpenDocumentDialog(mem_db)
        _select_leaves(dlg, set(ids))
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            dlg._on_merge()
        assert len(mem_db.list_documents()) == 2

    def test_merge_aborted_at_title_changes_nothing(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox, QInputDialog
        ids = _mk_series_chapters(mem_db, ["A", "B"])
        dlg = OpenDocumentDialog(mem_db)
        _select_leaves(dlg, set(ids))
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QInputDialog, "getText", return_value=("", False)):
            dlg._on_merge()
        assert len(mem_db.list_documents()) == 2

    def test_merge_flags_open_doc_when_merged_away(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox, QInputDialog
        ids = _mk_series_chapters(mem_db, ["A", "B"])
        dlg = OpenDocumentDialog(mem_db, current_doc_id=ids[1])
        _select_leaves(dlg, set(ids))
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QInputDialog, "getText", return_value=("AB", True)):
            dlg._on_merge()
        assert dlg.open_doc_merged_away is True

    def test_merge_does_not_flag_when_open_doc_is_target(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox, QInputDialog
        ids = _mk_series_chapters(mem_db, ["A", "B"])
        dlg = OpenDocumentDialog(mem_db, current_doc_id=ids[0])
        _select_leaves(dlg, set(ids))
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QInputDialog, "getText", return_value=("AB", True)):
            dlg._on_merge()
        assert dlg.open_doc_merged_away is False


class TestBatchDelete:
    def test_delete_batch_removes_all_selected(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        ids = _mk_series_chapters(mem_db, ["A", "B", "C"])
        dlg = OpenDocumentDialog(mem_db)
        _select_leaves(dlg, {ids[0], ids[2]})
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            dlg._on_delete()
        left = {d["chapter_title"] for d in mem_db.list_documents()}
        assert left == {"B"}

    def test_delete_batch_confirmation_mentions_count(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        ids = _mk_series_chapters(mem_db, ["A", "B", "C"])
        dlg = OpenDocumentDialog(mem_db)
        _select_leaves(dlg, set(ids))
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No) as mock_q:
            dlg._on_delete()
        assert "3" in " ".join(str(a) for a in mock_q.call_args[0])
        assert len(mem_db.list_documents()) == 3

    def test_delete_batch_aborted_changes_nothing(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        ids = _mk_series_chapters(mem_db, ["A", "B"])
        dlg = OpenDocumentDialog(mem_db)
        _select_leaves(dlg, set(ids))
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            dlg._on_delete()
        assert len(mem_db.list_documents()) == 2


def _mk_long_chapter(db, raw_lines, *, series="S", order=1, title="Ch1"):
    doc_id = db.create_document(
        title, series_title=series, series_order=order, chapter_title=title
    )
    db.save_lines(doc_id, [
        {"line_number": i, "prefix": "%", "raw_text": t, "translated_text": f"tr:{t}"}
        for i, t in enumerate(raw_lines)
    ])
    return doc_id


class TestSplitChapterDialog:
    def test_loads_one_line_per_raw_line(self, qapp, mem_db):
        from translation_assistant.ui.dlg_open import _SplitChapterDialog
        doc = _mk_long_chapter(mem_db, ["l0", "l1", "l2"])
        dlg = _SplitChapterDialog(doc, "Ch1", mem_db)
        assert dlg._editor.toPlainText().split("\n") == ["l0", "l1", "l2"]

    def test_insert_marker_button_places_sentinel_on_its_own_line(self, qapp, mem_db):
        from translation_assistant.ui.dlg_open import _SplitChapterDialog, SPLIT_MARKER
        doc = _mk_long_chapter(mem_db, ["l0", "l1", "l2"])
        dlg = _SplitChapterDialog(doc, "Ch1", mem_db)
        cur = dlg._editor.textCursor()
        cur.movePosition(cur.MoveOperation.Start)
        cur.movePosition(cur.MoveOperation.Down)  # start of line "l1"
        dlg._editor.setTextCursor(cur)
        dlg._insert_marker()
        assert dlg._editor.toPlainText().split("\n") == [
            "l0", SPLIT_MARKER, "l1", "l2",
        ]

    def test_save_button_disabled_without_marker(self, qapp, mem_db):
        from translation_assistant.ui.dlg_open import _SplitChapterDialog, SPLIT_MARKER
        doc = _mk_long_chapter(mem_db, ["l0", "l1"])
        dlg = _SplitChapterDialog(doc, "Ch1", mem_db)
        assert not dlg._save_btn.isEnabled()
        dlg._editor.setPlainText(f"l0\n{SPLIT_MARKER}\nl1")
        assert dlg._save_btn.isEnabled()

    def test_split_parses_title_from_marker_line(self, qapp, mem_db):
        from translation_assistant.ui.dlg_open import _SplitChapterDialog, SPLIT_MARKER
        doc = _mk_long_chapter(mem_db, ["l0", "l1", "l2"])
        dlg = _SplitChapterDialog(doc, "Ch1", mem_db)
        dlg._editor.setPlainText(f"l0\n{SPLIT_MARKER}Second Half\nl1\nl2")
        dlg._on_split()
        new_ids = dlg._new_ids
        assert mem_db.get_document(new_ids[1])["chapter_title"] == "Second Half"
        assert [ln["raw_text"] for ln in mem_db.get_lines(new_ids[1])] == ["l1", "l2"]

    def test_split_blank_marker_leaves_title_empty_for_db_autoname(self, qapp, mem_db):
        from translation_assistant.ui.dlg_open import _SplitChapterDialog, SPLIT_MARKER
        doc = _mk_long_chapter(mem_db, ["l0", "l1"], title="My Chapter")
        dlg = _SplitChapterDialog(doc, "My Chapter", mem_db)
        dlg._editor.setPlainText(f"l0\n{SPLIT_MARKER}\nl1")
        dlg._on_split()
        assert mem_db.get_document(dlg._new_ids[1])["chapter_title"] == "My Chapter (2)"

    def test_split_ignores_leading_and_trailing_markers(self, qapp, mem_db):
        from translation_assistant.ui.dlg_open import _SplitChapterDialog, SPLIT_MARKER
        doc = _mk_long_chapter(mem_db, ["l0", "l1", "l2"])
        dlg = _SplitChapterDialog(doc, "Ch1", mem_db)
        dlg._editor.setPlainText(f"{SPLIT_MARKER}\nl0\nl1\n{SPLIT_MARKER}P2\nl2\n{SPLIT_MARKER}")
        dlg._on_split()
        assert len(dlg._new_ids) == 2  # only the middle marker counts
        assert [ln["raw_text"] for ln in mem_db.get_lines(doc)] == ["l0", "l1"]

    def test_split_no_valid_marker_warns_and_no_change(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        from translation_assistant.ui.dlg_open import _SplitChapterDialog, SPLIT_MARKER
        doc = _mk_long_chapter(mem_db, ["l0", "l1"])
        dlg = _SplitChapterDialog(doc, "Ch1", mem_db)
        dlg._editor.setPlainText(f"{SPLIT_MARKER}\nl0\nl1")
        with patch.object(QMessageBox, "warning") as mock_warn:
            dlg._on_split()
        assert mock_warn.called
        assert len(mem_db.list_documents()) == 1


class TestSplitChapterAction:
    def test_on_split_creates_segments(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog
        from translation_assistant.ui.dlg_open import _SplitChapterDialog
        ids = _mk_series_chapters(mem_db, ["A", "B"])
        long_doc = _mk_long_chapter(mem_db, ["s0", "s1", "s2"], order=2, title="B")
        mem_db.delete_document(ids[1])
        dlg = OpenDocumentDialog(mem_db)
        _select_leaves(dlg, {long_doc})

        def fake_exec(self):
            self._editor.setPlainText("s0\n---CHAPTER SPLIT---B2\ns1\ns2")
            self._on_split()
            return QDialog.DialogCode.Accepted

        with patch.object(_SplitChapterDialog, "exec", fake_exec):
            dlg._on_split()
        titles = {d["chapter_title"] for d in mem_db.list_documents()}
        assert {"A", "B", "B2"} <= titles

    def test_on_split_flags_open_doc_when_current(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog
        from translation_assistant.ui.dlg_open import _SplitChapterDialog
        long_doc = _mk_long_chapter(mem_db, ["s0", "s1", "s2"])
        dlg = OpenDocumentDialog(mem_db, current_doc_id=long_doc)
        _select_leaves(dlg, {long_doc})

        def fake_exec(self):
            self._editor.setPlainText("s0\n---CHAPTER SPLIT---P2\ns1\ns2")
            self._on_split()
            return QDialog.DialogCode.Accepted

        with patch.object(_SplitChapterDialog, "exec", fake_exec):
            dlg._on_split()
        assert dlg.open_doc_split is True

    def test_on_split_does_not_flag_other_doc(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog
        from translation_assistant.ui.dlg_open import _SplitChapterDialog
        a = _mk_series_chapters(mem_db, ["A"])[0]
        long_doc = _mk_long_chapter(mem_db, ["s0", "s1", "s2"], order=2, title="B")
        dlg = OpenDocumentDialog(mem_db, current_doc_id=a)
        _select_leaves(dlg, {long_doc})

        def fake_exec(self):
            self._editor.setPlainText("s0\n---CHAPTER SPLIT---P2\ns1\ns2")
            self._on_split()
            return QDialog.DialogCode.Accepted

        with patch.object(_SplitChapterDialog, "exec", fake_exec):
            dlg._on_split()
        assert dlg.open_doc_split is False

    def test_on_split_cancelled_changes_nothing(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog
        from translation_assistant.ui.dlg_open import _SplitChapterDialog
        long_doc = _mk_long_chapter(mem_db, ["s0", "s1", "s2"])
        dlg = OpenDocumentDialog(mem_db)
        _select_leaves(dlg, {long_doc})
        with patch.object(_SplitChapterDialog, "exec",
                          lambda self: QDialog.DialogCode.Rejected):
            dlg._on_split()
        assert len(mem_db.list_documents()) == 1


def _make_editor_dialog(kind, mem_db, lines):
    doc_id = mem_db.create_document("Story")
    mem_db.save_lines(doc_id, [
        {"line_number": i, "prefix": "%", "raw_text": t, "translated_text": ""}
        for i, t in enumerate(lines)
    ])
    if kind == "edit":
        from translation_assistant.ui.dlg_open import _EditSourceDialog
        return _EditSourceDialog(doc_id, "Story", mem_db)
    from translation_assistant.ui.dlg_open import _SplitChapterDialog
    return _SplitChapterDialog(doc_id, "Story", mem_db)


@pytest.mark.parametrize("kind", ["edit", "split"])
class TestEditorFindRow:
    def test_find_row_present(self, qapp, mem_db, kind):
        dlg = _make_editor_dialog(kind, mem_db, ["alpha", "beta"])
        assert isinstance(dlg._find_edit, type(dlg._find_edit))
        assert dlg._find_edit is not None

    def test_find_next_selects_match(self, qapp, mem_db, kind):
        dlg = _make_editor_dialog(kind, mem_db, ["alpha beta", "gamma beta"])
        dlg._find_edit.setText("gamma")
        dlg._find_next()
        assert dlg._editor.textCursor().selectedText() == "gamma"

    def test_find_next_advances_and_wraps(self, qapp, mem_db, kind):
        dlg = _make_editor_dialog(kind, mem_db, ["x", "x", "x"])
        dlg._find_edit.setText("x")
        dlg._find_next()
        p1 = dlg._editor.textCursor().selectionStart()
        dlg._find_next()
        p2 = dlg._editor.textCursor().selectionStart()
        assert p2 > p1
        dlg._find_next()          # third
        dlg._find_next()          # wrap to first
        assert dlg._editor.textCursor().selectionStart() == p1

    def test_find_prev_goes_backward(self, qapp, mem_db, kind):
        dlg = _make_editor_dialog(kind, mem_db, ["x", "x", "x"])
        dlg._find_edit.setText("x")
        dlg._find_next()
        dlg._find_next()
        mid = dlg._editor.textCursor().selectionStart()
        dlg._find_prev()
        assert dlg._editor.textCursor().selectionStart() < mid

    def test_find_case_insensitive(self, qapp, mem_db, kind):
        dlg = _make_editor_dialog(kind, mem_db, ["Alpha BETA"])
        dlg._find_edit.setText("beta")
        dlg._find_next()
        assert dlg._editor.textCursor().selectedText().lower() == "beta"

    def test_find_label_shows_index_and_total(self, qapp, mem_db, kind):
        dlg = _make_editor_dialog(kind, mem_db, ["a a a"])
        dlg._find_edit.setText("a")
        dlg._find_next()
        assert dlg._find_label.text() == "1/3"
        dlg._find_next()
        assert dlg._find_label.text() == "2/3"

    def test_find_no_match_shows_zero(self, qapp, mem_db, kind):
        dlg = _make_editor_dialog(kind, mem_db, ["alpha"])
        dlg._find_edit.setText("zzz")
        dlg._find_next()
        assert dlg._find_label.text() == "0/0"
        assert dlg._editor.textCursor().selectedText() == ""

    def test_ctrl_f_shortcut_focuses_field(self, qapp, mem_db, kind):
        from PySide6.QtGui import QKeySequence
        dlg = _make_editor_dialog(kind, mem_db, ["alpha"])
        seqs = {sc.key().toString() for sc in dlg.findChildren(__import__(
            "PySide6.QtGui", fromlist=["QShortcut"]).QShortcut)}
        assert QKeySequence("Ctrl+F").toString() in seqs


class TestPublishFromContextMenu:
    def _dlg(self, qapp, mem_db, tmp_settings, n=1):
        for i in range(1, n + 1):
            doc_id = mem_db.create_document(
                f"C{i}", series_title="Nov", series_order=i, chapter_title=f"Ch {i}"
            )
            mem_db.save_lines(doc_id, [
                {"line_number": 0, "prefix": "%", "raw_text": "a", "translated_text": "b"},
            ])
        dlg = OpenDocumentDialog(mem_db, settings=tmp_settings)
        _select_series(dlg, "Nov")
        return dlg

    def test_menu_item_enabled_for_single_selection(self, qapp, mem_db, tmp_settings, monkeypatch):
        dlg = self._dlg(qapp, mem_db, tmp_settings, n=2)
        dlg._tree.setCurrentItem(dlg._tree.topLevelItem(0))
        seen = {}
        import translation_assistant.ui.dlg_open as mod
        monkeypatch.setattr(mod, "QMenu", _capture_menu(seen))
        dlg._on_chapter_context_menu(dlg._tree.visualItemRect(dlg._tree.topLevelItem(0)).center())
        assert seen["Publish to WordPress…"] is True

    def test_menu_item_disabled_for_multi_selection(self, qapp, mem_db, tmp_settings, monkeypatch):
        dlg = self._dlg(qapp, mem_db, tmp_settings, n=2)
        dlg._tree.selectAll()
        seen = {}
        import translation_assistant.ui.dlg_open as mod
        monkeypatch.setattr(mod, "QMenu", _capture_menu(seen))
        dlg._on_chapter_context_menu(dlg._tree.visualItemRect(dlg._tree.topLevelItem(0)).center())
        assert seen["Publish to WordPress…"] is False

    def test_dispatch_calls_run_single_publish_with_selected_doc(self, qapp, mem_db, tmp_settings, monkeypatch):
        dlg = self._dlg(qapp, mem_db, tmp_settings, n=1)
        item = dlg._tree.topLevelItem(0)
        dlg._tree.setCurrentItem(item)
        target_doc_id = dlg._doc_ids[id(item)]

        captured = {}
        import translation_assistant.ui.wp_publish_flow as wpf
        monkeypatch.setattr(
            wpf, "run_single_publish",
            lambda db, settings, doc_id, parent, **kw: captured.update(
                doc_id=doc_id, has_cb="on_status_changed" in kw
            ),
        )

        class _PickPublishMenu(QMenu):
            def exec(self, *a, **k):
                for act in self.actions():
                    if act.text() == "Publish to WordPress…":
                        return act
                return None

        monkeypatch.setattr("translation_assistant.ui.dlg_open.QMenu", _PickPublishMenu)
        dlg._on_chapter_context_menu(dlg._tree.visualItemRect(item).center())
        assert captured["doc_id"] == target_doc_id
        assert captured["has_cb"] is True


def _capture_menu(seen):
    class _M(QMenu):
        def addAction(self, text, *a, **k):
            act = super().addAction(text, *a, **k)
            seen[text] = act.isEnabled()
            _orig = act.setEnabled
            def _rec(v, _o=_orig, _t=text):
                seen[_t] = v
                _o(v)
            act.setEnabled = _rec
            return act
        def exec(self, *a, **k):
            return None
    return _M

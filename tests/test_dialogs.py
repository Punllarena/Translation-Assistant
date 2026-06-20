"""
Tests for the four dialog windows — Stage 4 acceptance criteria.

All dialogs are tested without displaying them (QDialog.exec() is never called).
UI state and logic are exercised by interacting directly with internal widgets
and calling the handler methods that buttons would invoke.
"""
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDialog, QKeySequenceEdit

from translation_assistant.db import Database
from translation_assistant.settings import AppSettings
from translation_assistant.ui.dlg_profile_name import ProfileNameDialog
from translation_assistant.ui.dlg_phrase import PhraseDialog
from translation_assistant.ui.dlg_new import NewFileDialog
from translation_assistant.ui.dlg_profile import ProfileDialog


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_settings(tmp_path) -> AppSettings:
    """AppSettings backed by tmp_path so nothing touches the real user config."""
    qs = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return AppSettings(_qs=qs)


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return db


# ---------------------------------------------------------------------------
# SetupGuideDialog
# ---------------------------------------------------------------------------

class TestSetupGuideDialog:
    def test_instantiates(self, qapp):
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        dlg = SetupGuideDialog()
        assert dlg.windowTitle() == "Setup Guide — Optional Tools"

    def test_has_close_button(self, qapp):
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        from PySide6.QtWidgets import QDialogButtonBox
        dlg = SetupGuideDialog()
        bb = dlg.findChild(QDialogButtonBox)
        assert bb is not None
        assert bb.button(QDialogButtonBox.StandardButton.Close) is not None

    def test_has_mecab_group(self, qapp):
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        from PySide6.QtWidgets import QGroupBox
        dlg = SetupGuideDialog()
        titles = [g.title() for g in dlg.findChildren(QGroupBox)]
        assert any("MeCab" in t for t in titles)

    def test_has_jparser_group(self, qapp):
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        from PySide6.QtWidgets import QGroupBox
        dlg = SetupGuideDialog()
        titles = [g.title() for g in dlg.findChildren(QGroupBox)]
        assert any("JParser" in t for t in titles)


# ---------------------------------------------------------------------------
# CombinedMainWindow — Help menu
# ---------------------------------------------------------------------------

class TestCombinedWindowHelpMenu:
    def test_has_help_menu(self, qapp, tmp_path):
        import sqlite3
        from translation_assistant.ui.combined_window import CombinedMainWindow
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        db = Database(":memory:", _conn=conn)
        db.create_profile("Default", is_default=True)
        settings = make_settings(tmp_path)
        window = CombinedMainWindow(_settings=settings, _db=db)
        menu_titles = [a.text() for a in window.menuBar().actions()]
        assert "Help" in menu_titles


# ---------------------------------------------------------------------------
# ProfileNameDialog
# ---------------------------------------------------------------------------

class TestProfileNameDialog:
    def test_instantiates(self, qapp):
        dlg = ProfileNameDialog()
        assert dlg is not None

    def test_ok_disabled_initially(self, qapp):
        dlg = ProfileNameDialog()
        assert not dlg._ok_btn.isEnabled()

    def test_ok_enabled_with_text(self, qapp):
        dlg = ProfileNameDialog()
        dlg._name_edit.setText("MyProfile")
        assert dlg._ok_btn.isEnabled()

    def test_ok_disabled_when_cleared(self, qapp):
        dlg = ProfileNameDialog()
        dlg._name_edit.setText("abc")
        dlg._name_edit.clear()
        assert not dlg._ok_btn.isEnabled()

    def test_filename_empty_before_accept(self, qapp):
        dlg = ProfileNameDialog()
        assert dlg.filename == ""

    def test_sanitizes_backslash(self, qapp):
        dlg = ProfileNameDialog()
        dlg._name_edit.setText("my\\profile")
        dlg._on_accept()
        assert "\\" not in dlg.filename
        assert "_" in dlg.filename

    def test_sanitizes_all_forbidden_chars(self, qapp):
        dlg = ProfileNameDialog()
        for ch in '\\/*:?"<>|':
            dlg._name_edit.setText(f"a{ch}b")
            dlg._on_accept()
            assert ch not in dlg.filename, f"Char {ch!r} not sanitised"

    def test_normal_name_unchanged(self, qapp):
        dlg = ProfileNameDialog()
        dlg._name_edit.setText("JP_Novel_2024")
        dlg._on_accept()
        assert dlg.filename == "JP_Novel_2024"

    def test_spaces_allowed_in_name(self, qapp):
        dlg = ProfileNameDialog()
        dlg._name_edit.setText("My Profile")
        dlg._on_accept()
        assert dlg.filename == "My Profile"


# ---------------------------------------------------------------------------
# PhraseDialog — DB-backed
# ---------------------------------------------------------------------------

class TestPhraseDialog:
    def test_instantiates(self, qapp, mem_db):
        dlg = PhraseDialog(mem_db, "Default")
        assert dlg is not None

    def test_ok_disabled_initially(self, qapp, mem_db):
        dlg = PhraseDialog(mem_db, "Default")
        assert not dlg._ok_btn.isEnabled()

    def test_ok_enabled_with_translation(self, qapp, mem_db):
        dlg = PhraseDialog(mem_db, "Default")
        dlg._translation_edit.setText("hello")
        assert dlg._ok_btn.isEnabled()

    def test_ok_disabled_when_translation_cleared(self, qapp, mem_db):
        dlg = PhraseDialog(mem_db, "Default")
        dlg._translation_edit.setText("hello")
        dlg._translation_edit.clear()
        assert not dlg._ok_btn.isEnabled()

    def test_adds_phrase_to_db(self, qapp, mem_db):
        dlg = PhraseDialog(mem_db, "Default")
        dlg._phrase_edit.setText("こんにちは")
        dlg._translation_edit.setText("hello")
        dlg._on_accept()

        glossary = mem_db.get_glossary("Default")
        assert ("こんにちは", "hello") in glossary

    def test_spaces_in_translation_replaced_with_underscore(self, qapp, mem_db):
        dlg = PhraseDialog(mem_db, "Default")
        dlg._phrase_edit.setText("phrase")
        dlg._translation_edit.setText("main character")
        dlg._on_accept()

        glossary = mem_db.get_glossary("Default")
        assert ("phrase", "main_character") in glossary

    def test_adds_to_existing_db_glossary(self, qapp, mem_db):
        mem_db.set_glossary("Default", [("first", "entry")])
        dlg = PhraseDialog(mem_db, "Default")
        dlg._phrase_edit.setText("second")
        dlg._translation_edit.setText("item")
        dlg._on_accept()

        glossary = mem_db.get_glossary("Default")
        assert ("first", "entry") in glossary
        assert ("second", "item") in glossary

    def test_phrase_can_be_empty(self, qapp, mem_db):
        dlg = PhraseDialog(mem_db, "Default")
        dlg._translation_edit.setText("something")
        dlg._on_accept()

        glossary = mem_db.get_glossary("Default")
        assert any(t == "something" for _, t in glossary)


# ---------------------------------------------------------------------------
# NewFileDialog
# ---------------------------------------------------------------------------

class TestNewFileDialog:
    def test_instantiates(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        assert dlg is not None

    def test_initial_raw_output_empty(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        assert dlg.raw_output_text == ""

    def test_create_sets_raw_output_text(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._entry_box.setPlainText("A。B\nC")
        dlg._on_create()
        assert "---SEPERATOR---" in dlg.raw_output_text
        assert dlg.raw_output_text != ""

    def test_create_uses_core_build_new_file(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._entry_box.setPlainText("Hello world")
        dlg._on_create()
        assert "%Hello world" in dlg.raw_output_text
        assert "---SEPERATOR---" in dlg.raw_output_text

    def test_create_accepts_dialog(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._entry_box.setPlainText("Some text")
        dlg._on_create()
        assert dlg.result() == QDialog.DialogCode.Accepted

    def test_series_title_property(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._series_edit.setText("My Novel")
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        assert dlg.series_title == "My Novel"

    def test_series_order_property(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._order_spin.setValue(3)
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        assert dlg.series_order == 3

    def test_chapter_title_property(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._chapter_edit.setText("The Beginning")
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        assert dlg.chapter_title == "The Beginning"

    def test_metadata_defaults_to_empty(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        assert dlg.series_title == ""
        assert dlg.series_order == 0
        assert dlg.chapter_title == ""

    # --- series order auto-suggestion ---

    def test_order_auto_suggests_1_for_new_series(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._series_edit.setText("Brand New Series")
        dlg._on_series_changed("Brand New Series")
        assert dlg._order_spin.value() == 1

    def test_order_auto_suggests_next_for_existing_series(self, qapp, mem_db):
        mem_db.create_document("C1", series_title="Novel", series_order=3)
        dlg = NewFileDialog(mem_db)
        dlg._series_edit.setText("Novel")
        dlg._on_series_changed("Novel")
        assert dlg._order_spin.value() == 4

    def test_order_not_changed_when_series_cleared(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._order_spin.setValue(5)
        dlg._on_series_changed("")
        assert dlg._order_spin.value() == 5

    # --- profile link ---

    def test_profile_link_checkbox_exists(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        assert hasattr(dlg, "_link_profile_check")

    def test_profile_link_combo_exists(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        assert hasattr(dlg, "_profile_combo")

    def test_profile_link_combo_lists_profiles(self, qapp, mem_db):
        mem_db.create_profile("JP")
        dlg = NewFileDialog(mem_db)
        items = [dlg._profile_combo.itemText(i) for i in range(dlg._profile_combo.count())]
        assert "Default" in items
        assert "JP" in items

    def test_profile_preselected_for_known_series(self, qapp, mem_db):
        mem_db.create_profile("JP")
        mem_db.set_series_profile("My Novel", "JP")
        dlg = NewFileDialog(mem_db)
        dlg._series_edit.setText("My Novel")
        dlg._on_series_changed("My Novel")
        assert dlg._profile_combo.currentText() == "JP"
        assert dlg._link_profile_check.isChecked()

    def test_on_create_saves_series_profile_link(self, qapp, mem_db):
        mem_db.create_profile("JP")
        dlg = NewFileDialog(mem_db)
        dlg._series_edit.setText("New Series")
        dlg._link_profile_check.setChecked(True)
        dlg._profile_combo.setCurrentText("JP")
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        assert mem_db.get_series_profile("New Series") == "JP"

    def test_on_create_does_not_save_link_when_unchecked(self, qapp, mem_db):
        mem_db.create_profile("JP")
        dlg = NewFileDialog(mem_db)
        dlg._series_edit.setText("New Series")
        dlg._link_profile_check.setChecked(False)
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        assert mem_db.get_series_profile("New Series") == ""

    def test_link_property_returns_profile_name_when_checked(self, qapp, mem_db):
        mem_db.create_profile("JP")
        dlg = NewFileDialog(mem_db)
        dlg._series_edit.setText("Novel")
        dlg._link_profile_check.setChecked(True)
        dlg._profile_combo.setCurrentText("JP")
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        assert dlg.linked_profile == "JP"

    def test_link_property_returns_empty_when_unchecked(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._link_profile_check.setChecked(False)
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        assert dlg.linked_profile == ""

    def test_profile_combo_has_use_series_title_option(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        items = [dlg._profile_combo.itemText(i) for i in range(dlg._profile_combo.count())]
        assert "Use the Series Title" in items

    def test_use_series_title_creates_new_profile(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._series_edit.setText("My Novel")
        dlg._link_profile_check.setChecked(True)
        idx = next(i for i in range(dlg._profile_combo.count())
                   if dlg._profile_combo.itemText(i) == "Use the Series Title")
        dlg._profile_combo.setCurrentIndex(idx)
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        assert mem_db.get_profile_id("My Novel") is not None

    def test_use_series_title_links_new_profile_to_series(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._series_edit.setText("My Novel")
        dlg._link_profile_check.setChecked(True)
        idx = next(i for i in range(dlg._profile_combo.count())
                   if dlg._profile_combo.itemText(i) == "Use the Series Title")
        dlg._profile_combo.setCurrentIndex(idx)
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        assert mem_db.get_series_profile("My Novel") == "My Novel"

    def test_use_series_title_linked_profile_property(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._series_edit.setText("My Novel")
        dlg._link_profile_check.setChecked(True)
        idx = next(i for i in range(dlg._profile_combo.count())
                   if dlg._profile_combo.itemText(i) == "Use the Series Title")
        dlg._profile_combo.setCurrentIndex(idx)
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        assert dlg.linked_profile == "My Novel"

    def test_use_series_title_does_not_duplicate_existing_profile(self, qapp, mem_db):
        """If profile with series name already exists, reuse it."""
        mem_db.create_profile("My Novel")
        dlg = NewFileDialog(mem_db)
        dlg._series_edit.setText("My Novel")
        dlg._link_profile_check.setChecked(True)
        idx = next(i for i in range(dlg._profile_combo.count())
                   if dlg._profile_combo.itemText(i) == "Use the Series Title")
        dlg._profile_combo.setCurrentIndex(idx)
        dlg._entry_box.setPlainText("text")
        dlg._on_create()
        # Only one profile named "My Novel"
        assert mem_db.list_profiles().count("My Novel") == 1

    def test_on_fetch_done_fills_chapter_title_field(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._on_fetch_done("第一話　始まり", "Some content here.")
        assert dlg._chapter_edit.text() == "第一話　始まり"

    def test_on_fetch_done_does_not_overwrite_when_title_empty(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._chapter_edit.setText("Already Set")
        dlg._on_fetch_done("", "Content only.")
        assert dlg._chapter_edit.text() == "Already Set"

    def test_on_fetch_done_puts_title_in_fetch_box(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._on_fetch_done("Chapter Title", "Body text.")
        assert "Chapter Title" in dlg._fetch_box.toPlainText()
        assert "Body text." in dlg._fetch_box.toPlainText()

    def test_source_url_property_returns_url_on_fetch_tab(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._tabs.setCurrentIndex(1)
        dlg._url_edit.setText("https://ncode.syosetu.com/n1234ab/1/")
        assert dlg.source_url == "https://ncode.syosetu.com/n1234ab/1/"

    def test_source_url_property_returns_empty_on_paste_tab(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._tabs.setCurrentIndex(0)
        assert dlg.source_url == ""


# ---------------------------------------------------------------------------
# FetchSeriesDialog
# ---------------------------------------------------------------------------

class TestFetchSeriesDialog:
    def test_on_chapter_done_prepends_title_to_raw_content(self, qapp, mem_db):
        from unittest.mock import patch
        from translation_assistant.ui.dlg_fetch_series import FetchSeriesDialog

        with patch("translation_assistant.ui.dlg_fetch_series.IndexFetchWorker"):
            dlg = FetchSeriesDialog(mem_db, "My Novel", "https://ncode.syosetu.com/n1234ab/")

        dlg._on_chapter_done(1, "第一話　始まり", "本文です。", "https://ncode.syosetu.com/n1234ab/1/")

        lines = mem_db.get_lines(mem_db.list_documents()[0]["id"])
        assert lines[0]["raw_text"] == "第一話　始まり"

    def test_on_chapter_done_no_title_does_not_prepend_blank(self, qapp, mem_db):
        from unittest.mock import patch
        from translation_assistant.ui.dlg_fetch_series import FetchSeriesDialog

        with patch("translation_assistant.ui.dlg_fetch_series.IndexFetchWorker"):
            dlg = FetchSeriesDialog(mem_db, "My Novel", "https://ncode.syosetu.com/n1234ab/")

        dlg._on_chapter_done(1, "", "本文だけです。", "https://ncode.syosetu.com/n1234ab/1/")

        lines = mem_db.get_lines(mem_db.list_documents()[0]["id"])
        assert lines[0]["raw_text"].strip() != ""


# ---------------------------------------------------------------------------
# ProfileDialog — DB-backed
# ---------------------------------------------------------------------------

class TestProfileDialog:
    def test_instantiates(self, qapp, tmp_path, monkeypatch, mem_db):
        s = make_settings(tmp_path)
        dlg = ProfileDialog(s, mem_db)
        assert dlg is not None

    def test_loads_default_profile(self, qapp, tmp_path, monkeypatch, mem_db):
        s = make_settings(tmp_path)
        dlg = ProfileDialog(s, mem_db)
        assert dlg._combo.count() >= 1
        assert dlg._combo.findText("Default") >= 0

    def test_delete_disabled_for_default(self, qapp, tmp_path, monkeypatch, mem_db):
        s = make_settings(tmp_path)
        dlg = ProfileDialog(s, mem_db)
        idx = dlg._combo.findText("Default")
        dlg._combo.setCurrentIndex(idx)
        assert not dlg._delete_btn.isEnabled()

    def test_delete_enabled_for_non_default(self, qapp, tmp_path, monkeypatch, mem_db):
        s = make_settings(tmp_path)
        mem_db.create_profile("Custom")
        dlg = ProfileDialog(s, mem_db)
        idx = dlg._combo.findText("Custom")
        dlg._combo.setCurrentIndex(idx)
        assert dlg._delete_btn.isEnabled()

    def test_add_row_increases_row_count(self, qapp, tmp_path, monkeypatch, mem_db):
        s = make_settings(tmp_path)
        dlg = ProfileDialog(s, mem_db)
        initial = dlg._table.rowCount()
        dlg._append_row("phrase", "trans")
        assert dlg._table.rowCount() == initial + 1

    def test_save_writes_to_db(self, qapp, tmp_path, monkeypatch, mem_db):
        s = make_settings(tmp_path)
        dlg = ProfileDialog(s, mem_db)
        dlg._table.setRowCount(0)
        dlg._append_row("勇者", "Hero")
        dlg._append_row("剣", "Sword")
        dlg._on_save()

        glossary = mem_db.get_glossary("Default")
        assert ("勇者", "Hero") in glossary
        assert ("剣", "Sword") in glossary

    def test_save_spaces_replaced_in_translation(self, qapp, tmp_path, monkeypatch, mem_db):
        s = make_settings(tmp_path)
        dlg = ProfileDialog(s, mem_db)
        dlg._table.setRowCount(0)
        dlg._append_row("phrase", "main character")
        dlg._on_save()

        glossary = mem_db.get_glossary("Default")
        assert ("phrase", "main_character") in glossary

    def test_save_updates_settings(self, qapp, tmp_path, monkeypatch, mem_db):
        s = make_settings(tmp_path)
        dlg = ProfileDialog(s, mem_db)
        dlg._parse_edit.setText("。 ？")
        dlg._table.setRowCount(0)
        dlg._append_row("a", "b")
        dlg._on_save()

        assert s.parse_char == "。 ？"

    def test_save_returns_text_output(self, qapp, tmp_path, monkeypatch, mem_db):
        s = make_settings(tmp_path)
        dlg = ProfileDialog(s, mem_db)
        dlg._table.setRowCount(0)
        dlg._append_row("A", "B")
        dlg._on_save()
        assert dlg.text_output == ["A,B"]

    def test_table_populated_from_db(self, qapp, tmp_path, monkeypatch, mem_db):
        mem_db.set_glossary("Default", [("hero", "勇者"), ("villain", "悪役")])
        s = make_settings(tmp_path)
        dlg = ProfileDialog(s, mem_db)

        assert dlg._table.rowCount() == 2
        assert dlg._table.item(0, 0).text() == "hero"
        assert dlg._table.item(0, 1).text() == "勇者"

    def test_parse_char_field_initialised_from_settings(self, qapp, tmp_path, monkeypatch, mem_db):
        s = make_settings(tmp_path)
        s.parse_char = "。 ？ ！"
        dlg = ProfileDialog(s, mem_db)
        assert dlg._parse_edit.text() == "。 ？ ！"

    def test_multiple_profiles_listed(self, qapp, tmp_path, monkeypatch, mem_db):
        mem_db.create_profile("JP_Novel")
        mem_db.create_profile("CN_Web")
        s = make_settings(tmp_path)
        dlg = ProfileDialog(s, mem_db)
        names = [dlg._combo.itemText(i) for i in range(dlg._combo.count())]
        assert "Default" in names
        assert "JP_Novel" in names
        assert "CN_Web" in names


# ---------------------------------------------------------------------------
# StatsDialog
# ---------------------------------------------------------------------------

def test_stats_dialog_renders(qapp):
    import sqlite3
    from translation_assistant.db import Database
    from translation_assistant.ui.dlg_stats import StatsDialog
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    dlg = StatsDialog(db)
    assert dlg.windowTitle() == "Usage Statistics"
    dlg.close()


def test_stats_dialog_renders_with_data(qapp):
    import sqlite3
    from translation_assistant.db import Database
    from translation_assistant.ui.dlg_stats import StatsDialog
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    doc_id = db.create_document("Ch1", series_title="Isekai")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "hello world")
    dlg = StatsDialog(db)
    assert dlg.windowTitle() == "Usage Statistics"
    dlg.close()


# ---------------------------------------------------------------------------
# ShortcutsDialog
# ---------------------------------------------------------------------------

class TestShortcutsDialog:
    def _make_registry(self, qapp):
        """Two-entry registry for testing."""
        entries = []
        for key, name, default in [
            ("new_doc", "New Document", "Ctrl+N"),
            ("open",    "Open",         "Ctrl+O"),
        ]:
            act = QAction(name, qapp)
            act.setShortcut(default)
            entries.append((key, name, act, default))
        return entries

    def test_row_count(self, qapp, tmp_path):
        from translation_assistant.ui.dlg_shortcuts import ShortcutsDialog, _HANDLE_KEY_SHORTCUTS
        from PySide6.QtWidgets import QTableWidget
        settings = make_settings(tmp_path)
        registry = self._make_registry(qapp)
        dlg = ShortcutsDialog(registry, settings)
        table = dlg.findChild(QTableWidget)
        # 1 "Editable" header + len(registry) rows + 1 "View Only" header + len(_HANDLE_KEY_SHORTCUTS) rows
        expected = 2 + len(registry) + len(_HANDLE_KEY_SHORTCUTS)
        assert table.rowCount() == expected

    def test_edit_and_save(self, qapp, tmp_path):
        from translation_assistant.ui.dlg_shortcuts import ShortcutsDialog
        from PySide6.QtWidgets import QTableWidget
        settings = make_settings(tmp_path)
        registry = self._make_registry(qapp)
        dlg = ShortcutsDialog(registry, settings)
        table = dlg.findChild(QTableWidget)
        # Row 0: "Editable" section header. Row 1: first editable row (new_doc).
        cell_widget = table.cellWidget(1, 1)
        assert cell_widget is not None, "Expected cell widget at row 1, col 1"
        kse = cell_widget.findChild(QKeySequenceEdit)
        kse.setKeySequence(QKeySequence("Ctrl+Z"))
        dlg._on_ok()
        assert settings.get_shortcut("new_doc") == "Ctrl+Z"
        _, _, action, _ = registry[0]
        assert action.shortcut().toString() == "Ctrl+Z"

    def test_reset_defaults(self, qapp, tmp_path):
        from translation_assistant.ui.dlg_shortcuts import ShortcutsDialog
        from PySide6.QtWidgets import QTableWidget
        settings = make_settings(tmp_path)
        registry = self._make_registry(qapp)
        dlg = ShortcutsDialog(registry, settings)
        table = dlg.findChild(QTableWidget)
        # Change new_doc shortcut in the UI
        cell_widget = table.cellWidget(1, 1)
        kse = cell_widget.findChild(QKeySequenceEdit)
        kse.setKeySequence(QKeySequence("Ctrl+Z"))
        # Reset — should revert to default without saving
        dlg._on_reset()
        assert kse.keySequence().toString() == "Ctrl+N"
        assert settings.get_shortcut("new_doc") is None  # not saved

    def test_conflict_blocks_save(self, qapp, tmp_path):
        from translation_assistant.ui.dlg_shortcuts import ShortcutsDialog
        from PySide6.QtWidgets import QTableWidget
        from unittest.mock import patch
        settings = make_settings(tmp_path)
        registry = self._make_registry(qapp)
        dlg = ShortcutsDialog(registry, settings)
        table = dlg.findChild(QTableWidget)
        # Set both rows (new_doc=row1, open=row2) to the same shortcut
        for row in (1, 2):
            cell_widget = table.cellWidget(row, 1)
            kse = cell_widget.findChild(QKeySequenceEdit)
            kse.setKeySequence(QKeySequence("Ctrl+Z"))
        with patch("translation_assistant.ui.dlg_shortcuts.QMessageBox.warning") as mock_warn:
            dlg._on_ok()
            mock_warn.assert_called_once()
        # Settings must remain unchanged
        assert settings.get_shortcut("new_doc") is None
        assert settings.get_shortcut("open") is None

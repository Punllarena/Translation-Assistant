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
from PySide6.QtWidgets import QDialog

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

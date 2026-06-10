"""
Tests for NewSeriesDialog.
All tests bypass exec() — call _on_accept() directly and inspect state.
"""
import sqlite3
import pytest
from unittest.mock import patch

from PySide6.QtWidgets import QDialog

from translation_assistant.db import Database
from translation_assistant.ui.dlg_new_series import NewSeriesDialog


@pytest.fixture
def mem_db(qapp):
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return db


class TestNewSeriesDialog:
    def test_instantiates(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        assert dlg is not None

    def test_empty_title_rejected(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("")
        with patch("translation_assistant.ui.dlg_new_series.QMessageBox.warning"):
            dlg._on_accept()
        assert dlg.result() != QDialog.DialogCode.Accepted

    def test_series_url_saved(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("https://ncode.syosetu.com/n1234ab/")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert mem_db.get_series_url("My Series") == "https://ncode.syosetu.com/n1234ab/"

    def test_empty_url_accepted(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert dlg.result() == QDialog.DialogCode.Accepted

    def test_profile_created_when_checked(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(True)
        dlg._on_accept()
        assert mem_db.get_profile_id("My Series") is not None
        assert mem_db.get_series_profile("My Series") == "My Series"

    def test_profile_not_created_when_unchecked(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert mem_db.get_profile_id("My Series") is None

    def test_duplicate_series_url_updated(self, qapp, mem_db):
        mem_db.set_series_url("My Series", "https://old.url/")
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("https://new.url/")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert mem_db.get_series_url("My Series") == "https://new.url/"

    def test_profile_already_exists_no_error(self, qapp, mem_db):
        mem_db.create_profile("My Series")
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(True)
        dlg._on_accept()
        assert mem_db.get_profile_id("My Series") is not None
        assert dlg.result() == QDialog.DialogCode.Accepted

    def test_series_title_property(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert dlg.series_title == "My Series"

    def test_created_profile_property_when_checked(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(True)
        dlg._on_accept()
        assert dlg.created_profile == "My Series"

    def test_created_profile_property_when_unchecked(self, qapp, mem_db):
        dlg = NewSeriesDialog(mem_db)
        dlg._title_edit.setText("My Series")
        dlg._url_edit.setText("")
        dlg._profile_check.setChecked(False)
        dlg._on_accept()
        assert dlg.created_profile == ""

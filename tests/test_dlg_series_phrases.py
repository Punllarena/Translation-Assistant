"""Tests for SeriesPhrasesDialog."""
import sqlite3
import pytest

from translation_assistant.db import Database
from translation_assistant.ui.dlg_series_phrases import SeriesPhrasesDialog


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_with_series(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_profile("Default", is_default=True)
    db.create_profile("Isekai")
    doc_id = db.create_document("Ch1", series_title="My Series")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "太郎", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "花子", "translated_text": ""},
    ])
    db.set_series_profile("My Series", "Isekai")
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_series_combo_populated_and_preselected(qapp, tmp_settings, db_with_series):
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    series = [dlg._series_combo.itemText(i) for i in range(dlg._series_combo.count())]
    assert "My Series" in series
    assert dlg._series_combo.currentText() == "My Series"


def test_profile_defaults_to_series_profile(qapp, tmp_settings, db_with_series):
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    assert dlg._profile_combo.currentText() == "Isekai"


def test_no_series_disables_analyze_button(qapp, tmp_settings):
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    dlg = SeriesPhrasesDialog(db, tmp_settings)
    assert not dlg._analyze_btn.isEnabled()
    assert dlg._status_label.text() == "No series found"


def test_analyze_populates_table(qapp, tmp_settings, db_with_series, monkeypatch):
    monkeypatch.setattr(
        "translation_assistant.ui.dlg_series_phrases.extract_frequent_nouns",
        lambda lines, glossary, min_freq, **kw: [("太郎", 5), ("花子", 3)],
    )
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    dlg._on_analyze()
    assert dlg._table.rowCount() == 2
    assert dlg._table.item(0, 0).text() == "太郎"
    assert dlg._table.item(0, 1).text() == "5"


def test_analyze_no_lines_shows_status(qapp, tmp_settings):
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    db.create_document("Ch1", series_title="Empty Series")
    dlg = SeriesPhrasesDialog(db, tmp_settings, current_series="Empty Series")
    dlg._on_analyze()
    assert dlg._table.rowCount() == 0
    assert "No lines found" in dlg._status_label.text()


def test_row_selection_enables_translation_field(qapp, tmp_settings, db_with_series, monkeypatch):
    monkeypatch.setattr(
        "translation_assistant.ui.dlg_series_phrases.extract_frequent_nouns",
        lambda lines, glossary, min_freq, **kw: [("太郎", 5)],
    )
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    dlg._on_analyze()
    assert not dlg._translation_edit.isEnabled()
    dlg._table.selectRow(0)
    dlg._on_selection_changed()
    assert dlg._translation_edit.isEnabled()
    assert not dlg._add_btn.isEnabled()  # no translation text yet


def test_add_btn_enabled_when_translation_non_empty(qapp, tmp_settings, db_with_series, monkeypatch):
    monkeypatch.setattr(
        "translation_assistant.ui.dlg_series_phrases.extract_frequent_nouns",
        lambda lines, glossary, min_freq, **kw: [("太郎", 5)],
    )
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    dlg._on_analyze()
    dlg._table.selectRow(0)
    dlg._on_selection_changed()
    dlg._translation_edit.setText("Taro")
    dlg._on_translation_changed("Taro")
    assert dlg._add_btn.isEnabled()


def test_add_saves_phrase_and_removes_row(qapp, tmp_settings, db_with_series, monkeypatch):
    monkeypatch.setattr(
        "translation_assistant.ui.dlg_series_phrases.extract_frequent_nouns",
        lambda lines, glossary, min_freq, **kw: [("太郎", 5)],
    )
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    dlg._on_analyze()
    dlg._table.selectRow(0)
    dlg._on_selection_changed()
    dlg._translation_edit.setText("Taro")
    dlg._on_add()
    assert dlg._table.rowCount() == 0
    assert ("太郎", "Taro") in db_with_series.get_glossary("Isekai")


def test_profile_change_refilters_results(qapp, tmp_settings, db_with_series, monkeypatch):
    db_with_series.add_phrase("Isekai", "太郎", "Taro")
    monkeypatch.setattr(
        "translation_assistant.ui.dlg_series_phrases.extract_frequent_nouns",
        lambda lines, glossary, min_freq, **kw: [("太郎", 5), ("花子", 3)],
    )
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    # Analyze with Default profile (empty glossary) — both terms visible
    dlg._profile_combo.setCurrentText("Default")
    dlg._on_profile_changed("Default")
    dlg._on_analyze()
    assert dlg._table.rowCount() == 2
    # Switch to Isekai (has 太郎) — 太郎 filtered out
    dlg._profile_combo.setCurrentText("Isekai")
    dlg._on_profile_changed("Isekai")
    terms = [dlg._table.item(r, 0).text() for r in range(dlg._table.rowCount())]
    assert "太郎" not in terms
    assert "花子" in terms

"""
Tests for MainWindow — Stage 5 acceptance criteria.

Widgets are exercised without showing them (window.show() is never called).
Navigation logic, state management, and file I/O are tested directly.
"""
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings

from translation_assistant.db import Database
from translation_assistant.settings import AppSettings
from translation_assistant.ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_settings(tmp_path: Path) -> AppSettings:
    qs = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return AppSettings(_qs=qs)


def _make_db() -> Database:
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return db


def _sep_file(raw: str, translated: str = "") -> str:
    """Build a minimal SEPERATOR-format file string."""
    return raw + "\n---SEPERATOR---\n" + translated


@pytest.fixture
def win(qapp, tmp_path):
    """MainWindow backed by isolated QSettings and an in-memory DB."""
    settings = _make_settings(tmp_path)
    w = MainWindow(_settings=settings, _db=_make_db())
    yield w
    w.destroy()


def _load(win: MainWindow, raw_content: str) -> None:
    """Helper: load a SEPERATOR file string into the window."""
    win.load_content(_sep_file(raw_content))


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_instantiates(self, win):
        assert win is not None

    def test_has_import_action(self, win):
        assert hasattr(win, "_action_import")

    def test_has_export_action(self, win):
        assert hasattr(win, "_action_export")

    def test_export_disabled_initially(self, win):
        assert not win._action_export.isEnabled()

    def test_title(self, win):
        assert "Translation Assistant" in win.windowTitle()

    def test_save_disabled_initially(self, win):
        assert not win._action_save.isEnabled()

    def test_clipboard_action_disabled_initially(self, win):
        assert not win._action_clipboard.isEnabled()

    def test_help_text_shown_in_review_top(self, win):
        assert "HOW TO USE" in win._review_top.toPlainText()

    def test_help_text_shown_in_review_bottom(self, win):
        assert "NAVIGATION CONTROLS" in win._review_bottom.toPlainText()


# ---------------------------------------------------------------------------
# Content loading
# ---------------------------------------------------------------------------

class TestLoadContent:
    def test_load_populates_raw_lines(self, win):
        _load(win, "%Hello\n$World\n")
        assert len(win._raw_lines) == 2
        assert win._raw_lines[0] == "%Hello"
        assert win._raw_lines[1] == "$World"

    def test_load_populates_translated_lines(self, win):
        _load(win, "%Line\n")
        assert len(win._translated_lines) == 1

    def test_load_resets_pointer(self, win):
        _load(win, "%First\n%Second\n")
        win._array_pointer = 1
        _load(win, "%Again\n")
        assert win._array_pointer == 0

    def test_load_enables_save(self, win):
        _load(win, "%A\n")
        assert win._action_save.isEnabled()

    def test_load_enables_clipboard_action(self, win):
        _load(win, "%A\n")
        assert win._action_clipboard.isEnabled()

    def test_raw_line_widget_shows_display_text(self, win):
        _load(win, "%Hello\n")
        assert "Hello" in win._raw_line.toPlainText()
        assert "%" not in win._raw_line.toPlainText()

    def test_translated_line_widget_populated(self, win):
        content = _sep_file("%Hello\n", "Hola\n")
        win.load_content(content)
        assert win._translated_line.toPlainText() == "Hola"

    def test_review_bottom_shows_subsequent_lines(self, win):
        _load(win, "%First\n%Second\n%Third\n")
        assert "Second" in win._review_bottom.toPlainText()
        assert "Third" in win._review_bottom.toPlainText()

    def test_review_top_empty_at_line_zero(self, win):
        _load(win, "%Only\n")
        assert win._review_top.toPlainText() == ""

    def test_line_status_updated(self, win):
        _load(win, "%A\n%B\n%C\n")
        assert "1/" in win._line_label.text()
        assert "3" in win._line_label.text()

    def test_progress_starts_at_zero(self, win):
        _load(win, "%A\n%B\n")
        assert "0%" in win._completion_label.text()


# ---------------------------------------------------------------------------
# Navigation — forward
# ---------------------------------------------------------------------------

class TestNavigateForward:
    def test_enter_advances_pointer(self, win):
        _load(win, "%First\n%Second\n")
        win._navigate_forward()
        assert win._array_pointer == 1

    def test_advance_skips_empty_lines(self, win):
        _load(win, "%A\n\n%B\n")
        win._navigate_forward()
        assert win._array_pointer == 2

    def test_advance_skips_bare_percent_marker(self, win):
        """'%' line (blank source paragraph) skipped by forward nav."""
        win._raw_lines = ["%A", "%", "%B"]
        win._translated_lines = ["", "", ""]
        win._array_pointer = 0
        win._navigate_forward()
        assert win._array_pointer == 2

    def test_advance_saves_translation(self, win):
        _load(win, "%A\n%B\n")
        win._translated_line.setPlainText("Hello")
        win._navigate_forward()
        assert win._translated_lines[0] == "Hello"

    def test_advance_does_not_go_past_end(self, win):
        _load(win, "%Only\n")
        win._navigate_forward()
        assert win._array_pointer == 0  # stays at 0, eof

    def test_advance_updates_raw_line_widget(self, win):
        _load(win, "%First\n%Second\n")
        win._navigate_forward()
        assert "Second" in win._raw_line.toPlainText()

    def test_advance_updates_review_top(self, win):
        _load(win, "%First\n%Second\n")
        win._navigate_forward()
        assert "First" in win._review_top.toPlainText()

    def test_enter_saves_to_db(self, win):
        _load(win, "%A\n%B\n")
        win._translated_line.setPlainText("Alpha")
        win._navigate_forward(write_file=True)
        lines = win._db.get_lines(win._doc_id)
        assert lines[0]["translated_text"] == "Alpha"

    def test_pgdn_saves_translation_via_partial_update(self, win):
        _load(win, "%A\n%B\n")
        win._translated_line.setPlainText("Alpha")
        win._navigate_forward(write_file=False)
        lines = win._db.get_lines(win._doc_id)
        assert lines[0]["translated_text"] == "Alpha"


# ---------------------------------------------------------------------------
# Navigation — backward
# ---------------------------------------------------------------------------

class TestNavigateBackward:
    def test_page_up_retreats_pointer(self, win):
        _load(win, "%A\n%B\n")
        win._array_pointer = 1
        win._navigate_backward()
        assert win._array_pointer == 0

    def test_page_up_at_first_line_stays(self, win):
        _load(win, "%A\n%B\n")
        win._navigate_backward()
        assert win._array_pointer == 0

    def test_page_up_skips_empty_lines(self, win):
        _load(win, "%A\n\n%B\n")
        win._array_pointer = 2
        win._navigate_backward()
        assert win._array_pointer == 0

    def test_page_up_skips_bare_percent_marker(self, win):
        """'%' line (blank source paragraph) skipped by backward nav."""
        win._raw_lines = ["%A", "%", "%B"]
        win._translated_lines = ["", "", ""]
        win._array_pointer = 2
        win._navigate_backward()
        assert win._array_pointer == 0

    def test_page_up_saves_translation(self, win):
        _load(win, "%A\n%B\n")
        win._array_pointer = 1
        win._translated_line.setPlainText("Beta")
        win._navigate_backward()
        assert win._translated_lines[1] == "Beta"


# ---------------------------------------------------------------------------
# Jump to first / next untranslated
# ---------------------------------------------------------------------------

class TestJumps:
    def test_jump_to_first(self, win):
        _load(win, "%A\n%B\n%C\n")
        win._array_pointer = 2
        win._jump_to_first()
        assert win._array_pointer == 0

    def test_jump_to_first_saves_translation(self, win):
        _load(win, "%A\n%B\n")
        win._array_pointer = 1
        win._translated_line.setPlainText("Beta")
        win._jump_to_first()
        assert win._translated_lines[1] == "Beta"

    def test_jump_to_first_does_nothing_at_zero(self, win):
        _load(win, "%A\n%B\n")
        win._jump_to_first()
        assert win._array_pointer == 0

    def test_jump_to_next_untranslated(self, win):
        content = _sep_file("%A\n%B\n%C\n", "done\ndone\n\n")
        win.load_content(content)
        win._translated_line.setPlainText("x")  # non-empty so jump is allowed
        win._jump_to_next_untranslated()
        assert win._array_pointer == 2

    def test_jump_to_next_untranslated_requires_nonempty_current(self, win):
        _load(win, "%A\n%B\n")
        win._translated_line.setPlainText("")
        win._jump_to_next_untranslated()
        assert win._array_pointer == 0  # no jump


# ---------------------------------------------------------------------------
# Parse navigation
# ---------------------------------------------------------------------------

class TestParseNavigation:
    def setup_method(self):
        """Each test sets up parse chars before creating win."""

    def test_advance_parse_selects_first_sentence(self, win):
        win._parse_chars = ["。"]
        win._glossary = []
        _load(win, "%Hello。World。\n")
        win._advance_parse()
        assert win._parse_pointer == 0
        assert win._parse_sentences[0] in win._raw_line.toPlainText()

    def test_advance_parse_pointer_bounded(self, win):
        win._parse_chars = ["。"]
        win._glossary = []
        _load(win, "%A。B。\n")
        # Only 2 sentences; advance 5 times
        for _ in range(5):
            win._advance_parse()
        assert win._parse_pointer == 1  # capped at last sentence index

    def test_retreat_parse_from_zero_goes_to_minus_one(self, win):
        win._parse_chars = ["。"]
        win._glossary = []
        _load(win, "%A。B。\n")
        win._advance_parse()
        assert win._parse_pointer == 0
        win._retreat_parse()
        assert win._parse_pointer == -1

    def test_retreat_parse_no_replaced_stops_at_minus_one(self, win):
        win._parse_chars = ["。"]
        win._glossary = []
        _load(win, "%A。\n")
        win._replaced = False
        win._parse_pointer = -1
        win._retreat_parse()
        assert win._parse_pointer == -1

    def test_retreat_parse_with_replaced_can_reach_minus_two(self, win):
        win._parse_chars = ["。"]
        win._glossary = []
        _load(win, "%A。\n")
        win._replaced = True
        win._parse_pointer = -1
        win._retreat_parse()
        assert win._parse_pointer == -2


# ---------------------------------------------------------------------------
# Save / write file
# ---------------------------------------------------------------------------

class TestSaveToDB:
    def test_load_content_creates_db_doc(self, win):
        _load(win, "%A\n%B\n")
        assert win._doc_id is not None

    def test_save_to_db_persists_translated_lines(self, win):
        _load(win, "%A\n%B\n")
        win._translated_lines[0] = "Translation A"
        win._translated_lines[1] = "Translation B"
        win._save_to_db()
        lines = win._db.get_lines(win._doc_id)
        assert lines[0]["translated_text"] == "Translation A"
        assert lines[1]["translated_text"] == "Translation B"

    def test_on_save_shows_filesaved_label(self, win):
        _load(win, "%A\n")
        win._on_save()
        assert "saved" in win._filesaved_label.text().lower()

    def test_on_save_captures_current_line_to_db(self, win):
        _load(win, "%A\n")
        win._translated_line.setPlainText("MyTranslation")
        win._on_save()
        lines = win._db.get_lines(win._doc_id)
        assert lines[0]["translated_text"] == "MyTranslation"

    def test_load_content_switches_to_linked_profile_immediately(self, win):
        """Profile switches at document creation, not just on open."""
        win._db.create_profile("JP")
        win._db.set_series_profile("My Novel", "JP")
        content = _sep_file("%Text\n")
        win.load_content(content, title="Ch1", series_title="My Novel")
        assert win._settings.profile_used == "JP"

    def test_load_content_no_switch_when_no_series_link(self, win):
        win._settings.profile_used = "Default"
        content = _sep_file("%Text\n")
        win.load_content(content, title="Standalone")
        assert win._settings.profile_used == "Default"

    def test_save_preserves_raw_text_in_db(self, win):
        _load(win, "%Hello\n")
        win._on_save()
        lines = win._db.get_lines(win._doc_id)
        assert lines[0]["raw_text"] == "Hello"
        assert lines[0]["prefix"] == "%"


class TestOpenDocument:
    def test_open_document_sets_doc_id(self, win):
        doc_id = win._db.create_document("Test")
        win._db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Hello", "translated_text": ""},
        ])
        win.open_document(doc_id)
        assert win._doc_id == doc_id

    def test_open_document_populates_raw_lines(self, win):
        doc_id = win._db.create_document("Test")
        win._db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "First", "translated_text": ""},
            {"line_number": 1, "prefix": "%", "raw_text": "Second", "translated_text": ""},
        ])
        win.open_document(doc_id)
        assert len(win._raw_lines) == 2
        assert win._raw_lines[0] == "%First"
        assert win._raw_lines[1] == "%Second"

    def test_open_document_populates_translated_lines(self, win):
        doc_id = win._db.create_document("Test")
        win._db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        win.open_document(doc_id)
        assert win._translated_lines[0] == "Alpha"

    def test_open_document_restores_last_position(self, win):
        doc_id = win._db.create_document("Test")
        win._db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": ""},
            {"line_number": 1, "prefix": "%", "raw_text": "B", "translated_text": ""},
        ])
        win._db.set_last_position(doc_id, 1)
        win.open_document(doc_id)
        assert win._array_pointer == 1

    def test_open_document_switches_to_series_linked_profile(self, win):
        win._db.create_profile("JP")
        win._db.set_series_profile("My Novel", "JP")
        doc_id = win._db.create_document("Ch1", series_title="My Novel")
        win._db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Text", "translated_text": ""},
        ])
        win.open_document(doc_id)
        assert win._settings.profile_used == "JP"

    def test_open_document_no_switch_when_no_series_link(self, win):
        win._db.create_profile("JP")
        win._settings.profile_used = "Default"
        doc_id = win._db.create_document("Standalone")
        win._db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Text", "translated_text": ""},
        ])
        win.open_document(doc_id)
        assert win._settings.profile_used == "Default"


# ---------------------------------------------------------------------------
# Glossary and parse chars
# ---------------------------------------------------------------------------

class TestGlossaryAndParseChars:
    def test_parse_chars_loaded_from_settings(self, win):
        win._settings.parse_char = "。 ？ ！"
        win._update_parse_chars()
        assert "。" in win._parse_chars
        assert "？" in win._parse_chars

    def test_glossary_applied_to_raw_display(self, win):
        win._glossary = [("勇者", "Hero")]
        win._parse_chars = []
        _load(win, "%勇者が来た。\n")
        assert "Hero" in win._raw_line.toPlainText()
        assert "勇者" not in win._raw_line.toPlainText()

    def test_replaced_flag_set_when_glossary_used(self, win):
        win._glossary = [("A", "B")]
        win._parse_chars = []
        _load(win, "%A test\n")
        assert win._replaced is True

    def test_replaced_flag_false_when_no_glossary_match(self, win):
        win._glossary = [("X", "Y")]
        win._parse_chars = []
        _load(win, "%Hello\n")
        assert win._replaced is False


# ---------------------------------------------------------------------------
# Import / Export — Stage F
# ---------------------------------------------------------------------------

class TestImportExport:
    def test_export_enabled_after_load(self, win):
        _load(win, "%A\n")
        assert win._action_export.isEnabled()

    def test_on_export_writes_txt(self, win, tmp_path, monkeypatch):
        _load(win, "%A\n")
        win._translated_line.setPlainText("Alpha")
        out = tmp_path / "exported.txt"
        monkeypatch.setattr(
            "translation_assistant.ui.main_window.QFileDialog.getSaveFileName",
            lambda *a, **kw: (str(out), ""),
        )
        win._on_export()
        content = out.read_text(encoding="utf-8")
        assert "---SEPERATOR---" in content
        assert "%A" in content
        assert "Alpha" in content

    def test_on_export_cancel_no_write(self, win, tmp_path, monkeypatch):
        _load(win, "%A\n")
        monkeypatch.setattr(
            "translation_assistant.ui.main_window.QFileDialog.getSaveFileName",
            lambda *a, **kw: ("", ""),
        )
        win._on_export()  # must not raise

    def test_on_export_no_doc_does_nothing(self, win, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(
            "translation_assistant.ui.main_window.QFileDialog.getSaveFileName",
            lambda *a, **kw: called.append(1) or ("", ""),
        )
        win._on_export()
        assert not called  # dialog not shown when no doc loaded


# ---------------------------------------------------------------------------
# Punctuation insertion
# ---------------------------------------------------------------------------

class TestPunctuationInsertion:
    def test_insert_single_quote_bracket(self, win):
        win._translated_line.setPlainText("")
        win._insert_punctuation(0)  # 「」
        text = win._translated_line.toPlainText()
        assert text == "「」"

    def test_cursor_between_brackets(self, win):
        win._translated_line.setPlainText("")
        win._insert_punctuation(0)  # 「」
        pos = win._translated_line.textCursor().position()
        assert pos == 1  # between 「 and 」

    def test_insert_ellipsis(self, win):
        win._translated_line.setPlainText("")
        win._insert_punctuation(3)  # …
        assert win._translated_line.toPlainText() == "…"

    def test_insert_wave_dash(self, win):
        win._translated_line.setPlainText("")
        win._insert_punctuation(4)  # 〜
        assert win._translated_line.toPlainText() == "〜"

    def test_insert_long_dash(self, win):
        win._translated_line.setPlainText("")
        win._insert_punctuation(7)  # ー
        assert win._translated_line.toPlainText() == "ー"

    def test_insert_at_cursor_position(self, win):
        win._translated_line.setPlainText("AB")
        cursor = win._translated_line.textCursor()
        cursor.setPosition(1)
        win._translated_line.setTextCursor(cursor)
        win._insert_punctuation(3)  # … (1 char)
        assert win._translated_line.toPlainText() == "A…B"


# ---------------------------------------------------------------------------
# Progress display
# ---------------------------------------------------------------------------

class TestProgressDisplay:
    def test_completion_updates_after_navigation(self, win):
        content = _sep_file("%A\n%B\n", "done\n\n")
        win.load_content(content)
        win._navigate_forward()
        assert "50%" in win._completion_label.text()

    def test_progress_hidden_when_setting_off(self, win):
        win._settings.show_progress = False
        win._update_progress_visibility()
        assert win._completion_label.isHidden()
        assert win._line_label.isHidden()

    def test_progress_shown_when_setting_on(self, win):
        win._settings.show_progress = True
        win._update_progress_visibility()
        assert not win._completion_label.isHidden()


# ---------------------------------------------------------------------------
# Dictionary
# ---------------------------------------------------------------------------

class TestDictionary:
    def test_add_to_dictionary_writes_db(self, win):
        cursor = win._translated_line.textCursor()
        win._translated_line.setPlainText("someword")
        cursor.select(cursor.SelectionType.Document)
        win._translated_line.setTextCursor(cursor)

        with patch("PySide6.QtWidgets.QMessageBox.information"):
            win._add_to_dictionary()

        assert "someword" in win._db.get_custom_words("Default")

    def test_add_to_dictionary_no_selection_does_nothing(self, win):
        before = win._db.get_custom_words("Default")
        win._translated_line.setPlainText("word")
        # no selection
        win._add_to_dictionary()
        assert win._db.get_custom_words("Default") == before

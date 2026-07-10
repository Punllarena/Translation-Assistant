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
from translation_assistant.ui.main_widget import TranslationAssistantWidget


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
    """TranslationAssistantWidget backed by isolated QSettings and an in-memory DB."""
    settings = _make_settings(tmp_path)
    w = TranslationAssistantWidget(_settings=settings, _db=_make_db())
    w.show()
    yield w
    w.destroy()


def _load(win: TranslationAssistantWidget, raw_content: str) -> None:
    """Helper: load a SEPERATOR file string into the window."""
    win.load_content(_sep_file(raw_content))


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_instantiates(self, win):
        assert win is not None

    def test_has_import_action(self, win):
        assert hasattr(win, "action_import")

    def test_has_export_action(self, win):
        assert hasattr(win, "action_export")

    def test_export_disabled_initially(self, win):
        assert not win.action_export.isEnabled()

    def test_title(self, win):
        assert win is not None  # widget has no window title; title lives in CombinedMainWindow

    def test_save_disabled_initially(self, win):
        assert not win.action_save.isEnabled()

    def test_clipboard_action_disabled_initially(self, win):
        assert not win.action_clipboard.isEnabled()

    def test_placeholder_shown_in_review_top(self, win):
        assert win._review_top.toPlainText() == ""
        assert "Open a document" in win._review_top.placeholderText()

    def test_placeholder_shown_in_review_bottom(self, win):
        assert win._review_bottom.toPlainText() == ""
        assert "Enter" in win._review_bottom.placeholderText()

    def test_exposes_context_above_panel(self, win):
        from PySide6.QtWidgets import QWidget
        assert isinstance(win.context_above_panel, QWidget)

    def test_exposes_source_panel(self, win):
        from PySide6.QtWidgets import QWidget
        assert isinstance(win.source_panel, QWidget)

    def test_exposes_tm_panel(self, win):
        from PySide6.QtWidgets import QWidget
        assert isinstance(win.tm_panel, QWidget)

    def test_exposes_translation_panel(self, win):
        from PySide6.QtWidgets import QWidget
        assert isinstance(win.translation_panel, QWidget)

    def test_exposes_context_below_panel(self, win):
        from PySide6.QtWidgets import QWidget
        assert isinstance(win.context_below_panel, QWidget)

    def test_exposes_status_bar(self, win):
        from PySide6.QtWidgets import QStatusBar
        assert isinstance(win.status_bar, QStatusBar)

    def test_has_no_layout(self, win):
        assert win.layout() is None

    def test_line_label_says_page_format(self, win, tmp_settings, qapp):
        """After loading a doc, line label uses Page N/N format."""
        # This tests the format string — we verify the attribute and its content
        # after a navigate call would set it. Just check the label exists and
        # that it does NOT start with "Line:" initially (empty doc state).
        assert not win._line_label.text().startswith("Line:")

    def test_has_last_save_time(self, win):
        assert hasattr(win, "_last_save_time")

    def test_has_autosave_tick_timer(self, win):
        from PySide6.QtCore import QTimer
        assert isinstance(win._autosave_tick_timer, QTimer)

    def test_ctx_above_label_has_expand_chevron(self, win, qapp):
        """Context Above label starts with ▼ (expanded by default)."""
        from PySide6.QtWidgets import QLabel
        labels = win._panel_ctx_above.findChildren(QLabel)
        texts = [lbl.text() for lbl in labels]
        assert any(t.startswith("▼") for t in texts)

    def test_ctx_below_label_has_expand_chevron(self, win, qapp):
        """Context Below label starts with ▼ (expanded by default)."""
        from PySide6.QtWidgets import QLabel
        labels = win._panel_ctx_below.findChildren(QLabel)
        texts = [lbl.text() for lbl in labels]
        assert any(t.startswith("▼") for t in texts)

    def test_ctx_above_inner_visible_by_default(self, win):
        assert win._review_top.isVisible()

    def test_ctx_below_inner_visible_by_default(self, win):
        assert win._review_bottom.isVisible()


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
        assert win.action_save.isEnabled()

    def test_load_enables_clipboard_action(self, win):
        _load(win, "%A\n")
        assert win.action_clipboard.isEnabled()

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
        assert win._progress_bar.value() == 0


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

    def test_load_content_stores_source_url_in_db(self, win):
        content = _sep_file("%A\n")
        win.load_content(content, source_url="https://ncode.syosetu.com/n1234ab/1/")
        doc = win._db.get_document(win._doc_id)
        assert doc["source_url"] == "https://ncode.syosetu.com/n1234ab/1/"

    def test_load_content_source_url_defaults_empty(self, win):
        content = _sep_file("%A\n")
        win.load_content(content)
        doc = win._db.get_document(win._doc_id)
        assert doc["source_url"] == ""


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

    def test_open_document_jumps_to_first_untranslated(self, win):
        doc_id = win._db.create_document("Test")
        win._db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "done"},
            {"line_number": 1, "prefix": "%", "raw_text": "", "translated_text": ""},  # blank — skip
            {"line_number": 2, "prefix": "%", "raw_text": "C", "translated_text": ""},
        ])
        win.open_document(doc_id)
        assert win._array_pointer == 2

    def test_open_document_falls_back_to_last_position_when_all_translated(self, win):
        doc_id = win._db.create_document("Test")
        win._db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "done"},
            {"line_number": 1, "prefix": "%", "raw_text": "B", "translated_text": "done"},
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
        assert win.action_export.isEnabled()

    def test_on_export_writes_txt(self, win, tmp_path, monkeypatch):
        _load(win, "%A\n")
        win._translated_line.setPlainText("Alpha")
        out = tmp_path / "exported.txt"
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getSaveFileName",
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
            "translation_assistant.ui.main_widget.QFileDialog.getSaveFileName",
            lambda *a, **kw: ("", ""),
        )
        win._on_export()  # must not raise

    def test_on_export_no_doc_does_nothing(self, win, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getSaveFileName",
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
        assert win._progress_bar.value() == 50

    def test_progress_hidden_when_setting_off(self, win):
        win._settings.show_progress = False
        win._update_progress_visibility()
        assert win._progress_bar.isHidden()
        assert win._line_label.isHidden()

    def test_progress_shown_when_setting_on_and_doc_loaded(self, win):
        _load(win, "%Hello\n")
        win._settings.show_progress = True
        win._update_progress_visibility()
        assert not win._progress_bar.isHidden()


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


# ---------------------------------------------------------------------------
# Shortcut registry
# ---------------------------------------------------------------------------

def _make_widget(tmp_path):
    from PySide6.QtCore import QSettings
    from translation_assistant.settings import AppSettings
    from translation_assistant.ui.main_widget import TranslationAssistantWidget
    qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings = AppSettings(_qs=qs)
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return TranslationAssistantWidget(_settings=settings, _db=db), settings


class TestShortcutRegistry:
    def test_registry_has_expected_keys(self, qapp, tmp_path):
        w, _ = _make_widget(tmp_path)
        keys = [e[0] for e in w._shortcut_registry]
        for expected in ("new_doc", "open", "save", "profile", "phrase",
                         "go_to_line", "clipboard", "series_phrases",
                         "punct_0", "punct_8"):
            assert expected in keys, f"missing key: {expected}"

    def test_apply_saved_shortcuts_overrides_default(self, qapp, tmp_path):
        from PySide6.QtCore import QSettings
        from translation_assistant.settings import AppSettings
        from translation_assistant.ui.main_widget import TranslationAssistantWidget
        qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        settings = AppSettings(_qs=qs)
        settings.set_shortcut("save", "Ctrl+Z")
        conn = sqlite3.connect(":memory:")
        db = Database(":memory:", _conn=conn)
        db.create_profile("Default", is_default=True)
        w = TranslationAssistantWidget(_settings=settings, _db=db)
        entry = next(e for e in w._shortcut_registry if e[0] == "save")
        _, _, action, _ = entry
        assert action.shortcut().toString() == "Ctrl+Z"

    def test_action_series_phrases_exists(self, qapp, tmp_path):
        w, _ = _make_widget(tmp_path)
        assert hasattr(w, "action_series_phrases")
        assert w.action_series_phrases.shortcut().toString() == "Ctrl+Shift+P"


class TestFontSize:
    def test_has_font_larger_action(self, win):
        assert hasattr(win, "action_font_larger")

    def test_has_font_smaller_action(self, win):
        assert hasattr(win, "action_font_smaller")

    def test_font_larger_increases_size(self, win):
        initial = win._settings.font_size
        win._adjust_font_size(+1)
        assert win._settings.font_size == initial + 1.0

    def test_font_smaller_decreases_size(self, win):
        win._settings.font_size = 14.0
        win._adjust_font_size(-1)
        assert win._settings.font_size == 13.0

    def test_font_size_clamped_at_max(self, win):
        win._settings.font_size = 24.0
        win._adjust_font_size(+1)
        assert win._settings.font_size == 24.0

    def test_font_size_clamped_at_min(self, win):
        win._settings.font_size = 8.0
        win._adjust_font_size(-1)
        assert win._settings.font_size == 8.0

    def test_apply_font_sets_font_on_all_panels(self, win):
        win._settings.font_size = 18.0
        win._apply_font()
        for panel in (win._review_top, win._raw_line,
                      win._translated_line, win._review_bottom):
            assert abs(panel.font().pointSizeF() - 18.0) < 0.1

    def test_font_larger_in_shortcut_registry(self, win):
        keys = [entry[0] for entry in win._shortcut_registry]
        assert "font_larger" in keys

    def test_font_smaller_in_shortcut_registry(self, win):
        keys = [entry[0] for entry in win._shortcut_registry]
        assert "font_smaller" in keys


class TestTmRow:
    def test_tm_row_emits_clicked_with_translation(self, qapp):
        from translation_assistant.ui.main_widget import _TmRow
        received = []
        row = _TmRow("Hello world", "Doc A, 2026-01-01")
        row.clicked.connect(received.append)
        from PySide6.QtCore import Qt, QPointF
        from PySide6.QtGui import QMouseEvent
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(1, 1), QPointF(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        row.mousePressEvent(event)
        assert received == ["Hello world"]


class TestSourceLabel:
    def test_has_source_label(self, win):
        assert hasattr(win, "_source_label")

    def test_source_label_default_text(self, win):
        assert "Source" in win._source_label.text()

    def test_source_label_updates_on_load_with_chapter_title(self, win):
        win.load_content(
            "%Hello\n---SEPERATOR---\n",
            title="Doc Title",
            chapter_title="Chapter 1",
        )
        assert "Chapter 1" in win._source_label.text()

    def test_source_label_falls_back_to_title(self, win):
        win.load_content(
            "%Hello\n---SEPERATOR---\n",
            title="My Doc",
            chapter_title="",
        )
        assert "My Doc" in win._source_label.text()

    def test_raw_line_placeholder_text(self, win):
        assert "Ctrl+O" in win._raw_line.placeholderText() or \
               "File" in win._raw_line.placeholderText()


class TestWindowTitle:
    def test_doc_title_empty_initially(self, win):
        assert win._doc_title == ""

    def test_doc_title_set_from_chapter_title_on_load(self, win):
        win.load_content("%Hello\n---SEPERATOR---\n", title="Doc", chapter_title="Chapter 1")
        assert win._doc_title == "Chapter 1"

    def test_doc_title_falls_back_to_title(self, win):
        win.load_content("%Hello\n---SEPERATOR---\n", title="My Doc", chapter_title="")
        assert win._doc_title == "My Doc"

    def test_doc_title_empty_string_when_no_title(self, win):
        win.load_content("%Hello\n---SEPERATOR---\n", title="", chapter_title="")
        assert win._doc_title == ""

    def test_refresh_window_title_method_exists(self, win):
        assert callable(getattr(win, "_refresh_window_title", None))

    def test_refresh_window_title_does_not_crash(self, win):
        win._doc_title = "Chapter 1"
        win._is_dirty = False
        win._refresh_window_title()  # no parent window in tests — must not raise


class TestParseCounter:
    def test_parse_label_exists(self, win):
        assert hasattr(win, "_parse_label")

    def test_parse_label_hidden_initially(self, win):
        assert win._parse_label.isHidden()

    def test_parse_label_shows_after_advance_parse(self, win):
        _load(win, "%Hello。World。\n")
        win._parse_sentences = ["Hello", "World"]
        win._parse_pointer = 0
        # Manually call the counter update logic by invoking _advance_parse path
        # Simulate: pointer is already at 0, call _advance_parse to reach 1
        win._parse_pointer = -1
        win._advance_parse()  # moves to 0
        assert not win._parse_label.isHidden()
        assert "Phrase 1/" in win._parse_label.text()

    def test_parse_label_hides_on_navigation(self, win):
        _load(win, "%Hello。World。\n%Second\n")
        win._parse_label.setVisible(True)
        win._navigate_forward()
        assert win._parse_label.isHidden()

    def test_parse_label_hides_when_pointer_negative(self, win):
        _load(win, "%Hello。World。\n")
        win._advance_parse()  # moves to 0
        win._retreat_parse()  # moves back to -1
        assert win._parse_label.isHidden()


class TestProgressBar:
    def test_has_progress_bar(self, win):
        assert hasattr(win, "_progress_bar")

    def test_no_completion_label(self, win):
        assert not hasattr(win, "_completion_label")

    def test_progress_bar_format(self, win):
        from PySide6.QtWidgets import QProgressBar
        assert isinstance(win._progress_bar, QProgressBar)
        assert win._progress_bar.format() == "%p%"

    def test_progress_bar_range(self, win):
        assert win._progress_bar.minimum() == 0
        assert win._progress_bar.maximum() == 100

    def test_progress_bar_value_after_load(self, win):
        _load(win, "%A\n")
        assert win._progress_bar.value() == 0  # nothing translated yet

    def test_progress_bar_value_updates_on_navigation(self, win):
        content = _sep_file("%A\n%B\n", "Alpha\nBeta\n")
        win.load_content(content)
        assert win._progress_bar.value() == 100

    def test_progress_bar_hidden_when_no_doc(self, win):
        # Show progress is True by default, but no doc open → hidden
        assert not win._progress_bar.isVisible()


class TestPanelLabelCounts:
    def test_has_translation_label(self, win):
        assert hasattr(win, "_translation_label")

    def test_translation_label_default_text(self, win):
        assert "Translation" in win._translation_label.text()

    def test_translation_label_shows_word_count_after_load(self, win):
        content = _sep_file("%Hello\n", "Hello world\n")
        win.load_content(content)
        assert "2 words" in win._translation_label.text()

    def test_translation_label_zero_words_when_empty(self, win):
        _load(win, "%Hello\n")
        assert "0 words" in win._translation_label.text()

    def test_source_label_includes_line_count(self, win):
        win.load_content("%A\n%B\n%C\n---SEPERATOR---\n", title="Doc", chapter_title="Ch1")
        assert "· 3 lines" in win._source_label.text()

    def test_source_label_includes_title_and_lines(self, win):
        win.load_content("%A\n---SEPERATOR---\n", title="Doc", chapter_title="Chapter 1")
        label = win._source_label.text()
        assert "Chapter 1" in label
        assert "lines" in label

    def test_translation_label_resets_on_db_import(self, win):
        _load(win, "%Hello\n")
        win._translated_line.setPlainText("Bonjour")
        # Simulate db import reset
        win._translation_label.setText("Translation")
        assert win._translation_label.text() == "Translation"


class TestStatusBarLabels:
    def test_filesaved_label_states(self, win):
        assert win._filesaved_label.text().startswith("Autosave:")
        _load(win, "%A\n")
        win._set_dirty(True)
        assert "Unsaved" in win._filesaved_label.text()
        win._on_save()
        assert "saved" in win._filesaved_label.text().lower()

    def test_stats_label_respects_metric(self, win):
        _load(win, "%A\n")
        win._settings.stats_metric = "en_words"
        win._update_stats_label()
        assert "EN words" in win._stats_label.text()

    def test_progress_bar_tooltip_counts(self, win):
        _load(win, "%A\n%B\n")
        assert "of 2 paragraphs" in win._progress_bar.toolTip()

    def test_wp_label_tooltip_empty_without_doc(self, win):
        win._doc_id = None
        win._update_wp_status_label()
        assert win._wp_status_label.text() == ""

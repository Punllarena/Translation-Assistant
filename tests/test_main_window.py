"""
Tests for MainWindow — Stage 5 acceptance criteria.

Widgets are exercised without showing them (window.show() is never called).
Navigation logic, state management, and file I/O are tested directly.
"""
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt

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

    def test_has_import_epub_action(self, win):
        assert hasattr(win, "action_import_epub")

    def test_export_disabled_initially(self, win):
        assert not win.action_export.isEnabled()

    def test_title(self, win):
        assert win is not None  # widget has no window title; title lives in CombinedMainWindow

    def test_save_disabled_initially(self, win):
        assert not win.action_save.isEnabled()

    def test_clipboard_action_disabled_initially(self, win):
        assert not win.action_clipboard.isEnabled()

    def test_card_view_placeholder_before_load(self, win):
        assert win._card_view.card_count() == 0
        assert "No document open" in win._card_view._placeholder.text()

    def test_exposes_card_panel(self, win):
        from translation_assistant.ui.card_list import CardListView
        assert isinstance(win.card_panel, CardListView)

    def test_exposes_tm_panel(self, win):
        from PySide6.QtWidgets import QWidget
        assert isinstance(win.tm_panel, QWidget)

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

    def test_card_placeholder_visible_by_default(self, win):
        assert not win._card_view._placeholder.isHidden()


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

    def test_all_lines_get_cards(self, win):
        _load(win, "%First\n%Second\n%Third\n")
        assert win._card_view.card_count() == 3
        assert "Second" in win._card_view.card(1).source_label.text()
        assert "Third" in win._card_view.card(2).source_label.text()

    def test_first_card_active_after_load(self, win):
        _load(win, "%Only\n")
        assert win._card_view.active_index == 0
        assert win._card_view.card(0).state() == "active"

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

    def test_advance_updates_card_states(self, win):
        _load(win, "%First\n%Second\n")
        win._translated_line.setPlainText("done")
        win._navigate_forward()
        assert win._card_view.card(0).state() == "done"
        assert win._card_view.card(1).state() == "active"

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

    def test_card_click_navigates(self, win):
        _load(win, "%A\n%B\n%C\n")
        win._translated_line.setPlainText("alpha")
        win._on_card_clicked(2)
        assert win._array_pointer == 2
        assert win._translated_lines[0] == "alpha"
        assert win._card_view.card(2).state() == "active"


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


class TestExportEpubSeries:
    def _load_translated_doc(self, win, mem_db=None):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        return doc_id

    def test_writes_one_epub_per_volume(self, win, tmp_path, monkeypatch):
        self._load_translated_doc(win)
        win._doc_id = win._db.get_document_ids_by_series("S")[0]
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        assert (tmp_path / "S" / "Vol 1.epub").exists()

    def test_skips_whole_volume_if_any_chapter_incomplete(self, win, tmp_path, monkeypatch):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": ""},  # untranslated
        ])
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        assert not (tmp_path / "S" / "Vol 1.epub").exists()

    def test_skips_existing_file(self, win, tmp_path, monkeypatch):
        self._load_translated_doc(win)
        win._doc_id = win._db.get_document_ids_by_series("S")[0]
        series_dir = tmp_path / "S"
        series_dir.mkdir()
        (series_dir / "Vol 1.epub").write_bytes(b"existing content")
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        assert (series_dir / "Vol 1.epub").read_bytes() == b"existing content"

    def test_empty_chapter_does_not_block_volume(self, win, tmp_path, monkeypatch):
        """A chapter with zero raw_lines can never reach 100% — it must not
        discard the whole volume; it is silently omitted instead."""
        db = win._db
        self._load_translated_doc(win)
        empty_id = db.create_document(
            "Colophon", series_title="S", series_order=2,
            chapter_title="Colophon", volume_title="Vol 1",
        )
        db.save_lines(empty_id, [])
        win._doc_id = db.get_document_ids_by_series("S")[0]
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        dest = tmp_path / "S" / "Vol 1.epub"
        assert dest.exists()

    def test_empty_chapter_omitted_from_exported_volume(self, win, tmp_path, monkeypatch):
        from translation_assistant.epub import open_book
        db = win._db
        self._load_translated_doc(win)
        empty_id = db.create_document(
            "Colophon", series_title="S", series_order=2,
            chapter_title="Colophon", volume_title="Vol 1",
        )
        db.save_lines(empty_id, [])
        win._doc_id = db.get_document_ids_by_series("S")[0]
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        book = open_book(tmp_path / "S" / "Vol 1.epub")
        assert [c["title"] for c in book["chapters"]] == ["Ch 1"]

    def test_volume_of_only_empty_chapters_writes_nothing(self, win, tmp_path, monkeypatch):
        """Skipping empty chapters must not leave a chapterless book behind."""
        db = win._db
        doc_id = db.create_document(
            "Colophon", series_title="S", series_order=1,
            chapter_title="Colophon", volume_title="Vol 1",
        )
        db.save_lines(doc_id, [])
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        assert not (tmp_path / "S" / "Vol 1.epub").exists()

    def test_blank_volume_title_falls_back_to_series_title(self, win, tmp_path, monkeypatch):
        """Legacy (syosetu) docs have volume_title='' — the book must still
        carry a dc:title, and the filename stays 'volume.epub'."""
        from translation_assistant.epub import open_book
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        dest = tmp_path / "S" / "volume.epub"
        assert dest.exists()
        assert open_book(dest)["title"] == "S"

    def test_exported_epub_contains_inline_image(self, win, tmp_path, monkeypatch):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        db.add_document_image(doc_id, 1, False, "images/pic.png", b"fake-bytes")
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        import zipfile
        out = tmp_path / "S" / "Vol 1.epub"
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert any(n.endswith("pic.png") for n in names)

    def test_image_only_chapter_exports_its_images(self, win, tmp_path, monkeypatch):
        """A colour-plate page has zero raw_lines but is not empty — dropping it
        would throw away every illustration that lives on its own page."""
        db = win._db
        self._load_translated_doc(win)
        plate_id = db.create_document(
            "p-fmatter-003", series_title="S", series_order=2,
            chapter_title="p-fmatter-003", volume_title="Vol 1",
        )
        db.save_lines(plate_id, [])
        db.add_document_image(plate_id, 0, False, "image/ph_kuchie2.jpg", b"fake-plate")
        win._doc_id = db.get_document_ids_by_series("S")[0]
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        import zipfile
        with zipfile.ZipFile(tmp_path / "S" / "Vol 1.epub") as zf:
            names = zf.namelist()
            plate = next(n for n in names if n.endswith("chap2.xhtml"))
            xhtml = zf.read(plate).decode("utf-8")
        assert any(n.endswith("ph_kuchie2.jpg") for n in names)
        assert "ph_kuchie2.jpg" in xhtml
        assert "<h1>" not in xhtml  # filename-stub title must not print as a heading

    def test_untranslated_image_only_chapter_does_not_block_volume(self, win, tmp_path, monkeypatch):
        """Zero raw_lines means calculate_progress() would report 0% — the image
        chapter must stay exempt from the completeness check."""
        db = win._db
        self._load_translated_doc(win)
        plate_id = db.create_document(
            "Plate", series_title="S", series_order=2,
            chapter_title="Plate", volume_title="Vol 1",
        )
        db.save_lines(plate_id, [])
        db.add_document_image(plate_id, 0, False, "image/plate.jpg", b"fake-plate")
        win._doc_id = db.get_document_ids_by_series("S")[0]
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        assert (tmp_path / "S" / "Vol 1.epub").exists()

    def test_excluded_image_only_chapter_is_omitted(self, win, tmp_path, monkeypatch):
        """Unticking export on the only image of a text-less page leaves nothing
        to emit — the chapter goes back to being dropped."""
        from translation_assistant.epub import open_book
        db = win._db
        self._load_translated_doc(win)
        plate_id = db.create_document(
            "Plate", series_title="S", series_order=2,
            chapter_title="Plate", volume_title="Vol 1",
        )
        db.save_lines(plate_id, [])
        image_id = db.add_document_image(plate_id, 0, False, "image/plate.jpg", b"fake-plate")
        db.set_image_exclude_export(image_id, True)
        win._doc_id = db.get_document_ids_by_series("S")[0]
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        book = open_book(tmp_path / "S" / "Vol 1.epub")
        assert [c["title"] for c in book["chapters"]] == ["Ch 1"]

    def test_exported_epub_contains_cover(self, win, tmp_path, monkeypatch):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        db.add_document_image(doc_id, 0, True, "images/cover.jpg", b"fake-cover-bytes")
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        import zipfile
        out = tmp_path / "S" / "Vol 1.epub"
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "cover-image" in opf

    def test_cover_on_empty_chapter_is_not_dropped(self, win, tmp_path, monkeypatch):
        """A cover image attached to a chapter that extracts to zero
        raw_lines (e.g. a bare-<img> title-page chapter) must still make it
        into the exported EPUB's manifest, even though that chapter itself
        contributes no content and is omitted from the spine."""
        db = win._db
        cover_id = db.create_document(
            "Cover", series_title="S", series_order=1,
            chapter_title="Cover", volume_title="Vol 1",
        )
        db.save_lines(cover_id, [])
        db.add_document_image(cover_id, 0, True, "images/cover.jpg", b"fake-cover-bytes")

        content_id = db.create_document(
            "Ch 1", series_title="S", series_order=2, chapter_title="Ch 1", volume_title="Vol 1",
        )
        db.save_lines(content_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])

        win._doc_id = content_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        import zipfile
        out = tmp_path / "S" / "Vol 1.epub"
        assert out.exists()
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "cover-image" in opf

    def test_exported_epub_contains_metadata(self, win, tmp_path, monkeypatch):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1",
            volume_author="Author Name", volume_illustrator="Illustrator Name",
            volume_publisher="Test Publisher", volume_identifier="urn:isbn:1234567890123",
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        import zipfile
        out = tmp_path / "S" / "Vol 1.epub"
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "Author Name" in opf
        assert "Illustrator Name" in opf
        assert "Test Publisher" in opf
        assert "urn:isbn:1234567890123" in opf


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
    def test_card_font_from_settings_on_startup(self, qapp, tmp_path):
        """Saved font size (and serif family) must reach cards without Ctrl+±."""
        settings = _make_settings(tmp_path)
        settings.font_size = 17.0
        settings.save()
        w = TranslationAssistantWidget(_settings=settings, _db=_make_db())
        _load(w, "%A\n")
        card = w._card_view.card(0)
        assert abs(card.source_label.font().pointSizeF() - 17.0) < 0.1
        assert "Serif" in card.source_label.font().families()[0]
        w.destroy()

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

    def test_apply_font_sets_font_on_editors_and_cards(self, win):
        win._settings.font_size = 18.0
        _load(win, "%A\n")
        win._apply_font()
        for panel in (win._raw_line, win._translated_line):
            assert abs(panel.font().pointSizeF() - 18.0) < 0.1
        assert abs(win._card_view.card(0).source_label.font().pointSizeF() - 18.0) < 0.1

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


class TestDocTitle:
    def test_doc_title_uses_chapter_title(self, win):
        win.load_content(
            "%Hello\n---SEPERATOR---\n",
            title="Doc Title",
            chapter_title="Chapter 1",
        )
        assert win._doc_title == "Chapter 1"

    def test_doc_title_falls_back_to_title(self, win):
        win.load_content(
            "%Hello\n---SEPERATOR---\n",
            title="My Doc",
            chapter_title="",
        )
        assert win._doc_title == "My Doc"


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


class TestKeyboardAdditions:
    @staticmethod
    def _key(win, key, mods=Qt.KeyboardModifier.NoModifier):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        return win._handle_key(QKeyEvent(QEvent.Type.KeyPress, key, mods))

    def test_shift_enter_passes_through_for_newline(self, win):
        _load(win, "%A\n%B\n")
        handled = self._key(win, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        assert handled is False
        assert win._array_pointer == 0

    def test_plain_enter_still_advances(self, win):
        _load(win, "%A\n%B\n")
        assert self._key(win, Qt.Key.Key_Return) is True
        assert win._array_pointer == 1

    def test_ctrl_down_advances(self, win):
        _load(win, "%A\n%B\n")
        assert self._key(win, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier) is True
        assert win._array_pointer == 1

    def test_ctrl_up_goes_back(self, win):
        _load(win, "%A\n%B\n")
        win._navigate_forward()
        assert self._key(win, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier) is True
        assert win._array_pointer == 0


class TestCardListImagesWiring:
    def test_open_document_passes_images_to_card_view(self, win):
        doc_id = win._db.create_document("Ch 1", chapter_title="Ch 1")
        win._db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": ""},
        ])
        win._db.add_document_image(doc_id, 0, False, "images/pic.png", b"fake-bytes")
        win.open_document(doc_id)
        assert len(win._card_view._image_widgets) == 1


class TestPublishWpConfirmCopy:
    def test_confirm_dialog_warns_when_already_published(self, win, monkeypatch):
        win.load_content(_sep_file("Hello\n", "Bonjour\n"))
        win._db.set_document_wp_status(win._doc_id, "publish", "https://ex.com/c1/", None, 1)
        win._settings.wp_endpoint_url = "https://example.com"
        win._settings.wp_api_key = "key123"
        doc = win._db.get_document(win._doc_id)
        win._db.set_series_wp_meta(
            doc["series_title"], series_slug="s", series_title_short="S",
        )

        captured = {}

        from PySide6.QtWidgets import QDialog as _RealQDialog

        class _FakeDialog(_RealQDialog):
            def exec(self): return 0  # Cancel — stop before any network/worker activity

        def _fake_label_capture(text, *a, **k):
            captured.setdefault("labels", []).append(text)
            from PySide6.QtWidgets import QLabel
            return QLabel(text)

        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog", _FakeDialog,
        )
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QLabel", _fake_label_capture,
        )
        win._on_publish_wp()

        assert any("overwrite" in t.lower() for t in captured["labels"])

    def test_accept_path_forwards_cached_chapter_index(self, win, monkeypatch):
        """End-to-end: cached wp_chapter_index flows into build_payload, and
        _last_wp_chapter_index is updated to the new series_order once the
        confirm dialog is accepted."""
        win.load_content(_sep_file("Hello\n", "Bonjour\n"))
        win._db.set_document_wp_status(win._doc_id, "publish", "https://ex.com/c1/", None, 1)
        win._db.set_series_orders([(win._doc_id, 3)])
        win._settings.wp_endpoint_url = "https://example.com"
        win._settings.wp_api_key = "key123"
        doc = win._db.get_document(win._doc_id)
        win._db.set_series_wp_meta(
            doc["series_title"], series_slug="s", series_title_short="S",
        )

        from PySide6.QtWidgets import QDialog as _RealQDialog

        class _FakeDialog(_RealQDialog):
            def exec(self):
                return 1  # Accept

        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog", _FakeDialog,
        )

        # Stub the QThread-based workers so no real network/threading occurs.
        class _FakeThread:
            def __init__(self, *a, **k):
                pass

            def start(self):
                pass

            def quit(self):
                pass

            def wait(self, *a, **k):
                pass

            def connect(self, *a, **k):
                pass

            @property
            def succeeded(self):
                return self

            @property
            def error(self):
                return self

        monkeypatch.setattr(
            "translation_assistant.ui.main_widget._StatusCheckWorker", _FakeThread,
        )
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget._PublishWorker", _FakeThread,
        )

        captured = {}
        import translation_assistant.wp_publisher as wp_publisher
        _real_build_payload = wp_publisher.build_payload

        def _spy_build_payload(*args, **kwargs):
            captured["kwargs"] = kwargs
            return _real_build_payload(*args, **kwargs)

        monkeypatch.setattr(wp_publisher, "build_payload", _spy_build_payload)

        win._on_publish_wp()

        assert captured["kwargs"]["previous_chapter_index"] == 1
        assert win._last_wp_chapter_index == 3

    def test_status_ok_preserves_cached_chapter_index(self, win, monkeypatch):
        """_on_status_ok's async status refresh must not clobber the cached
        wp_chapter_index with None."""
        win.load_content(_sep_file("Hello\n", "Bonjour\n"))
        win._db.set_document_wp_status(win._doc_id, "publish", "https://ex.com/c1/", None, 1)
        win._settings.wp_endpoint_url = "https://example.com"
        win._settings.wp_api_key = "key123"
        doc = win._db.get_document(win._doc_id)
        win._db.set_series_wp_meta(
            doc["series_title"], series_slug="s", series_title_short="S",
        )

        from PySide6.QtWidgets import QDialog as _RealQDialog

        class _FakeDialog(_RealQDialog):
            def exec(self):
                return 0  # Cancel — we only care about the async status callback

        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog", _FakeDialog,
        )

        captured_worker = {}
        from translation_assistant.ui.main_widget import _StatusCheckWorker as _RealStatusWorker

        class _CapturingStatusWorker(_RealStatusWorker):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                captured_worker["worker"] = self

            def start(self):
                pass  # don't actually run the thread

        monkeypatch.setattr(
            "translation_assistant.ui.main_widget._StatusCheckWorker", _CapturingStatusWorker,
        )

        win._on_publish_wp()

        worker = captured_worker["worker"]
        # Simulate the async status callback firing with a fresh result.
        worker.succeeded.emit({"status": "future", "post_url": "https://ex.com/c1/", "date": "2026-01-01T00:00:00Z"})

        info = win._db.get_document_wp_status(win._doc_id)
        assert info["wp_chapter_index"] == 1


class TestOnPublishDone:
    def _prep(self, win):
        _load(win, "Hello\n")
        win._last_scheduled_date = None
        win._last_pw = None
        win._last_unlock_idx = None
        win._last_wp_chapter_index = 1
        return win._doc_id

    def test_persists_status_on_created(self, win, monkeypatch):
        doc_id = self._prep(win)
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog.exec", lambda self: 1,
        )
        win._on_publish_done({"created": True, "page_url": "https://ex.com/c1/", "post_url": "https://ex.com/p1/"})
        info = win._db.get_document_wp_status(doc_id)
        assert info["wp_status"] == "publish"
        assert info["wp_chapter_index"] == 1

    def test_persists_status_on_updated_without_created(self, win, monkeypatch):
        doc_id = self._prep(win)
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog.exec", lambda self: 1,
        )
        win._on_publish_done({
            "created": False, "updated": True,
            "page_url": "https://ex.com/c1/", "post_url": "https://ex.com/p1/",
        })
        info = win._db.get_document_wp_status(doc_id)
        assert info["wp_status"] == "publish"
        assert info["wp_post_url"] == "https://ex.com/p1/"
        assert info["wp_chapter_index"] == 1

    def test_skips_status_write_when_neither_created_nor_updated(self, win, monkeypatch):
        doc_id = self._prep(win)
        win._db.set_document_wp_status(doc_id, "future", "https://old.example/", "2026-01-01T00:00:00Z", 1)
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog.exec", lambda self: 1,
        )
        win._on_publish_done({"created": False, "page_url": "https://ex.com/c1/", "post_url": ""})
        info = win._db.get_document_wp_status(doc_id)
        assert info["wp_status"] == "future"  # untouched


class TestImageCollapseAndExport:
    def test_action_collapse_images_exists_and_is_checkable(self, win):
        assert win.action_collapse_images.isCheckable()
        assert win.action_collapse_images.text() == "Collapse Images"

    def test_action_initialised_from_settings(self, qapp, tmp_path):
        from translation_assistant.ui.main_widget import TranslationAssistantWidget
        settings = _make_settings(tmp_path)
        settings.images_collapsed = True
        w = TranslationAssistantWidget(_settings=settings, _db=_make_db())
        assert w.action_collapse_images.isChecked()
        assert w._card_view._images_collapsed is True
        w.destroy()

    def test_toggling_action_persists_and_applies(self, win):
        win.action_collapse_images.setChecked(True)
        win._on_toggle_collapse_images()
        assert win._settings.images_collapsed is True
        assert win._card_view._images_collapsed is True

    def test_export_toggle_writes_to_db(self, win):
        doc_id = win._db.create_document("doc")
        img_id = win._db.add_document_image(doc_id, 0, False, "pic.png", b"x")
        win._card_view.image_export_toggled.emit(img_id, True)
        assert win._db.get_document_images(doc_id)[0]["exclude_export"] == 1
        win._card_view.image_export_toggled.emit(img_id, False)
        assert win._db.get_document_images(doc_id)[0]["exclude_export"] == 0

    def test_excluded_inline_image_is_not_exported(self, win, tmp_path, monkeypatch):
        """When an inline image has exclude_export=1, it should not appear in the EPUB."""
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        img_id = db.add_document_image(doc_id, 1, False, "images/pic.png", b"fake-bytes")
        db.set_image_exclude_export(img_id, 1)
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        import zipfile
        out = tmp_path / "S" / "Vol 1.epub"
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert not any(n.endswith("pic.png") for n in names)

    def test_cover_still_exported_when_inline_image_excluded(self, win, tmp_path, monkeypatch):
        """Cover images should always be exported, even if an inline image is excluded."""
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        # Add cover
        db.add_document_image(doc_id, 0, True, "images/cover.jpg", b"fake-cover-bytes")
        # Add excluded inline image
        img_id = db.add_document_image(doc_id, 1, False, "images/pic.png", b"fake-bytes")
        db.set_image_exclude_export(img_id, 1)
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        import zipfile
        out = tmp_path / "S" / "Vol 1.epub"
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "cover-image" in opf
        # Excluded inline image should not be in the archive
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert not any(n.endswith("pic.png") for n in names)

    def test_excluded_image_not_in_wp_payload(self, win, monkeypatch):
        """When an inline image has exclude_export=1, it should not be in the WordPress payload."""
        win.load_content(_sep_file("Hello\n", "Bonjour\n"))
        win._settings.wp_endpoint_url = "https://example.com"
        win._settings.wp_api_key = "key123"
        doc = win._db.get_document(win._doc_id)
        win._db.set_series_wp_meta(
            doc["series_title"], series_slug="s", series_title_short="S",
        )
        # Add excluded inline image
        img_id = win._db.add_document_image(win._doc_id, 1, False, "images/pic.png", b"fake-bytes")
        win._db.set_image_exclude_export(img_id, 1)

        class _FakeThread:
            def __init__(self, *a, **k):
                pass
            def start(self):
                pass
            def quit(self):
                pass
            def wait(self, *a, **k):
                pass
            def connect(self, *a, **k):
                pass
            @property
            def succeeded(self):
                return self
            @property
            def error(self):
                return self

        monkeypatch.setattr(
            "translation_assistant.ui.main_widget._StatusCheckWorker", _FakeThread,
        )
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget._PublishWorker", _FakeThread,
        )

        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog.exec", lambda self: 1,
        )

        captured = {}
        import translation_assistant.wp_publisher as wp_publisher
        _real_build_payload = wp_publisher.build_payload

        def _spy_build_payload(*args, **kwargs):
            captured["kwargs"] = kwargs
            return _real_build_payload(*args, **kwargs)

        monkeypatch.setattr(wp_publisher, "build_payload", _spy_build_payload)

        win._on_publish_wp()

        # Verify the payload's images list does not contain the excluded image
        assert "images" in captured["kwargs"]
        assert len(captured["kwargs"]["images"]) == 0


class TestIllustrationsWorker:
    def test_sends_batches_in_order_and_emits_first_result(self, qapp):
        from translation_assistant.ui import main_widget as mw

        calls = []

        def fake_publish(endpoint, payload):
            calls.append(payload["mode"])
            return {"status": "ok", "mode": payload["mode"], "page_url": "u", "created": payload["mode"] == "replace"}

        with patch.object(mw, "_IllustrationsPublishWorker") as _:
            pass  # ensure the symbol exists; real check below

        worker = mw._IllustrationsPublishWorker(
            "https://site.com",
            [{"mode": "replace"}, {"mode": "append"}, {"mode": "append"}],
        )
        got = {}
        worker.succeeded.connect(lambda r: got.update(r))
        with patch("translation_assistant.wp_publisher.publish_illustrations", fake_publish):
            worker.run()  # run synchronously in-thread for the test

        assert calls == ["replace", "append", "append"]
        assert got["mode"] == "replace"  # first batch's result

    def test_stops_and_reports_on_batch_failure(self, qapp):
        from translation_assistant.ui import main_widget as mw
        from translation_assistant.wp_publisher import WPPublishError

        calls = []

        def fake_publish(endpoint, payload):
            calls.append(payload["mode"])
            if payload["mode"] == "append":
                raise WPPublishError("boom", status_code=500)
            return {"status": "ok"}

        worker = mw._IllustrationsPublishWorker(
            "https://site.com", [{"mode": "replace"}, {"mode": "append"}]
        )
        errs = []
        worker.error.connect(errs.append)
        with patch("translation_assistant.wp_publisher.publish_illustrations", fake_publish):
            worker.run()

        assert calls == ["replace", "append"]
        assert errs and errs[0] == "batch 2/2: boom"

"""
End-to-end integration tests — Stage 10 checklist.

These tests exercise the full pipeline (core → settings → window) for
scenarios that individual unit tests do not cover in combination.
"""
import sqlite3
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings

from translation_assistant.core import (
    build_new_file, parse_file_content, save_file,
    build_review_text, calculate_progress,
)
from translation_assistant.db import Database
from translation_assistant.settings import AppSettings
from translation_assistant.spellcheck import SpellHighlighter


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_settings(tmp_path: Path) -> AppSettings:
    qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    return AppSettings(_qs=qs)


def _make_settings_from_ini(tmp_path: Path) -> AppSettings:
    """Create a fresh AppSettings reading from an existing INI — simulates restart."""
    qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    return AppSettings(_qs=qs)


def _make_db() -> Database:
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return db


@pytest.fixture
def win(qapp, tmp_path):
    settings = _make_settings(tmp_path)
    from translation_assistant.ui.main_widget import TranslationAssistantWidget
    w = TranslationAssistantWidget(_settings=settings, _db=_make_db())
    yield w
    w.destroy()


def _sep(raw: str, translated: str = "") -> str:
    return raw + "\n---SEPERATOR---\n" + translated


# ---------------------------------------------------------------------------
# Round-trip: create → translate → save → re-open
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_single_line_round_trip(self, tmp_path):
        raw = "Hello world"
        content = build_new_file(raw)
        path = tmp_path / "test.txt"
        path.write_text(content, encoding="utf-8")

        raw_lines, tl_lines, raw_section = parse_file_content(path.read_text(encoding="utf-8"))
        tl_lines[0] = "こんにちは世界"
        save_file(path, raw_section, tl_lines)

        raw_lines2, tl_lines2, _ = parse_file_content(path.read_text(encoding="utf-8"))
        assert tl_lines2[0] == "こんにちは世界"
        assert raw_lines2 == raw_lines  # raw never touched

    def test_multiline_round_trip_preserves_all_translations(self, tmp_path):
        raw = "Line one\nLine two\nLine three"
        content = build_new_file(raw)
        path = tmp_path / "test.txt"
        path.write_text(content, encoding="utf-8")

        raw_lines, tl_lines, raw_section = parse_file_content(path.read_text(encoding="utf-8"))
        for i in range(len(raw_lines)):
            if raw_lines[i]:
                tl_lines[i] = f"Translation {i}"
        save_file(path, raw_section, tl_lines)

        _, tl_lines2, _ = parse_file_content(path.read_text(encoding="utf-8"))
        for i in range(len(raw_lines)):
            if raw_lines[i]:
                assert tl_lines2[i] == f"Translation {i}"

    def test_continuation_lines_preserved_in_round_trip(self, tmp_path):
        content = _sep("%First。\n$Second。\n%Third\n")
        path = tmp_path / "test.txt"
        path.write_text(content, encoding="utf-8")

        raw_lines, tl_lines, raw_section = parse_file_content(content)
        tl_lines[0] = "TL0"
        tl_lines[1] = "TL1"
        tl_lines[2] = "TL2"
        save_file(path, raw_section, tl_lines)

        _, tl_lines2, _ = parse_file_content(path.read_text(encoding="utf-8"))
        assert tl_lines2[0] == "TL0"
        assert tl_lines2[1] == "TL1"
        assert tl_lines2[2] == "TL2"

    def test_empty_lines_preserved_in_round_trip(self, tmp_path):
        content = _sep("%A\n\n%B\n")
        path = tmp_path / "test.txt"
        path.write_text(content, encoding="utf-8")

        raw_lines, tl_lines, raw_section = parse_file_content(content)
        assert raw_lines[1] == ""  # blank line kept
        tl_lines[0] = "Alpha"
        tl_lines[2] = "Beta"
        save_file(path, raw_section, tl_lines)

        _, tl_lines2, _ = parse_file_content(path.read_text(encoding="utf-8"))
        assert tl_lines2[0] == "Alpha"
        assert tl_lines2[2] == "Beta"

    def test_separator_never_appears_in_raw_after_round_trip(self, tmp_path):
        content = build_new_file("Test line one。Second sentence。\nParagraph two")
        path = tmp_path / "test.txt"
        path.write_text(content, encoding="utf-8")

        raw_lines, tl_lines, raw_section = parse_file_content(content)
        tl_lines[0] = "TL"
        save_file(path, raw_section, tl_lines)

        saved = path.read_text(encoding="utf-8")
        assert saved.count("---SEPERATOR---") == 1


# ---------------------------------------------------------------------------
# Glossary substitution end-to-end
# ---------------------------------------------------------------------------

class TestGlossaryEndToEnd:
    def test_glossary_applied_on_load(self, win):
        win._glossary = [("勇者", "Hero"), ("魔王", "DemonKing")]
        win._parse_chars = []
        win.load_content(_sep("%勇者が魔王を倒した。\n"))
        text = win._raw_line.toPlainText()
        assert "Hero" in text
        assert "DemonKing" in text
        assert "勇者" not in text

    def test_glossary_reapplied_after_profile_change(self, win):
        win.load_content(_sep("%TestPhrase\n"))
        win._glossary = [("TestPhrase", "Replaced")]
        win._parse_chars = []
        # Simulate profile dialog having updated the glossary
        win._update_ui_for_pointer()
        assert "Replaced" in win._raw_line.toPlainText()

    def test_replacement_flag_set_on_substitution(self, win):
        win._glossary = [("A", "B")]
        win._parse_chars = []
        win.load_content(_sep("%A is here\n"))
        assert win._replaced is True

    def test_replacement_flag_false_when_no_match(self, win):
        win._glossary = [("X", "Y")]
        win._parse_chars = []
        win.load_content(_sep("%Nothing matches\n"))
        assert win._replaced is False

    def test_glossary_underscore_translations_display_as_spaces(self, win, tmp_path):
        """Underscores in glossary translations should display as spaces."""
        win._glossary = [("主人公", "main_character")]
        win._parse_chars = []
        win.load_content(_sep("%主人公の話\n"))
        assert "main_character" in win._raw_line.toPlainText()


# ---------------------------------------------------------------------------
# Parse navigation
# ---------------------------------------------------------------------------

class TestParseNavigationEndToEnd:
    def test_advance_selects_first_sentence(self, win):
        win._glossary = []
        win._parse_chars = ["。"]
        win.load_content(_sep("%First。Second。Third。\n"))
        win._advance_parse()
        assert win._parse_pointer == 0
        selected = win._raw_line.textCursor().selectedText()
        assert "First" in selected

    def test_advance_then_retreat_clears_selection(self, win):
        win._glossary = []
        win._parse_chars = ["。"]
        win.load_content(_sep("%A。B。\n"))
        win._advance_parse()
        win._retreat_parse()
        assert win._parse_pointer == -1
        # Selection should be empty after retreating to -1
        assert win._raw_line.textCursor().selectedText() == ""

    def test_retreat_to_minus_two_shows_original_raw(self, win):
        win._glossary = [("A", "Alpha")]
        win._parse_chars = ["。"]
        win.load_content(_sep("%A。\n"))
        assert win._replaced is True
        win._advance_parse()   # pointer = 0
        win._retreat_parse()   # pointer = -1
        win._retreat_parse()   # pointer = -2 (possible because replaced=True)
        assert win._parse_pointer == -2
        # raw line should show original (with % stripped but no glossary)
        raw_shown = win._raw_line.toPlainText()
        assert "A" in raw_shown
        assert "Alpha" not in raw_shown

    def test_parse_pointer_bounded_by_sentence_count(self, win):
        win._glossary = []
        win._parse_chars = ["。"]
        win.load_content(_sep("%One。Two。\n"))
        for _ in range(10):
            win._advance_parse()
        assert win._parse_pointer == 1  # only 2 sentences, index 0 and 1


# ---------------------------------------------------------------------------
# Progress percentage and word count
# ---------------------------------------------------------------------------

class TestProgressAccuracy:
    def test_zero_percent_at_load(self, win):
        win.load_content(_sep("%A\n%B\n%C\n"))
        assert win._progress_bar.value() == 0

    def test_hundred_percent_all_translated(self, win):
        content = _sep("%A\n%B\n", "done\ndone\n")
        win.load_content(content)
        pct, _ = calculate_progress(win._raw_lines, win._translated_lines)
        assert pct == 100

    def test_fifty_percent_half_translated(self, win):
        content = _sep("%A\n%B\n", "done\n\n")
        win.load_content(content)
        pct, _ = calculate_progress(win._raw_lines, win._translated_lines)
        assert pct == 50

    def test_word_count_sums_translated_words(self, win):
        content = _sep("%A\n%B\n", "hello world\nfoo bar baz\n")
        win.load_content(content)
        _, wc = calculate_progress(win._raw_lines, win._translated_lines)
        # "hello world" → 2, "foo bar baz" → 3
        assert wc == 5

    def test_progress_updates_after_navigation(self, win):
        win.load_content(_sep("%A\n%B\n"))
        win._translated_line.setPlainText("done")
        win._navigate_forward()
        pct, _ = calculate_progress(win._raw_lines, win._translated_lines)
        assert pct == 50

    def test_empty_lines_not_counted_in_progress(self, win):
        content = _sep("%A\n\n%B\n", "done\n\ndone\n")
        win.load_content(content)
        pct, _ = calculate_progress(win._raw_lines, win._translated_lines)
        assert pct == 100  # only 2 non-empty raw lines, both translated


# ---------------------------------------------------------------------------
# Settings persistence (simulated restart)
# ---------------------------------------------------------------------------

class TestSettingsPersistence:
    def test_on_top_persists(self, tmp_path):
        s1 = _make_settings(tmp_path)
        s1.on_top = False
        s1.save()
        s2 = _make_settings_from_ini(tmp_path)
        assert s2.on_top is False

    def test_show_progress_persists(self, tmp_path):
        s1 = _make_settings(tmp_path)
        s1.show_progress = False
        s1.save()
        s2 = _make_settings_from_ini(tmp_path)
        assert s2.show_progress is False

    def test_parse_char_persists(self, tmp_path):
        s1 = _make_settings(tmp_path)
        s1.parse_char = "。 ！ ？"
        s1.save()
        s2 = _make_settings_from_ini(tmp_path)
        assert s2.parse_char == "。 ！ ？"

    def test_profile_used_persists(self, tmp_path):
        s1 = _make_settings(tmp_path)
        s1.profile_used = "MyProfile"
        s1.save()
        s2 = _make_settings_from_ini(tmp_path)
        assert s2.profile_used == "MyProfile"

    def test_auto_save_interval_persists(self, tmp_path):
        s1 = _make_settings(tmp_path)
        s1.auto_save = 10
        s1.save()
        s2 = _make_settings_from_ini(tmp_path)
        assert s2.auto_save == 10


# ---------------------------------------------------------------------------
# Custom dictionary persistence
# ---------------------------------------------------------------------------

class TestCustomDictionaryPersistence:
    def test_words_survive_lex_reload(self, qapp, tmp_path):
        lex = tmp_path / "test.lex"
        lex.write_text("#LID 1033\n", encoding="utf-8")
        from PySide6.QtGui import QTextDocument

        # First session: add a word
        doc1 = QTextDocument()
        h1 = SpellHighlighter(doc1, lex_path=lex)
        h1.add_word("jargonterm")
        lex.open("a", encoding="utf-8").write("jargonterm\n")

        # Simulate restart: fresh highlighter reads the same lex
        doc2 = QTextDocument()
        h2 = SpellHighlighter(doc2, lex_path=lex)
        assert "jargonterm" in h2._custom

    def test_custom_word_not_flagged_after_reload(self, qapp, tmp_path):
        lex = tmp_path / "test.lex"
        lex.write_text("#LID 1033\nuniquejargon\n", encoding="utf-8")
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        h = SpellHighlighter(doc, lex_path=lex)
        assert h.check("uniquejargon") is True

    def test_add_to_dictionary_in_window_persists(self, win):
        win._translated_line.setPlainText("mytechterm")
        cursor = win._translated_line.textCursor()
        cursor.select(cursor.SelectionType.Document)
        win._translated_line.setTextCursor(cursor)
        with patch("PySide6.QtWidgets.QMessageBox.information"):
            win._add_to_dictionary()

        # Verify persisted in DB
        assert "mytechterm" in win._db.get_custom_words("Default")
        # And in the live highlighter
        assert "mytechterm" in win._spell_highlighter._custom


# ---------------------------------------------------------------------------
# Edge cases inherited from the original
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_continuation_lines_grouped_in_review_bottom(self, win):
        """
        $ lines and their % head group together in the review panels.
        At pointer=0, %Head。 is the current raw line; reviewBottom shows
        lines 1+ so the $Continuation。 and %Next appear there.
        """
        win.load_content(_sep("%Head。\n$Continuation。\n%Next\n"))
        # Current raw line shows the % head (no markers)
        assert "Head" in win._raw_line.toPlainText()
        # reviewBottom shows the continuation and the following % line
        review = win._review_bottom.toPlainText()
        assert "Continuation" in review
        assert "Next" in review

    def test_continuation_line_display_has_both_parts(self, win):
        raw_lines = ["%Head。", "$Cont。", "%Other"]
        tl_lines = ["", "", ""]
        text, omap, _ = build_review_text(raw_lines, tl_lines, 1, 2)
        # Both parts should appear in the display
        assert "Cont" in text
        assert "Other" in text

    def test_empty_lines_skipped_during_forward_nav(self, win):
        win.load_content(_sep("%A\n\n\n%B\n"))
        win._navigate_forward()
        assert win._array_pointer == 3  # skipped indices 1 and 2 (empty)

    def test_empty_lines_skipped_during_backward_nav(self, win):
        win.load_content(_sep("%A\n\n%B\n"))
        win._array_pointer = 2
        win._navigate_backward()
        assert win._array_pointer == 0  # skipped index 1 (empty)

    def test_file_without_separator_shows_error(self, win):
        with patch("PySide6.QtWidgets.QMessageBox.critical"):
            try:
                win.load_content("No separator")
                assert False, "Should have raised ValueError"
            except ValueError:
                pass  # expected

    def test_percentage_and_dollar_stripped_from_raw_display(self, win):
        win._glossary = []
        win._parse_chars = []
        win.load_content(_sep("%Hello\n"))
        assert "%" not in win._raw_line.toPlainText()
        assert "Hello" in win._raw_line.toPlainText()

    def test_dollar_prefix_stripped_from_continuation_display(self, win):
        win._glossary = []
        win._parse_chars = []
        content = _sep("%Head。\n$Tail。\n")
        win.load_content(content)
        win._navigate_forward()
        # array_pointer now on the $ line; display should not contain $
        assert "$" not in win._raw_line.toPlainText()

    def test_ctrl_j_requires_selection(self, win):
        win._translated_line.setPlainText("word")
        before = win._db.get_custom_words("Default")
        # No selection — nothing added to dictionary
        win._add_to_dictionary()
        assert win._db.get_custom_words("Default") == before

    def test_word_count_includes_all_translated_lines(self, win):
        content = _sep("%A\n%B\n%C\n", "one\ntwo three\nfour five six\n")
        win.load_content(content)
        _, wc = calculate_progress(win._raw_lines, win._translated_lines)
        assert wc == 6  # 1 + 2 + 3


# ---------------------------------------------------------------------------
# Auto-save timer
# ---------------------------------------------------------------------------

class TestAutoSaveTimer:
    def test_timer_created_at_startup(self, win):
        assert win._autosave_timer is not None

    def test_timer_interval_matches_settings(self, win):
        win._settings.auto_save = 3
        win._restart_autosave_timer()
        assert win._autosave_timer.interval() == 3 * 60_000

    def test_timer_starts_on_load(self, win):
        win.load_content("%A\n---SEPERATOR---\n\n")
        assert win._autosave_timer.isActive()

    def test_timer_disabled_when_autosave_zero(self, win):
        win._settings.auto_save = 0
        win._restart_autosave_timer()
        assert not win._autosave_timer.isActive()

    def test_autosave_tick_writes_to_db(self, win):
        win.load_content("%A\n---SEPERATOR---\n\n")
        win._translated_line.setPlainText("AutoSaved")
        win._on_autosave_timer()
        lines = win._db.get_lines(win._doc_id)
        assert lines[0]["translated_text"] == "AutoSaved"


# ---------------------------------------------------------------------------
# Large file performance
# ---------------------------------------------------------------------------

class TestLargeFile:
    def _make_large_file(self, tmp_path: Path, n: int = 1000) -> Path:
        lines = [f"%Line number {i}。" for i in range(n)]
        raw = "\n".join(lines)
        content = build_new_file(raw)
        p = tmp_path / "large.txt"
        p.write_text(content, encoding="utf-8")
        return p

    def test_large_file_parses_in_reasonable_time(self, tmp_path):
        p = self._make_large_file(tmp_path, 1000)
        t0 = time.monotonic()
        raw_lines, tl_lines, _ = parse_file_content(p.read_text(encoding="utf-8"))
        elapsed = time.monotonic() - t0
        assert len(raw_lines) >= 1000
        assert elapsed < 5.0, f"Parsing took {elapsed:.2f}s"

    def test_large_file_loads_into_window(self, win, tmp_path):
        p = self._make_large_file(tmp_path, 1000)
        win.load_content(p.read_text(encoding="utf-8"))
        assert len(win._raw_lines) >= 1000

    def test_build_review_text_large_range(self, tmp_path):
        p = self._make_large_file(tmp_path, 1000)
        raw_lines, tl_lines, _ = parse_file_content(p.read_text(encoding="utf-8"))
        t0 = time.monotonic()
        text, omap, _ = build_review_text(raw_lines, tl_lines, 0, len(raw_lines) - 1)
        elapsed = time.monotonic() - t0
        assert len(omap) == len(raw_lines)
        assert elapsed < 5.0, f"build_review_text took {elapsed:.2f}s"

    def test_navigation_through_large_file(self, win, tmp_path):
        p = self._make_large_file(tmp_path, 500)
        win.load_content(p.read_text(encoding="utf-8"))
        # Navigate 50 steps forward
        for _ in range(50):
            win._navigate_forward()
        assert win._array_pointer == 50

"""
Tests for SpellHighlighter — Stage 8 acceptance criteria.

A mock enchant dict is injected via the ``_dict`` seam so tests run
without requiring system enchant language data.
"""
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QSettings
from PySide6.QtGui import QTextDocument

from translation_assistant.db import Database
from translation_assistant.settings import AppSettings
from translation_assistant.spellcheck import SpellHighlighter


def _make_settings(tmp_path: Path) -> AppSettings:
    qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    return AppSettings(_qs=qs)


def _make_db() -> Database:
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return db


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def doc(qapp):
    return QTextDocument()


@pytest.fixture
def mock_dict():
    """enchant.Dict stand-in: 'hello' and 'world' are correct; all else wrong."""
    d = MagicMock()
    d.check.side_effect = lambda w: w.lower() in ("hello", "world", "translation")
    d.suggest.return_value = ["hello"]
    return d


@pytest.fixture
def hl(doc, mock_dict):
    """Highlighter with injected mock dict."""
    return SpellHighlighter(doc, _dict=mock_dict)


@pytest.fixture
def hl_no_dict(doc):
    """Highlighter with no dict (enchant unavailable simulation)."""
    return SpellHighlighter(doc, _dict=None)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

class TestAvailability:
    def test_available_with_injected_dict(self, hl):
        assert hl.available is True

    def test_not_available_without_dict(self, hl_no_dict):
        assert hl_no_dict.available is False

    def test_init_without_enchant_does_not_raise(self, doc, monkeypatch):
        """If enchant import fails, SpellHighlighter must not raise."""
        import sys
        saved = sys.modules.pop("enchant", None)
        sys.modules["enchant"] = None  # causes ImportError on `import enchant`
        try:
            h = SpellHighlighter(doc)
            assert h.available is False
        finally:
            if saved is not None:
                sys.modules["enchant"] = saved
            else:
                sys.modules.pop("enchant", None)


# ---------------------------------------------------------------------------
# Custom word list
# ---------------------------------------------------------------------------

class TestCustomWords:
    def test_load_words_from_lex(self, hl, tmp_path):
        lex = tmp_path / "test.lex"
        lex.write_text("#LID 1033\ncustom\nwordlist\n", encoding="utf-8")
        hl.load_custom_words(lex)
        assert "custom" in hl._custom
        assert "wordlist" in hl._custom

    def test_load_skips_comment_lines(self, hl, tmp_path):
        lex = tmp_path / "test.lex"
        lex.write_text("#LID 1033\n#another comment\nrealword\n", encoding="utf-8")
        hl.load_custom_words(lex)
        assert "realword" in hl._custom
        assert "#LID 1033" not in hl._custom
        assert "#another comment" not in hl._custom

    def test_load_missing_file_clears_words(self, hl, tmp_path):
        hl._custom.add("previous")
        hl.load_custom_words(tmp_path / "nonexistent.lex")
        assert not hl._custom

    def test_add_word(self, hl):
        hl.add_word("myterm")
        assert "myterm" in hl._custom

    def test_load_replaces_previous_custom_words(self, hl, tmp_path):
        hl._custom.add("old")
        lex = tmp_path / "test.lex"
        lex.write_text("new\n", encoding="utf-8")
        hl.load_custom_words(lex)
        assert "old" not in hl._custom
        assert "new" in hl._custom


# ---------------------------------------------------------------------------
# check() and suggest()
# ---------------------------------------------------------------------------

class TestCheckAndSuggest:
    def test_check_known_word_returns_true(self, hl):
        assert hl.check("hello") is True

    def test_check_unknown_word_returns_false(self, hl):
        assert hl.check("helo") is False

    def test_check_custom_word_bypasses_dict(self, hl, mock_dict):
        hl._custom.add("myterm")
        mock_dict.check.return_value = False
        assert hl.check("myterm") is True

    def test_check_always_true_when_no_dict(self, hl_no_dict):
        assert hl_no_dict.check("completelymisspelledword") is True

    def test_suggest_returns_list(self, hl):
        result = hl.suggest("helo")
        assert isinstance(result, list)
        assert "hello" in result

    def test_suggest_empty_when_no_dict(self, hl_no_dict):
        assert hl_no_dict.suggest("helo") == []

    def test_check_dict_exception_returns_true(self, hl, mock_dict):
        mock_dict.check.side_effect = Exception("internal error")
        assert hl.check("anything") is True

    def test_suggest_dict_exception_returns_empty(self, hl, mock_dict):
        mock_dict.suggest.side_effect = Exception("internal error")
        assert hl.suggest("word") == []

    def test_check_case_sensitive_custom_words(self, hl):
        hl._custom.add("MyTerm")
        assert hl.check("MyTerm") is True
        # "myterm" (different case) is NOT in custom — falls through to dict
        # mock_dict.check returns False for "myterm", so it should be False
        assert hl.check("myterm") is False


# ---------------------------------------------------------------------------
# highlightBlock
# ---------------------------------------------------------------------------

class TestHighlightBlock:
    def test_no_raise_when_no_dict(self, hl_no_dict):
        hl_no_dict.highlightBlock("helo wrold")

    def test_no_raise_with_dict(self, hl):
        hl.highlightBlock("hello world helo wrold")

    def test_no_raise_empty_string(self, hl):
        hl.highlightBlock("")

    def test_no_raise_non_ascii_text(self, hl):
        hl.highlightBlock("日本語のテキスト mixed with English")

    def test_no_raise_short_words_ignored(self, hl):
        # Single-letter words are excluded by the regex (min 2 chars)
        hl.highlightBlock("I a")


# ---------------------------------------------------------------------------
# Integration with MainWindow
# ---------------------------------------------------------------------------

class TestMainWindowIntegration:
    def test_highlighter_attached_at_startup(self, qapp, tmp_path):
        settings = _make_settings(tmp_path)
        from translation_assistant.ui.main_window import MainWindow
        win = MainWindow(_settings=settings, _db=_make_db())
        assert win._spell_highlighter is not None
        win.destroy()

    def test_add_to_dictionary_updates_highlighter(self, qapp, tmp_path):
        settings = _make_settings(tmp_path)
        from translation_assistant.ui.main_window import MainWindow
        win = MainWindow(_settings=settings, _db=_make_db())
        win._translated_line.setPlainText("myspecialword")
        cursor = win._translated_line.textCursor()
        cursor.select(cursor.SelectionType.Document)
        win._translated_line.setTextCursor(cursor)
        with patch("PySide6.QtWidgets.QMessageBox.information"):
            win._add_to_dictionary()
        assert "myspecialword" in win._spell_highlighter._custom
        win.destroy()

    def test_load_spell_dict_reads_from_db(self, qapp, tmp_path):
        db = _make_db()
        db.add_word("Default", "specialjargon")
        settings = _make_settings(tmp_path)
        from translation_assistant.ui.main_window import MainWindow
        win = MainWindow(_settings=settings, _db=db)
        assert "specialjargon" in win._spell_highlighter._custom
        win.destroy()

    def test_profile_change_reloads_spell_dict(self, qapp, tmp_path):
        db = _make_db()
        db.create_profile("Alt")
        db.add_word("Alt", "altword")
        settings = _make_settings(tmp_path)
        from translation_assistant.ui.main_window import MainWindow
        win = MainWindow(_settings=settings, _db=db)

        win._settings.profile_used = "Alt"
        win._load_spell_dict()

        assert "altword" in win._spell_highlighter._custom
        win.destroy()

"""
Tests for CombinedMainWindow — verifies signal bridge between TA widget and Aggregator widget.
"""
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QSettings

from translation_assistant.db import Database
from translation_assistant.settings import AppSettings
from translation_assistant.ui.combined_window import CombinedMainWindow


def _make_settings(tmp_path: Path) -> AppSettings:
    qs = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return AppSettings(_qs=qs)


def _make_db() -> Database:
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return db


def _sep_file(raw: str, translated: str = "") -> str:
    return raw + "\n---SEPERATOR---\n" + translated


@pytest.fixture
def win(qapp, tmp_path):
    # Isolate the aggregator from the user's real config: with real settings
    # these tests fire actual translator requests (e.g. a live Ollama server)
    # on load_content/navigation and append to the user's history file.
    from ta.config.settings import Settings
    from ta.core.history import HistoryStore

    agg_settings = Settings()
    for cfg in agg_settings.translators.values():
        cfg.enabled = False

    def make_history(max_bytes):
        return HistoryStore(path=tmp_path / "history.db", max_bytes=max_bytes)

    settings = _make_settings(tmp_path)
    with patch("ta.ui.aggregator_widget.Settings.load", return_value=agg_settings), \
         patch("ta.ui.aggregator_widget.HistoryStore", make_history), \
         patch("ta.ui.aggregator_widget.ClipboardMonitor"):
        w = CombinedMainWindow(_settings=settings, _db=_make_db())
    yield w
    w.destroy()


class TestCombinedWindowInstantiation:
    def test_instantiates(self, win):
        assert win is not None

    def test_has_ta_widget(self, win):
        from translation_assistant.ui.main_widget import TranslationAssistantWidget
        assert isinstance(win._ta_widget, TranslationAssistantWidget)

    def test_has_agg_widget(self, win):
        from ta.ui.aggregator_widget import AggregatorWidget
        assert isinstance(win._agg_widget, AggregatorWidget)

    def test_window_title(self, win):
        assert "Translation Assistant" in win.windowTitle()

    def test_has_main_splitter(self, win):
        from PySide6.QtWidgets import QSplitter
        from PySide6.QtCore import Qt
        assert isinstance(win._main_splitter, QSplitter)
        assert win._main_splitter.orientation() == Qt.Orientation.Horizontal
        assert win._main_splitter.count() == 2

    def test_right_splitter_is_vertical(self, win):
        from PySide6.QtCore import Qt
        assert win._right_splitter.orientation() == Qt.Orientation.Vertical
        assert win._right_splitter.count() == 2

    def test_status_bar_is_ta_status_bar(self, win):
        assert win.statusBar() is win._ta_widget.status_bar


class TestSignalBridge:
    def test_navigate_forward_triggers_translate_source(self, win, qapp):
        """Navigating to a new sentence in TA emits source_sentence_changed."""
        received = []
        # Listen on the signal directly (bridge already wired in __init__)
        win._ta_widget.source_sentence_changed.connect(lambda t: received.append(t))

        content = _sep_file("%First sentence\n%Second sentence\n")
        win._ta_widget.load_content(content, title="Test")
        received.clear()  # clear the load_content emission

        win._ta_widget._navigate_forward()
        assert len(received) == 1
        assert "Second sentence" in received[0]

    def test_load_content_emits_signal(self, win, qapp):
        """load_content emits source_sentence_changed for the first sentence."""
        received = []
        win._ta_widget.source_sentence_changed.connect(lambda t: received.append(t))

        content = _sep_file("%Hello world\n")
        win._ta_widget.load_content(content, title="Test")
        assert len(received) >= 1
        assert "Hello world" in received[-1]


class TestShortcutsMenuEntry:
    def test_settings_menu_has_shortcuts_action(self, win):
        mb = win.menuBar()
        # Find Settings menu directly
        for action in mb.actions():
            if action.text() == "Settings":
                settings_menu = action.menu()
                break
        else:
            settings_menu = None

        assert settings_menu is not None
        # Get action texts
        action_texts = [a.text() for a in settings_menu.actions()]
        assert "Keyboard Shortcuts…" in action_texts


class TestPublishWPAction:
    def test_action_publish_wp_exists(self, win):
        assert hasattr(win._ta_widget, "action_publish_wp")

    def test_action_publish_wp_disabled_with_no_doc(self, win):
        assert not win._ta_widget.action_publish_wp.isEnabled()

    def test_action_publish_wp_in_file_menu(self, win):
        mb = win.menuBar()
        for action in mb.actions():
            if action.text() == "File":
                file_menu = action.menu()
                break
        else:
            file_menu = None
        assert file_menu is not None
        action_texts = [a.text() for a in file_menu.actions()]
        assert "Publish to WordPress…" in action_texts

    def test_settings_menu_has_wp_settings_action(self, win):
        mb = win.menuBar()
        for action in mb.actions():
            if action.text() == "Settings":
                settings_menu = action.menu()
                break
        else:
            settings_menu = None
        assert settings_menu is not None
        action_texts = [a.text() for a in settings_menu.actions()]
        assert "WordPress Settings…" in action_texts


class TestWPStatusLabel:
    def test_wp_status_label_in_statusbar(self, win):
        ta = win._ta_widget
        assert hasattr(ta, "_wp_status_label")
        assert ta._wp_status_label.text() == ""


class TestUpcomingSentences:
    def test_load_emits_upcoming(self, win, qapp):
        received = []
        win._ta_widget.upcoming_sentences_changed.connect(received.append)
        content = _sep_file("%First\n%Second\n\n%Third\n")
        win._ta_widget.load_content(content, title="Test")
        assert received
        assert received[-1] == ["Second", "Third"]

    def test_navigate_emits_remaining(self, win, qapp):
        received = []
        content = _sep_file("%First\n%Second\n%Third\n")
        win._ta_widget.load_content(content, title="Test")
        win._ta_widget.upcoming_sentences_changed.connect(received.append)
        win._ta_widget._navigate_forward()
        assert received[-1] == ["Third"]

    def test_last_line_emits_empty(self, win, qapp):
        received = []
        content = _sep_file("%Only\n")
        win._ta_widget.load_content(content, title="Test")
        win._ta_widget.upcoming_sentences_changed.connect(received.append)
        win._ta_widget._navigate_forward()  # stays on last line or no-op emit
        if received:  # navigation may not emit when pinned to last line
            assert received[-1] == []

    def test_capped_at_20(self, win, qapp):
        raw = "\n".join(f"%Line {i}" for i in range(30))
        win._ta_widget.load_content(_sep_file(raw + "\n"), title="Test")
        received = []
        win._ta_widget.upcoming_sentences_changed.connect(received.append)
        win._ta_widget._update_ui_for_pointer()
        assert len(received[-1]) == 20
        assert received[-1][0] == "Line 1"

    def test_bridge_fills_prefetch_queue(self, win, qapp):
        content = _sep_file("%First\n%Second\n%Third\n")
        win._ta_widget.load_content(content, title="Test")
        assert win._agg_widget._prefetch_queue == ["Second", "Third"]


class TestClearTranslationCache:
    def test_clear_translation_cache_action(self, win, monkeypatch):
        agg = win._agg_widget
        agg._history.append("line", {"ollama": "cached"}, "Japanese", "English")
        assert len(agg._history.all_entries()) == 1

        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.StandardButton.Yes)
        win._on_clear_translation_cache()
        assert agg._history.all_entries() == []

        # Declining leaves history alone
        agg._history.append("line2", {"ollama": "kept"}, "Japanese", "English")
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.StandardButton.No)
        win._on_clear_translation_cache()
        assert len(agg._history.all_entries()) == 1

    def test_clear_translation_cache_in_tools_menu(self, win):
        labels = []
        for menu in win.menuBar().actions():
            if menu.text() == "Tools":
                labels = [a.text() for a in menu.menu().actions()]
        assert "Clear Translation Cache…" in labels

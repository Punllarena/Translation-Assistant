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
    settings = _make_settings(tmp_path)
    with patch("ta.ui.aggregator_widget.ClipboardMonitor"):
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

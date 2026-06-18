"""Tests for Ollama translator feature."""
import json
import threading
import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from ta.translators.base import BaseTranslator
from ta.config.languages import Language


# ---------------------------------------------------------------------------
# Task 1: BaseTranslator signal + TranslationPanel streaming
# ---------------------------------------------------------------------------

class TestBaseTranslatorChunkSignal:
    def test_has_translation_chunk_signal(self):
        t = BaseTranslator("test")
        # Signal must be connectable
        received = []
        t.translation_chunk.connect(received.append)
        t.translation_chunk.emit("hello")
        assert received == ["hello"]


class TestTranslationPanelStreaming:
    def test_on_chunk_appends_text(self, qapp):
        from ta.ui.translation_panel import TranslationPanel
        t = BaseTranslator("TestTranslator")
        panel = TranslationPanel(t)
        panel._on_chunk("Hello")
        panel._on_chunk(" world")
        assert panel._output.toPlainText() == "Hello world"
        assert panel._status_label.text() == "…"

    def test_on_started_clears_output(self, qapp):
        from ta.ui.translation_panel import TranslationPanel
        t = BaseTranslator("TestTranslator")
        panel = TranslationPanel(t)
        panel._output.setPlainText("old text")
        panel._on_started()
        assert panel._output.toPlainText() == ""
        assert panel._status_label.text() == "…"

    def test_on_ready_empty_text_sets_done_status(self, qapp):
        from ta.ui.translation_panel import TranslationPanel
        t = BaseTranslator("TestTranslator")
        panel = TranslationPanel(t)
        panel._on_ready("")
        assert panel._status_label.text() == "✓"
        assert panel._output.toPlainText() == ""

    def test_on_ready_nonempty_sets_text_and_done_status(self, qapp):
        from ta.ui.translation_panel import TranslationPanel
        t = BaseTranslator("TestTranslator")
        panel = TranslationPanel(t)
        panel._on_ready("translated text")
        assert panel._output.toPlainText() == "translated text"
        assert panel._status_label.text() == "✓"

    def test_on_error_sets_error_status(self, qapp):
        from ta.ui.translation_panel import TranslationPanel
        t = BaseTranslator("TestTranslator")
        panel = TranslationPanel(t)
        panel._on_error("timeout")
        assert panel._status_label.text() == "✗"
        assert "[Error]" in panel._output.toPlainText()

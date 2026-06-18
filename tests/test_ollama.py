"""Tests for Ollama translator feature."""
import json
import threading
import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
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


# ---------------------------------------------------------------------------
# Task 2: Settings — model and system_prompt fields
# ---------------------------------------------------------------------------

class TestSettingsOllamaExtensions:
    def test_translator_config_has_model_field(self):
        from ta.config.settings import TranslatorConfig
        cfg = TranslatorConfig(model="llama3")
        assert cfg.model == "llama3"

    def test_translator_config_has_system_prompt_field(self):
        from ta.config.settings import TranslatorConfig
        cfg = TranslatorConfig(system_prompt="my prompt")
        assert cfg.system_prompt == "my prompt"

    def test_ollama_in_default_translators(self):
        from ta.config.settings import Settings
        s = Settings()
        assert "ollama" in s.translators
        cfg = s.translators["ollama"]
        assert cfg.url == "http://pun-ln01:8101"
        assert "{src}" in cfg.system_prompt
        assert "{dst}" in cfg.system_prompt

    def test_ollama_in_default_layout_panels(self):
        from ta.config.settings import Settings
        s = Settings()
        assert "ollama" in s.layout_panels

    def test_round_trip_model_and_system_prompt(self, tmp_path):
        from ta.config.settings import Settings, TranslatorConfig
        s = Settings()
        s.translators["ollama"] = TranslatorConfig(
            enabled=True,
            url="http://test:8080",
            model="qwen2:latest",
            system_prompt="Translate {src} to {dst}.",
        )
        path = tmp_path / "settings.toml"
        s.save(path)
        s2 = Settings.load(path)
        cfg2 = s2.translators["ollama"]
        assert cfg2.enabled is True
        assert cfg2.url == "http://test:8080"
        assert cfg2.model == "qwen2:latest"
        assert cfg2.system_prompt == "Translate {src} to {dst}."

    def test_round_trip_multiline_system_prompt(self, tmp_path):
        from ta.config.settings import Settings, TranslatorConfig
        s = Settings()
        s.translators["ollama"] = TranslatorConfig(
            model="llama3",
            system_prompt="Line one.\nLine two.\nLine three.",
        )
        path = tmp_path / "settings.toml"
        s.save(path)
        s2 = Settings.load(path)
        assert s2.translators["ollama"].system_prompt == "Line one.\nLine two.\nLine three."

    def test_default_ollama_system_prompt_constant_exported(self):
        from ta.config.settings import DEFAULT_OLLAMA_SYSTEM_PROMPT
        assert "{src}" in DEFAULT_OLLAMA_SYSTEM_PROMPT
        assert "{dst}" in DEFAULT_OLLAMA_SYSTEM_PROMPT

    def test_existing_translator_config_unaffected(self):
        """Existing translators load fine without model/system_prompt in TOML."""
        from ta.config.settings import Settings, TranslatorConfig
        import tempfile, pathlib
        toml = "[translators.deepl]\nenabled = true\napi_key = \"abc\"\n"
        with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
            f.write(toml)
            p = pathlib.Path(f.name)
        s = Settings.load(p)
        p.unlink()
        cfg = s.translators.get("deepl")
        assert cfg is not None
        assert cfg.enabled is True
        assert cfg.model == ""
        assert cfg.system_prompt == ""


# ---------------------------------------------------------------------------
# Task 3: OllamaTranslator
# ---------------------------------------------------------------------------

class TestOllamaTranslator:
    def _make_fake_stream(self, tokens):
        """Return a context manager factory that yields fake NDJSON chunks."""
        @contextmanager
        def fake_stream(*args, **kwargs):
            class FakeResp:
                def raise_for_status(self): pass
                def iter_lines(self_inner):
                    for tok in tokens:
                        yield json.dumps({"message": {"content": tok}, "done": False})
                    yield json.dumps({"done": True})
            yield FakeResp()
        return fake_stream

    def test_emits_chunks_and_ready(self, qapp):
        from ta.translators.ollama import OllamaTranslator
        chunks = []
        done = threading.Event()
        t = OllamaTranslator("http://test:11434", "llama3", "Translate {src} to {dst}:")
        t.translation_chunk.connect(chunks.append, Qt.ConnectionType.DirectConnection)
        t.translation_ready.connect(lambda _: done.set(), Qt.ConnectionType.DirectConnection)

        with patch("ta.translators.ollama.httpx.stream",
                   self._make_fake_stream(["Hello", " world"])):
            t.translate("こんにちは", Language.Japanese, Language.English)
            assert done.wait(timeout=3.0), "translation_ready never fired"

        assert chunks == ["Hello", " world"]

    def test_ready_signal_value_is_empty_string(self, qapp):
        from ta.translators.ollama import OllamaTranslator
        ready_values = []
        done = threading.Event()
        t = OllamaTranslator("http://test:11434", "llama3", "")
        t.translation_ready.connect(
            lambda v: (ready_values.append(v), done.set()),
            Qt.ConnectionType.DirectConnection,
        )

        with patch("ta.translators.ollama.httpx.stream",
                   self._make_fake_stream(["ok"])):
            t.translate("test", Language.Japanese, Language.English)
            done.wait(timeout=3.0)

        assert ready_values == [""]

    def test_emits_error_on_exception(self, qapp):
        from ta.translators.ollama import OllamaTranslator
        errors = []
        done = threading.Event()
        t = OllamaTranslator("http://test:11434", "llama3", "")
        t.translation_error.connect(
            lambda e: (errors.append(e), done.set()),
            Qt.ConnectionType.DirectConnection,
        )

        def raise_connection_error(*args, **kwargs):
            raise Exception("connection refused")

        with patch("ta.translators.ollama.httpx.stream", raise_connection_error):
            t.translate("test", Language.Japanese, Language.English)
            done.wait(timeout=3.0)

        assert len(errors) == 1
        assert "connection refused" in errors[0]

    def test_system_prompt_substitution(self, qapp):
        """Verify {src}/{dst} are replaced with language display names."""
        from ta.translators.ollama import OllamaTranslator
        captured_payload = {}
        done = threading.Event()

        @contextmanager
        def capture_stream(*args, **kwargs):
            captured_payload.update(kwargs.get("json", {}))

            class FakeResp:
                def raise_for_status(self): pass
                def iter_lines(self_inner):
                    yield json.dumps({"done": True})
            yield FakeResp()
            done.set()

        t = OllamaTranslator(
            "http://test:11434", "llama3",
            "You are a {src} to {dst} translator."
        )
        t.translation_ready.connect(lambda _: None, Qt.ConnectionType.DirectConnection)

        with patch("ta.translators.ollama.httpx.stream", capture_stream):
            t.translate("text", Language.Japanese, Language.English)
            done.wait(timeout=3.0)

        sys_msg = captured_payload["messages"][0]["content"]
        assert "Japanese" in sys_msg
        assert "English" in sys_msg
        assert "{src}" not in sys_msg
        assert "{dst}" not in sys_msg

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
        assert cfg.url == "http://localhost:11434"
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

    def test_http_error_includes_server_error_body(self, qapp):
        """A 500 response must surface Ollama's JSON error detail, not just the status."""
        import httpx
        from ta.translators.ollama import OllamaTranslator
        errors = []
        done = threading.Event()
        t = OllamaTranslator("http://test:11434", "llama3", "")
        t.translation_error.connect(
            lambda e: (errors.append(e), done.set()),
            Qt.ConnectionType.DirectConnection,
        )

        @contextmanager
        def fake_500_stream(*args, **kwargs):
            class FakeResp:
                status_code = 500

                def raise_for_status(self_inner):
                    raise httpx.HTTPStatusError(
                        "Server error '500 Internal Server Error'",
                        request=httpx.Request("POST", "http://test:11434/api/chat"),
                        response=httpx.Response(500),
                    )

                def read(self_inner):
                    pass

                def json(self_inner):
                    return {"error": "model requires more system memory"}
            yield FakeResp()

        with patch("ta.translators.ollama.httpx.stream", fake_500_stream):
            t.translate("test", Language.Japanese, Language.English)
            done.wait(timeout=3.0)

        assert len(errors) == 1
        assert "model requires more system memory" in errors[0]

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


class TestBaseTranslatorCancelReset:
    def test_translate_after_halt_clears_cancel(self):
        """A halt() must not silently drop the next queued request."""
        t = BaseTranslator("test")
        t.halt()
        assert t._cancel is True
        t._running = True  # simulate worker thread still winding down
        t.translate("x", Language.Japanese, Language.English)
        assert t._cancel is False
        assert t._pending == ("x", Language.Japanese, Language.English)


class TestOllamaSupersededStream:
    def test_superseded_stream_aborts_without_ready(self, qapp):
        """A newer pending request aborts the current stream mid-flight."""
        from ta.translators.ollama import OllamaTranslator
        chunks = []
        readies = []
        done = threading.Event()
        t = OllamaTranslator("http://test:11434", "llama3", "")
        t.translation_chunk.connect(chunks.append, Qt.ConnectionType.DirectConnection)
        t.translation_ready.connect(
            lambda v: (readies.append(v), done.set()),
            Qt.ConnectionType.DirectConnection,
        )

        calls = []

        @contextmanager
        def fake_stream(*args, **kwargs):
            calls.append(kwargs["json"]["messages"][1]["content"])
            first = len(calls) == 1

            class FakeResp:
                def raise_for_status(self): pass
                def iter_lines(self_inner):
                    yield json.dumps({"message": {"content": "A"}, "done": False})
                    if first:
                        # Queue a newer request mid-stream.
                        with t._lock:
                            t._pending = ("second", Language.Japanese, Language.English)
                    yield json.dumps({"message": {"content": "B"}, "done": False})
                    yield json.dumps({"done": True})
            yield FakeResp()

        with patch("ta.translators.ollama.httpx.stream", fake_stream):
            t.translate("first", Language.Japanese, Language.English)
            assert done.wait(timeout=3.0), "translation_ready never fired"

        assert calls == ["first", "second"]
        # First stream aborted after "A"; only the second ran to completion.
        assert chunks == ["A", "A", "B"]
        assert readies == [""]


class TestTranslationPanelShowResult:
    def test_show_result_displays_text_and_sets_key(self, qapp):
        from ta.ui.translation_panel import TranslationPanel
        t = BaseTranslator("Ollama")
        panel = TranslationPanel(t)
        panel.show_result("cached!", "源文", Language.Japanese, Language.English)
        assert panel._output.toPlainText() == "cached!"
        assert panel._status_label.text() == "✓ cached"
        assert panel.request_key() == ("源文", Language.Japanese, Language.English)

    def test_show_result_hides_stale_thinking_trace(self, qapp):
        from ta.ui.translation_panel import TranslationPanel
        t = BaseTranslator("Ollama")
        panel = TranslationPanel(t)
        panel._on_thinking("old trace")
        panel.show_result("cached!", "源文", Language.Japanese, Language.English)
        assert panel._thinking_toggle.isHidden()
        assert panel._thinking_box.toPlainText() == ""

    def test_thinking_reshown_after_interrupted_stream(self, qapp):
        """Navigating mid-thinking restarts the stream; the new trace must render."""
        from ta.ui.translation_panel import TranslationPanel
        t = BaseTranslator("Ollama")
        panel = TranslationPanel(t)
        panel._on_started()
        panel._on_thinking("first line")
        # User navigates: stream restarts before any answer token arrived.
        panel._on_started()
        panel._on_thinking("second trace")
        assert not panel._thinking_toggle.isHidden()
        assert panel._thinking_toggle.isChecked()
        assert not panel._thinking_box.isHidden()
        assert panel._thinking_box.toPlainText() == "second trace"

    def test_show_result_respects_disabled_checkbox(self, qapp):
        from ta.ui.translation_panel import TranslationPanel
        t = BaseTranslator("Ollama")
        panel = TranslationPanel(t)
        panel._enable_cb.setChecked(False)
        panel.show_result("cached!", "源文", Language.Japanese, Language.English)
        assert panel._output.toPlainText() == ""


class TestThinkingTakeover:
    def _panel(self):
        from ta.ui.translation_panel import TranslationPanel
        return TranslationPanel(BaseTranslator("Ollama"))

    def test_thinking_takes_over_panel_while_streaming(self, qapp):
        panel = self._panel()
        panel._on_started()
        panel._on_thinking("hmm")
        assert panel._output.isHidden()
        # Box must be free to grow, not pinned at the collapsed 80px.
        assert panel._thinking_box.maximumHeight() > 80

    def test_first_chunk_collapses_thinking_and_restores_output(self, qapp):
        panel = self._panel()
        panel._on_started()
        panel._on_thinking("hmm")
        panel._on_chunk("Hello")
        assert not panel._output.isHidden()
        assert not panel._thinking_toggle.isChecked()
        assert panel._thinking_box.isHidden()
        assert panel._output.toPlainText() == "Hello"

    def test_ready_without_chunks_restores_output(self, qapp):
        panel = self._panel()
        panel._on_started()
        panel._on_thinking("hmm")
        panel._on_ready("done")
        assert not panel._output.isHidden()
        assert panel._output.toPlainText() == "done"

    def test_error_restores_output(self, qapp):
        panel = self._panel()
        panel._on_started()
        panel._on_thinking("hmm")
        panel._on_error("boom")
        assert not panel._output.isHidden()

    def test_restart_mid_takeover_restores_output_layout(self, qapp):
        panel = self._panel()
        panel._on_started()
        panel._on_thinking("hmm")
        panel._on_started()
        assert not panel._output.isHidden()
        assert panel._thinking_box.isHidden()

    def test_manual_expand_after_done_uses_collapsed_height(self, qapp):
        panel = self._panel()
        panel._on_started()
        panel._on_thinking("hmm")
        panel._on_chunk("Hello")
        panel._thinking_toggle.setChecked(True)
        assert not panel._thinking_box.isHidden()
        assert panel._thinking_box.maximumHeight() == 80
        assert not panel._output.isHidden()


class TestOllamaStats:
    def test_done_object_emits_stats(self, qapp):
        from ta.translators.ollama import OllamaTranslator
        stats = []
        done = threading.Event()
        t = OllamaTranslator("http://test:11434", "llama3", "")
        t.translation_stats.connect(stats.append, Qt.ConnectionType.DirectConnection)
        t.translation_ready.connect(lambda _: done.set(), Qt.ConnectionType.DirectConnection)

        @contextmanager
        def fake_stream(*args, **kwargs):
            class FakeResp:
                def raise_for_status(self): pass
                def iter_lines(self_inner):
                    yield json.dumps({"message": {"content": "ok"}, "done": False})
                    yield json.dumps({
                        "done": True,
                        "prompt_eval_count": 45,
                        "eval_count": 210,
                        "eval_duration": 7_000_000_000,
                        "total_duration": 8_200_000_000,
                    })
            yield FakeResp()

        with patch("ta.translators.ollama.httpx.stream", fake_stream):
            t.translate("test", Language.Japanese, Language.English)
            assert done.wait(timeout=3.0)

        assert stats == [{
            "prompt_eval_count": 45,
            "eval_count": 210,
            "eval_duration": 7_000_000_000,
            "total_duration": 8_200_000_000,
        }]

    def test_panel_shows_stats_in_status(self, qapp):
        from ta.ui.translation_panel import TranslationPanel
        t = BaseTranslator("Ollama")
        panel = TranslationPanel(t)
        panel._on_started()
        panel._on_stats({
            "prompt_eval_count": 45,
            "eval_count": 210,
            "eval_duration": 7_000_000_000,
            "total_duration": 8_200_000_000,
        })
        panel._on_ready("")
        assert panel._status_label.text() == "✓ 45 in · 210 out · 8.2s · 30 tok/s"
        assert "Prompt: 45 tokens" in panel._status_label.toolTip()
        assert "Output: 210 tokens" in panel._status_label.toolTip()

    def test_duration_over_a_minute_humanized(self, qapp):
        from ta.ui.translation_panel import _fmt_duration
        assert _fmt_duration(8.24) == "8.2s"
        assert _fmt_duration(72.6) == "1m 13s"
        assert _fmt_duration(60) == "1m 00s"

    def test_panel_status_plain_check_without_stats(self, qapp):
        from ta.ui.translation_panel import TranslationPanel
        t = BaseTranslator("Ollama")
        panel = TranslationPanel(t)
        panel._on_started()
        panel._on_ready("done")
        assert panel._status_label.text() == "✓"


class TestAggregatorOllamaCache:
    def _make_widget(self, qapp, tmp_path):
        from ta.config.settings import Settings, TranslatorConfig
        from ta.core.history import HistoryStore

        s = Settings()
        for cfg in s.translators.values():
            cfg.enabled = False
        s.translators["ollama"] = TranslatorConfig(
            enabled=True, url="http://test:1", model="m", system_prompt="p",
        )
        s.layout_panels = ["ollama"]
        s.enable_substitutions = False

        def make_history(max_bytes):
            return HistoryStore(path=tmp_path / "history.jsonl", max_bytes=max_bytes)

        with patch("ta.ui.aggregator_widget.Settings.load", return_value=s), \
             patch("ta.ui.aggregator_widget.HistoryStore", make_history), \
             patch("ta.ui.aggregator_widget.ClipboardMonitor"):
            from ta.ui.aggregator_widget import AggregatorWidget
            return AggregatorWidget()

    def test_cache_hit_skips_translator_and_debounce(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        calls = []
        w._ollama_translator.translate = lambda *a: calls.append(a)
        text = w._preprocess("hello line")
        src = w._source_panel.src_language()
        dst = w._source_panel.dst_language()
        w._mt_cache[(text, src, dst)] = "cached!"

        w.translate_source("hello line")

        assert w._ollama_panel._output.toPlainText() == "cached!"
        assert not w._ollama_debounce.isActive()
        assert calls == []

    def test_cache_miss_debounces_then_fires(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        calls = []
        w._ollama_translator.translate = lambda *a: calls.append(a)

        w.translate_source("new line")

        assert w._ollama_debounce.isActive()
        assert calls == []  # nothing sent until the debounce fires
        w._ollama_debounce.stop()
        w._fire_ollama()
        assert len(calls) == 1
        assert calls[0][0] == w._current_source

    def test_ready_caches_result_and_records_history(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        calls = []
        w._ollama_translator.translate = lambda *a: calls.append(a)
        w.translate_source("some line")
        w._ollama_debounce.stop()
        w._fire_ollama()

        w._ollama_chunks[:] = ["Hello", " world"]
        w._on_ollama_ready("")

        key = w._ollama_panel.request_key()
        assert w._mt_cache[key] == "Hello world"
        assert w._pending_translations["ollama"] == "Hello world"
        assert any(
            e.translations.get("ollama") == "Hello world"
            for e in w._history.all_entries()
        )

    def test_ready_toasts_when_window_inactive(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        messages = []
        with patch.object(w, "window") as win, \
             patch("ta.ui.aggregator_widget.QSystemTrayIcon") as tray_cls:
            win.return_value.isActiveWindow.return_value = False
            tray_cls.isSystemTrayAvailable.return_value = True
            tray_cls.return_value.showMessage = (
                lambda title, body, *a: messages.append((title, body))
            )
            w._ollama_chunks[:] = ["Hello world"]
            w._on_ollama_ready("")
        assert messages == [("Ollama translation ready", "Hello world")]

    def test_ready_no_toast_when_window_active(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        with patch.object(w, "window") as win, \
             patch("ta.ui.aggregator_widget.QSystemTrayIcon") as tray_cls:
            win.return_value.isActiveWindow.return_value = True
            w._ollama_chunks[:] = ["Hello world"]
            w._on_ollama_ready("")
        tray_cls.return_value.showMessage.assert_not_called()
        assert w._tray is None

    def test_seed_cache_from_history(self, qapp, tmp_path):
        from ta.core.history import HistoryStore
        store = HistoryStore(path=tmp_path / "history.jsonl")
        store.append("古い行", {"ollama": "old line"})

        w = self._make_widget(qapp, tmp_path)
        src = w._source_panel.src_language()
        dst = w._source_panel.dst_language()
        assert w._mt_cache[("古い行", src, dst)] == "old line"


# ---------------------------------------------------------------------------
# Task 4: Aggregator factory + SettingsDialog Ollama group
# ---------------------------------------------------------------------------

class TestBuildTranslatorOllama:
    def test_build_translator_returns_ollama(self):
        from ta.ui.aggregator_widget import _build_translator
        from ta.config.settings import TranslatorConfig
        from ta.translators.ollama import OllamaTranslator
        cfg = TranslatorConfig(
            enabled=True,
            url="http://test:8101",
            model="llama3",
            system_prompt="prompt",
        )
        t = _build_translator("ollama", cfg)
        assert isinstance(t, OllamaTranslator)

    def test_build_translator_ollama_uses_cfg_url(self):
        from ta.ui.aggregator_widget import _build_translator
        from ta.config.settings import TranslatorConfig
        from ta.translators.ollama import OllamaTranslator
        cfg = TranslatorConfig(url="http://custom:9999", model="m", system_prompt="")
        t = _build_translator("ollama", cfg)
        assert t._url == "http://custom:9999"


class TestSettingsDialogOllamaGroup:
    def _make_settings(self):
        from ta.config.settings import Settings, TranslatorConfig, DEFAULT_OLLAMA_SYSTEM_PROMPT
        s = Settings()
        s.translators["ollama"] = TranslatorConfig(
            enabled=False,
            url="http://localhost:11434",
            model="llama3:latest",
            system_prompt=DEFAULT_OLLAMA_SYSTEM_PROMPT,
        )
        return s

    def test_dialog_has_ollama_group(self, qapp):
        from ta.ui.dialogs.settings_dialog import SettingsDialog
        from PySide6.QtWidgets import QGroupBox
        dlg = SettingsDialog(self._make_settings())
        groups = dlg.findChildren(QGroupBox)
        titles = [g.title() for g in groups]
        assert any("Ollama" in t for t in titles)

    def test_dialog_loads_saved_model(self, qapp):
        from ta.ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._make_settings())
        assert dlg._ollama_model_combo.currentText() == "llama3:latest"
        assert dlg._ollama_model_combo.isEnabled()

    def test_dialog_loads_system_prompt(self, qapp):
        from ta.ui.dialogs.settings_dialog import SettingsDialog
        from ta.config.settings import DEFAULT_OLLAMA_SYSTEM_PROMPT
        dlg = SettingsDialog(self._make_settings())
        assert dlg._ollama_prompt_edit.toPlainText() == DEFAULT_OLLAMA_SYSTEM_PROMPT

    def test_apply_captures_model_and_prompt(self, qapp):
        from ta.ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._make_settings())
        dlg._ollama_model_combo.setCurrentText("qwen2:latest")
        dlg._ollama_prompt_edit.setPlainText("custom prompt")
        result = dlg.apply()
        assert result.translators["ollama"].model == "qwen2:latest"
        assert result.translators["ollama"].system_prompt == "custom prompt"

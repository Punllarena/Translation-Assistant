# Ollama Translator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Ollama as a local-AI streaming translator panel to the aggregator widget, with configurable URL, model dropdown (populated via connection test), editable system prompt, and token-by-token streaming display.

**Architecture:** Add `translation_chunk = Signal(str)` to `BaseTranslator` (all translators inherit it; most never emit it). `OllamaTranslator` overrides `_worker` to stream via `httpx.stream()` and emit one chunk per token. `TranslationPanel` connects the new signal and appends text live.

**Tech Stack:** PySide6, httpx (already installed), Python dataclasses, TOML

## Global Constraints

- Python 3.12, PySide6 ≥ 6.6, httpx 0.28+
- Activate venv before running any command: `source .venv/bin/activate`
- Run tests with: `pytest tests/test_ollama.py -q`
- Full suite: `pytest -q`
- No new dependencies — httpx already used by `ta/translators/libretranslate.py`
- Default Ollama URL: `http://pun-ln01:8101`
- All test files go in `tests/` (same level as existing test files)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `ta/translators/base.py` | Add `translation_chunk = Signal(str)` |
| Modify | `ta/ui/translation_panel.py` | Streaming append, status states ("✓"/"✗"/"…") |
| Modify | `ta/config/settings.py` | `TranslatorConfig` + `model`/`system_prompt`; ollama defaults; TOML round-trip |
| Create | `ta/translators/ollama.py` | `OllamaTranslator` — streams `/api/chat` |
| Modify | `ta/ui/aggregator_widget.py` | Factory + label for `"ollama"` |
| Modify | `ta/ui/dialogs/settings_dialog.py` | Ollama GroupBox: URL, Test button, model dropdown, system prompt |
| Create | `tests/test_ollama.py` | All tests for the above |

---

### Task 1: Add streaming signal to BaseTranslator and update TranslationPanel

**Files:**
- Modify: `ta/translators/base.py`
- Modify: `ta/ui/translation_panel.py`
- Create: `tests/test_ollama.py`

**Interfaces:**
- Produces: `BaseTranslator.translation_chunk: Signal(str)` — emitted per token by streaming translators
- Produces: `TranslationPanel._on_chunk(token: str)` — appends token to output, sets status "…"
- Produces: status label states: `""` idle, `"…"` in-progress, `"✓"` done, `"✗"` error

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ollama.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failures**

```bash
source .venv/bin/activate && pytest tests/test_ollama.py -q
```

Expected: `FAILED` — `BaseTranslator` has no `translation_chunk`, `TranslationPanel` has no `_on_chunk`.

- [ ] **Step 3: Add `translation_chunk` to BaseTranslator**

Edit `ta/translators/base.py`. Change:

```python
class BaseTranslator(QObject):
    translation_ready = Signal(str)
    translation_error = Signal(str)
    translation_started = Signal()
```

To:

```python
class BaseTranslator(QObject):
    translation_ready = Signal(str)
    translation_error = Signal(str)
    translation_started = Signal()
    translation_chunk = Signal(str)
```

- [ ] **Step 4: Update TranslationPanel**

Edit `ta/ui/translation_panel.py`.

Add `QTextCursor` to imports at top:

```python
from PySide6.QtGui import QTextCursor
```

In `_connect_signals`, add after the existing connections:

```python
    def _connect_signals(self) -> None:
        self._translator.translation_ready.connect(self._on_ready)
        self._translator.translation_error.connect(self._on_error)
        self._translator.translation_started.connect(self._on_started)
        self._translator.translation_chunk.connect(self._on_chunk)
```

Replace `_on_ready`, `_on_error`, `_on_started` with:

```python
    def _on_ready(self, text: str) -> None:
        if text:
            if text.startswith("<html"):
                self._output.setHtml(text)
            else:
                self._output.setPlainText(text)
        self._status_label.setText("✓")

    def _on_error(self, msg: str) -> None:
        self._output.setPlainText(f"[Error] {msg}")
        self._status_label.setText("✗")

    def _on_started(self) -> None:
        self._output.clear()
        self._status_label.setText("…")

    def _on_chunk(self, token: str) -> None:
        self._output.moveCursor(QTextCursor.MoveOperation.End)
        self._output.insertPlainText(token)
        self._status_label.setText("…")
```

- [ ] **Step 5: Run tests — expect pass**

```bash
source .venv/bin/activate && pytest tests/test_ollama.py -q
```

Expected: all 6 tests in `TestBaseTranslatorChunkSignal` and `TestTranslationPanelStreaming` pass.

- [ ] **Step 6: Run full suite to catch regressions**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all existing tests pass (the `_on_ready("")` path now skips `setPlainText` and sets "✓" instead of ""; if any existing test checked for `""` status after ready, it will fail — fix it).

- [ ] **Step 7: Commit**

```bash
git add ta/translators/base.py ta/ui/translation_panel.py tests/test_ollama.py
git commit -m "feat(streaming): add translation_chunk signal and update TranslationPanel"
```

---

### Task 2: Extend Settings for Ollama

**Files:**
- Modify: `ta/config/settings.py`
- Modify: `tests/test_ollama.py` (append tests)

**Interfaces:**
- Consumes: `TranslatorConfig` from Task 1 (unchanged shape, just adding fields)
- Produces: `TranslatorConfig.model: str = ""`
- Produces: `TranslatorConfig.system_prompt: str = ""`
- Produces: `DEFAULT_OLLAMA_SYSTEM_PROMPT: str` — module-level constant, importable
- Produces: `Settings.translators["ollama"]` — default entry with url, system_prompt
- Produces: `Settings.layout_panels` — includes `"ollama"`
- Produces: TOML round-trip for `model` and `system_prompt`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ollama.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failures**

```bash
source .venv/bin/activate && pytest tests/test_ollama.py::TestSettingsOllamaExtensions -q
```

Expected: FAILED — `TranslatorConfig` has no `model`/`system_prompt`, no `"ollama"` in defaults.

- [ ] **Step 3: Update `ta/config/settings.py`**

Add module-level constant above the `TranslatorConfig` dataclass:

```python
DEFAULT_OLLAMA_SYSTEM_PROMPT = (
    "You are a professional {src} to {dst} translator.\n\n"
    "Task:\n\n"
    "* Translate only the {src} text contained in the user's current message.\n"
    "* Do not use, reference, infer, or rely on any previous messages, "
    "conversation history, or external context.\n"
    "* Treat each translation request as an independent, standalone input.\n"
    "* If the current message is ambiguous, translate only based on the text "
    "present in the current message.\n"
    "* Preserve the original meaning, tone, nuance, and intent as accurately as possible.\n"
    "* Produce natural, grammatically correct {dst} output.\n\n"
    "Output requirements:\n\n"
    "* Return only the translation.\n"
    "* Do not provide explanations, notes, commentary, alternatives, or metadata.\n\n"
    "Translate the {src} text in the user's current message:"
)
```

Replace `TranslatorConfig`:

```python
@dataclass
class TranslatorConfig:
    enabled: bool = False
    api_key: str = ""
    url: str = ""
    model: str = ""
    system_prompt: str = ""
```

In `Settings`, replace the `translators` default_factory to include ollama:

```python
    translators: dict[str, TranslatorConfig] = field(default_factory=lambda: {
        "deepl": TranslatorConfig(enabled=False),
        "google": TranslatorConfig(enabled=False),
        "bing": TranslatorConfig(enabled=False),
        "libretranslate": TranslatorConfig(enabled=False, url="http://localhost:5000"),
        "ollama": TranslatorConfig(
            enabled=False,
            url="http://pun-ln01:8101",
            system_prompt=DEFAULT_OLLAMA_SYSTEM_PROMPT,
        ),
        "mecab": TranslatorConfig(enabled=True),
        "jparser": TranslatorConfig(enabled=True),
    })
```

Replace `layout_panels` default:

```python
    layout_panels: list[str] = field(default_factory=lambda: [
        "deepl", "google", "bing", "libretranslate", "ollama", "mecab", "jparser"
    ])
```

In `_from_dict`, replace the translator construction inside `if "translators" in data:`:

```python
        if "translators" in data:
            for name, cfg in data["translators"].items():
                api_key = cfg.get("api_key", "")
                env_map = {
                    "deepl": "DEEPL_API_KEY",
                    "google": "GOOGLE_TRANSLATE_KEY",
                    "bing": "AZURE_TRANSLATOR_KEY",
                }
                if not api_key and name in env_map:
                    api_key = os.environ.get(env_map[name], "")
                s.translators[name] = TranslatorConfig(
                    enabled=cfg.get("enabled", False),
                    api_key=api_key,
                    url=cfg.get("url", ""),
                    model=cfg.get("model", ""),
                    system_prompt=cfg.get("system_prompt", ""),
                )
```

In `save()`, replace the translator serialization loop:

```python
        for name, cfg in self.translators.items():
            lines += [
                f"[translators.{name}]",
                f"enabled = {str(cfg.enabled).lower()}",
                f'api_key = "{cfg.api_key}"',
            ]
            if cfg.url:
                lines.append(f'url = "{cfg.url}"')
            if cfg.model:
                lines.append(f'model = "{cfg.model}"')
            if cfg.system_prompt:
                lines.append(f'system_prompt = """\n{cfg.system_prompt}"""')
            lines.append("")
```

- [ ] **Step 4: Run tests — expect pass**

```bash
source .venv/bin/activate && pytest tests/test_ollama.py::TestSettingsOllamaExtensions -q
```

Expected: all 8 tests pass.

- [ ] **Step 5: Run full suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ta/config/settings.py tests/test_ollama.py
git commit -m "feat(settings): extend TranslatorConfig with model/system_prompt, add ollama defaults"
```

---

### Task 3: Implement OllamaTranslator

**Files:**
- Create: `ta/translators/ollama.py`
- Modify: `tests/test_ollama.py` (append tests)

**Interfaces:**
- Consumes: `BaseTranslator` from Task 1 — inherits `translation_chunk`, `translation_ready`, `translation_error`, `translation_started` signals; inherits `_lock`, `_pending`, `_running`, `_cancel` state; overrides `_worker`
- Consumes: `Language` from `ta.config.languages`
- Consumes: `to_google_code(lang) -> str` from `ta.config.languages`
- Produces: `OllamaTranslator(url: str, model: str, system_prompt: str, parent=None)`
- Produces: emits `translation_chunk(str)` per streaming token
- Produces: emits `translation_ready("")` on completion
- Produces: emits `translation_error(str)` on HTTP/network failure

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ollama.py`:

```python
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
        t.translation_chunk.connect(chunks.append)
        t.translation_ready.connect(lambda _: done.set())

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
        t.translation_ready.connect(lambda v: (ready_values.append(v), done.set()))

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
        t.translation_error.connect(lambda e: (errors.append(e), done.set()))

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
        t.translation_ready.connect(lambda _: None)

        with patch("ta.translators.ollama.httpx.stream", capture_stream):
            t.translate("text", Language.Japanese, Language.English)
            done.wait(timeout=3.0)

        sys_msg = captured_payload["messages"][0]["content"]
        assert "Japanese" in sys_msg
        assert "English" in sys_msg
        assert "{src}" not in sys_msg
        assert "{dst}" not in sys_msg
```

- [ ] **Step 2: Run tests — expect failures**

```bash
source .venv/bin/activate && pytest tests/test_ollama.py::TestOllamaTranslator -q
```

Expected: FAILED — `ta.translators.ollama` does not exist.

- [ ] **Step 3: Create `ta/translators/ollama.py`**

```python
from __future__ import annotations

import json

import httpx

from ta.config.languages import Language, to_google_code
from ta.translators.base import BaseTranslator


def _lang_display(lang: Language) -> str:
    code = to_google_code(lang)
    name = lang.name.replace("_", " ")
    return f"{name} ({code})" if code else name


class OllamaTranslator(BaseTranslator):
    def __init__(self, url: str, model: str, system_prompt: str, parent=None):
        super().__init__("Ollama", parent)
        self._url = url.rstrip("/")
        self._model = model
        self._system_prompt = system_prompt

    def _worker(self) -> None:
        while True:
            with self._lock:
                if self._cancel or self._pending is None:
                    self._running = False
                    return
                text, src, dst = self._pending
                self._pending = None

            self.translation_started.emit()
            try:
                self._stream_translate(text, src, dst)
            except Exception as exc:
                if not self._cancel:
                    self.translation_error.emit(str(exc))

            with self._lock:
                if self._pending is None:
                    self._running = False
                    return

    def _stream_translate(self, text: str, src: Language, dst: Language) -> None:
        src_display = _lang_display(src)
        dst_display = _lang_display(dst)
        system = (
            self._system_prompt
            .replace("{src}", src_display)
            .replace("{dst}", dst_display)
        )
        payload = {
            "model": self._model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        }
        with httpx.stream("POST", f"{self._url}/api/chat", json=payload, timeout=60) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if self._cancel:
                    return
                if not line.strip():
                    continue
                obj = json.loads(line)
                if obj.get("done"):
                    break
                token = obj.get("message", {}).get("content", "")
                if token:
                    self.translation_chunk.emit(token)

        if not self._cancel:
            self.translation_ready.emit("")
```

- [ ] **Step 4: Run tests — expect pass**

```bash
source .venv/bin/activate && pytest tests/test_ollama.py::TestOllamaTranslator -q
```

Expected: all 4 tests pass.

- [ ] **Step 5: Run full suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ta/translators/ollama.py tests/test_ollama.py
git commit -m "feat(ollama): implement OllamaTranslator with streaming via httpx"
```

---

### Task 4: Wire Ollama into aggregator and settings dialog

**Files:**
- Modify: `ta/ui/aggregator_widget.py`
- Modify: `ta/ui/dialogs/settings_dialog.py`
- Modify: `tests/test_ollama.py` (append tests)

**Interfaces:**
- Consumes: `OllamaTranslator(url, model, system_prompt)` from Task 3
- Consumes: `TranslatorConfig.model`, `TranslatorConfig.system_prompt` from Task 2
- Consumes: `DEFAULT_OLLAMA_SYSTEM_PROMPT` from `ta.config.settings`
- Produces: `_build_translator("ollama", cfg)` returns `OllamaTranslator`
- Produces: Ollama GroupBox in SettingsDialog Translators tab with URL field, Test button, model combo, system prompt editor

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ollama.py`:

```python
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
            url="http://pun-ln01:8101",
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
```

- [ ] **Step 2: Run tests — expect failures**

```bash
source .venv/bin/activate && pytest tests/test_ollama.py::TestBuildTranslatorOllama tests/test_ollama.py::TestSettingsDialogOllamaGroup -q
```

Expected: FAILED — no `"ollama"` case in `_build_translator`, no Ollama group in dialog.

- [ ] **Step 3: Update `ta/ui/aggregator_widget.py`**

Add the `"ollama"` case to `_build_translator` (before the `return None`):

```python
    if name == "ollama":
        from ta.translators.ollama import OllamaTranslator
        return OllamaTranslator(
            url=cfg.url or "http://pun-ln01:8101",
            model=cfg.model or "",
            system_prompt=cfg.system_prompt or "",
        )
```

- [ ] **Step 4: Update `ta/ui/dialogs/settings_dialog.py`**

Add `QPushButton` and `QPlainTextEdit` to imports:

```python
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QTabWidget, QWidget,
    QFormLayout, QVBoxLayout, QHBoxLayout,
    QComboBox, QCheckBox, QLineEdit, QLabel,
    QSpinBox, QGroupBox, QScrollArea, QPushButton, QPlainTextEdit,
)
```

Add `"ollama"` to `_TRANSLATOR_LABELS`:

```python
_TRANSLATOR_LABELS = {
    "deepl": "DeepL",
    "google": "Google Translate",
    "bing": "Bing/Azure",
    "libretranslate": "LibreTranslate",
    "mecab": "MeCab",
    "jparser": "JParser",
    "ollama": "Ollama (Local AI)",
}
```

Add `"ollama"` to the no-key group in `_make_translators_tab`. Replace:

```python
            if name in ("mecab", "jparser"):
                api_edit.setEnabled(False)
                api_edit.setPlaceholderText("No key required")
```

With:

```python
            if name in ("mecab", "jparser", "ollama"):
                api_edit.setEnabled(False)
                api_edit.setPlaceholderText("No key required")
```

After the `if name == "libretranslate":` block (inside the for loop), add:

```python
            if name == "ollama":
                url_edit = QLineEdit()
                url_edit.setPlaceholderText("http://pun-ln01:8101")
                form.addRow("Server URL:", url_edit)
                self._translator_url_widgets[name] = url_edit

                test_row_w = QWidget()
                test_row_l = QHBoxLayout(test_row_w)
                test_row_l.setContentsMargins(0, 0, 0, 0)
                self._ollama_test_btn = QPushButton("Test Connection")
                self._ollama_status_lbl = QLabel("")
                test_row_l.addWidget(self._ollama_test_btn)
                test_row_l.addWidget(self._ollama_status_lbl)
                test_row_l.addStretch()
                form.addRow(test_row_w)
                self._ollama_test_btn.clicked.connect(self._on_ollama_test)

                self._ollama_model_combo = QComboBox()
                self._ollama_model_combo.setEnabled(False)
                form.addRow("Model:", self._ollama_model_combo)

                self._ollama_prompt_edit = QPlainTextEdit()
                self._ollama_prompt_edit.setFixedHeight(120)
                form.addRow("System prompt:", self._ollama_prompt_edit)
```

Add `_on_ollama_test` method to `SettingsDialog`:

```python
    def _on_ollama_test(self) -> None:
        import httpx
        url = self._translator_url_widgets["ollama"].text().rstrip("/")
        prev_model = self._ollama_model_combo.currentText()
        try:
            resp = httpx.get(f"{url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            self._ollama_model_combo.clear()
            for m in models:
                self._ollama_model_combo.addItem(m)
            self._ollama_model_combo.setEnabled(True)
            self._ollama_status_lbl.setText("Connected ✓")
            if prev_model:
                idx = self._ollama_model_combo.findText(prev_model)
                if idx >= 0:
                    self._ollama_model_combo.setCurrentIndex(idx)
                else:
                    self._ollama_model_combo.insertItem(0, prev_model)
                    self._ollama_model_combo.setCurrentIndex(0)
        except Exception as exc:
            self._ollama_status_lbl.setText(f"Error: {exc}")
            self._ollama_model_combo.clear()
            self._ollama_model_combo.setEnabled(False)
```

In `_load`, inside the `for name, (cb, edit) in self._translator_widgets.items():` loop, add after the existing `if name in self._translator_url_widgets:` block:

```python
            if name == "ollama":
                from ta.config.settings import DEFAULT_OLLAMA_SYSTEM_PROMPT
                if cfg and cfg.model:
                    self._ollama_model_combo.addItem(cfg.model)
                    self._ollama_model_combo.setCurrentIndex(0)
                    self._ollama_model_combo.setEnabled(True)
                self._ollama_prompt_edit.setPlainText(
                    cfg.system_prompt if cfg and cfg.system_prompt
                    else DEFAULT_OLLAMA_SYSTEM_PROMPT
                )
```

In `apply()`, inside the `for name, (cb, edit) in self._translator_widgets.items():` loop, add after `if name in self._translator_url_widgets:`:

```python
            if name == "ollama":
                s.translators[name].model = self._ollama_model_combo.currentText()
                s.translators[name].system_prompt = self._ollama_prompt_edit.toPlainText()
```

- [ ] **Step 5: Run tests — expect pass**

```bash
source .venv/bin/activate && pytest tests/test_ollama.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Run full suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all pass.

- [ ] **Step 7: Manual smoke test**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

1. Open Settings → Translators tab → scroll to "Ollama (Local AI)" group
2. URL should show `http://pun-ln01:8101`, model "llama3:latest" pre-populated (if previously saved)
3. Click "Test Connection" — dropdown should populate with models from the server
4. Select a model, click OK
5. Type Japanese text in source panel and translate — Ollama panel should stream tokens live

- [ ] **Step 8: Commit**

```bash
git add ta/ui/aggregator_widget.py ta/ui/dialogs/settings_dialog.py tests/test_ollama.py
git commit -m "feat(ollama): wire OllamaTranslator into aggregator and settings dialog"
```

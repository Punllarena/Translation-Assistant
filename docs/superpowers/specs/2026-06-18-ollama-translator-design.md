# Ollama Translator — Design Spec
**Date:** 2026-06-18

## Overview

Add Ollama as a local-AI translator in the aggregator panel. One Ollama instance supported. Features: configurable API URL, model selection (populated via connection test), editable system prompt with language placeholders, and token-by-token streaming display.

---

## Architecture

### New file
- `ta/translators/ollama.py` — `OllamaTranslator(BaseTranslator)`

### Modified files
| File | Change |
|------|--------|
| `ta/translators/base.py` | Add `translation_chunk = Signal(str)` |
| `ta/ui/translation_panel.py` | Connect `translation_chunk`; streaming append; status states |
| `ta/config/settings.py` | Extend `TranslatorConfig` with `model`, `system_prompt`; add ollama defaults |
| `ta/ui/dialogs/settings_dialog.py` | Ollama GroupBox: URL, Test button, model dropdown, system prompt textarea |
| `ta/ui/aggregator_widget.py` | Add `"ollama"` to `_build_translator` and `_TRANSLATOR_LABELS` |

### Data flow
```
SettingsDialog → settings.toml → AggregatorWidget._build_translator
  → OllamaTranslator._worker → httpx.stream(POST /api/chat)
      → emit translation_chunk(token)  ← TranslationPanel appends
      → emit translation_ready("")     ← clears "…" status → "✓"
```

---

## OllamaTranslator

**File:** `ta/translators/ollama.py`

- Subclasses `BaseTranslator`
- Constructor: `__init__(self, url, model, system_prompt, parent=None)`
- Overrides `_worker` (not `_do_translate`) to stream responses
- API endpoint: `POST {url}/api/chat`
- Payload:
  ```json
  {
    "model": "<model>",
    "stream": true,
    "messages": [
      {"role": "system", "content": "<resolved system prompt>"},
      {"role": "user",   "content": "<source text>"}
    ]
  }
  ```
- Streaming format: NDJSON, one JSON object per line
  - In-progress: `{"message": {"content": "token"}, "done": false}`
  - Final: `{"done": true}`
- Emits `translation_chunk(token)` per content token
- Emits `translation_ready("")` on `done: true` (signals completion)
- Emits `translation_error(msg)` on HTTP error or exception

**System prompt substitution:**
```python
system_prompt.replace("{src}", src_display).replace("{dst}", dst_display)
```
Where `src_display` / `dst_display` are language names like `"Japanese (ja)"`, `"English (en)"`.

---

## Settings Storage

### `TranslatorConfig` (extended)
```python
@dataclass
class TranslatorConfig:
    enabled: bool = False
    api_key: str = ""
    url: str = ""
    model: str = ""          # new
    system_prompt: str = ""  # new
```

### Ollama default in `Settings`
```python
"ollama": TranslatorConfig(
    enabled=False,
    url="http://pun-ln01:8101",
    model="",
    system_prompt=(
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
    ),
)
```

`"ollama"` added to `layout_panels` default list.

**TOML serialization:** `model` and `system_prompt` written for all translators that have them set (non-empty). `system_prompt` uses TOML triple-quoted multiline strings (`"""..."""`) to handle embedded newlines. `Settings._from_dict` reads them with empty-string fallback — backward-compatible.

---

## Settings Dialog — Ollama GroupBox

```
┌─ Ollama ──────────────────────────────────────────────┐
│ [✓] Enabled                                           │
│ Server URL:  [http://pun-ln01:8101         ] [Test]   │
│ Status:      Connected ✓  /  Error: <msg>             │
│ Model:       [llama3:latest           ▼]              │
│ System prompt:                                        │
│ ┌─────────────────────────────────────────────────┐  │
│ │ You are a professional {src} to {dst} ...       │  │
│ │ ...                                             │  │
│ └─────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────┘
```

**Test button behavior:**
1. `httpx.get(f"{url}/api/tags", timeout=5)` on UI thread
2. Success: parse `response.json()["models"]`, populate model `QComboBox` with `m["name"]` for each. Show "Connected ✓". Select saved model if present in list; otherwise add it as first item.
3. Failure: show "Error: \<message\>", clear dropdown

**Model dropdown:** disabled until test passes (or saved model exists).

**System prompt:** `QPlainTextEdit`, ~5 rows, editable. Placeholder text shows the default template.

**`apply()`** saves `model = combo.currentText()`, `system_prompt = prompt_edit.toPlainText()`.

**Model dropdown pre-population:** on dialog open, if `cfg.model` is non-empty, add it as the sole item and enable the dropdown immediately. Test button refreshes the full list from the server.

---

## TranslationPanel — Streaming

**`_connect_signals` addition:**
```python
self._translator.translation_chunk.connect(self._on_chunk)
```

**New slot:**
```python
def _on_chunk(self, token: str) -> None:
    self._output.moveCursor(QTextCursor.MoveOperation.End)
    self._output.insertPlainText(token)
    self._status_label.setText("…")
```

**`_on_started` change:** calls `self._output.clear()` so each request starts fresh.

**`_on_ready` change:** if `text` is non-empty, sets it (non-streaming path); if empty, just clears status → `"✓"`.

**Status label states:**
| Value | Meaning |
|-------|---------|
| `""` | idle |
| `"…"` | in progress |
| `"✓"` | done |
| `"✗"` | error |

---

## Dependencies

`httpx` already used by `libretranslate.py` — no new dependencies.

---

## Testing Notes

- `OllamaTranslator` testable by mocking `httpx.stream` to yield fake NDJSON lines
- Settings round-trip: `model` and `system_prompt` survive save/load cycle
- `translation_chunk` signal can be tested with a mock slot counting calls

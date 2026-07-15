# Ollama Eager Prefetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While the user is idle after the current line's Ollama translation finishes, silently pre-translate the next N lines into the aggregator's MT cache (translation + thinking trace), so advancing shows instant "✓ cached" results.

**Architecture:** A second `OllamaTranslator` instance with no panel attached does background prefetch, driven by a single-shot idle `QTimer`. The TA widget emits the upcoming lines via a new signal; `CombinedMainWindow` bridges it to the aggregator. `_mt_cache` values change from `str` to `(translation, thinking)` tuples.

**Tech Stack:** PySide6, httpx (existing), pytest.

**Spec:** `docs/superpowers/specs/2026-07-15-ollama-prefetch-design.md`

## Global Constraints

- Activate venv before any command: `source .venv/bin/activate`
- Never import `sqlite3` outside `db.py` (untouched here).
- `translation_assistant/ui/main_window.py` is legacy — do not modify.
- Cache key must be produced by `AggregatorWidget._preprocess` so prefetch keys match `_on_translate` keys exactly.
- Foreground Ollama request must never queue behind a prefetch: halt prefetcher on every `_on_translate`.
- Defaults: `prefetch_count = 0` (disabled), `prefetch_idle_ms = 3000`.

---

### Task 1: Settings — prefetch config fields

**Files:**
- Modify: `ta/config/settings.py` (TranslatorConfig ~line 31, `_from_dict` ~line 143, `save()` ~line 183)
- Test: `tests/test_ollama.py` (append new class)

**Interfaces:**
- Produces: `TranslatorConfig.prefetch_count: int = 0`, `TranslatorConfig.prefetch_idle_ms: int = 3000`; both survive TOML save/load. Later tasks read them from `settings.translators["ollama"]`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ollama.py`:

```python
# ---------------------------------------------------------------------------
# Prefetch: settings fields
# ---------------------------------------------------------------------------

class TestPrefetchSettings:
    def test_defaults(self):
        from ta.config.settings import TranslatorConfig
        cfg = TranslatorConfig()
        assert cfg.prefetch_count == 0
        assert cfg.prefetch_idle_ms == 3000

    def test_toml_roundtrip(self, tmp_path):
        from ta.config.settings import Settings, TranslatorConfig
        s = Settings()
        s.translators["ollama"] = TranslatorConfig(
            enabled=True, url="http://localhost:11434", model="m",
            system_prompt="p", prefetch_count=5, prefetch_idle_ms=7000,
        )
        path = tmp_path / "settings.toml"
        s.save(path)
        s2 = Settings.load(path)
        assert s2.translators["ollama"].prefetch_count == 5
        assert s2.translators["ollama"].prefetch_idle_ms == 7000

    def test_load_without_prefetch_keys_uses_defaults(self, tmp_path):
        from ta.config.settings import Settings
        path = tmp_path / "settings.toml"
        path.write_text(
            '[translators.ollama]\nenabled = true\napi_key = ""\n',
            encoding="utf-8",
        )
        s = Settings.load(path)
        assert s.translators["ollama"].prefetch_count == 0
        assert s.translators["ollama"].prefetch_idle_ms == 3000
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_ollama.py::TestPrefetchSettings -q`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'prefetch_count'` / `AttributeError`.

- [ ] **Step 3: Implement**

In `ta/config/settings.py`, `TranslatorConfig`:

```python
@dataclass
class TranslatorConfig:
    enabled: bool = False
    api_key: str = ""
    url: str = ""
    model: str = ""
    system_prompt: str = ""
    # Ollama only: background prefetch of upcoming lines (0 = off)
    prefetch_count: int = 0
    prefetch_idle_ms: int = 3000
```

In `_from_dict`, in the `s.translators[name] = TranslatorConfig(...)` call add:

```python
                    prefetch_count=cfg.get("prefetch_count", 0),
                    prefetch_idle_ms=cfg.get("prefetch_idle_ms", 3000),
```

In `save()`, inside the `for name, cfg in self.translators.items():` loop after the `if cfg.model:` block:

```python
            if cfg.prefetch_count:
                lines.append(f"prefetch_count = {cfg.prefetch_count}")
            if cfg.prefetch_idle_ms != 3000:
                lines.append(f"prefetch_idle_ms = {cfg.prefetch_idle_ms}")
```

(Note: must come before the `system_prompt` triple-quote block or after it — either works; keep TOML valid by placing before `system_prompt`, since the multi-line string ends the visual block.)

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_ollama.py::TestPrefetchSettings -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ta/config/settings.py tests/test_ollama.py
git commit -m "feat(settings): ollama prefetch_count / prefetch_idle_ms config"
```

---

### Task 2: TranslationPanel — show cached thinking

**Files:**
- Modify: `ta/ui/translation_panel.py` (`show_result`, lines 121–136)
- Test: `tests/test_ollama.py` (append new class)

**Interfaces:**
- Consumes: nothing new.
- Produces: `TranslationPanel.show_result(text: str, source: str, src: Language, dst: Language, thinking: str = "")`. Empty `thinking` behaves exactly as today (trace cleared/hidden).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ollama.py` (module already imports `BaseTranslator` and has `qapp` fixture via conftest):

```python
# ---------------------------------------------------------------------------
# Prefetch: panel shows cached thinking
# ---------------------------------------------------------------------------

class TestShowResultThinking:
    def _panel(self):
        from ta.ui.translation_panel import TranslationPanel
        return TranslationPanel(BaseTranslator("Ollama"))

    def test_cached_thinking_shown_collapsed(self, qapp):
        from ta.config.languages import Language
        panel = self._panel()
        panel.show_result(
            "hello", "こんにちは", Language.Japanese, Language.English,
            thinking="line one\nline two",
        )
        assert panel._output.toPlainText() == "hello"
        assert not panel._thinking_toggle.isHidden()
        assert not panel._thinking_toggle.isChecked()
        assert panel._thinking_toggle.text() == "Thinking (2 lines)"
        assert panel._thinking_box.isHidden()
        assert panel._thinking_box.toPlainText() == "line one\nline two"

    def test_no_thinking_hides_trace(self, qapp):
        from ta.config.languages import Language
        panel = self._panel()
        # Simulate a previous streamed trace, then a cached line without one
        panel._on_thinking("old trace")
        panel.show_result("hi", "やあ", Language.Japanese, Language.English)
        assert panel._thinking_toggle.isHidden()
        assert panel._thinking_box.isHidden()
        assert panel._thinking_box.toPlainText() == ""

    def test_expanding_cached_thinking_shows_box(self, qapp):
        from ta.config.languages import Language
        panel = self._panel()
        panel.show_result(
            "hello", "こんにちは", Language.Japanese, Language.English,
            thinking="trace",
        )
        panel._thinking_toggle.setChecked(True)
        assert not panel._thinking_box.isHidden()
        assert panel._output.isVisibleTo(panel)  # not streaming: no takeover
```

- [ ] **Step 2: Run tests, verify fail**

Run: `pytest tests/test_ollama.py::TestShowResultThinking -q`
Expected: FAIL — `TypeError: show_result() got an unexpected keyword argument 'thinking'`.

- [ ] **Step 3: Implement**

Replace `show_result` in `ta/ui/translation_panel.py`:

```python
    def show_result(self, text: str, source: str, src: Language, dst: Language,
                    thinking: str = "") -> None:
        """Display a cached result without contacting the translator."""
        self._current_text = source
        self._current_src = src
        self._current_dst = dst
        if not self._enable_cb.isChecked():
            return
        # An interrupted stream may still hold the panel in thinking takeover;
        # end it while the streaming flag is still set so the layout restores.
        self._end_thinking_takeover()
        self._thinking_text = thinking
        self._thinking_box.setPlainText(thinking)
        if thinking:
            # Collapsed by default; the toggled handler writes the line count.
            if self._thinking_toggle.isChecked():
                self._thinking_toggle.setChecked(False)
            else:
                self._on_thinking_toggled(False)
            self._thinking_toggle.show()
        else:
            self._thinking_toggle.hide()
            self._thinking_box.hide()
        self._stats_text = ""
        self._status_label.setToolTip("")
        self._on_ready(text)
        self._set_status("ok", "✓ cached")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_ollama.py::TestShowResultThinking tests/test_ollama.py -q`
Expected: all pass (existing `show_result` callers use positional args only).

- [ ] **Step 5: Commit**

```bash
git add ta/ui/translation_panel.py tests/test_ollama.py
git commit -m "feat(panel): show_result accepts cached thinking trace"
```

---

### Task 3: TA widget — upcoming_sentences_changed signal + bridge

**Files:**
- Modify: `translation_assistant/ui/main_widget.py` (signal at ~line 126; emit sites ~line 629 `_finish_load` and ~line 677 `_update_ui_for_pointer`; new helper)
- Modify: `translation_assistant/ui/combined_window.py` (`_connect_bridge`, line 75)
- Test: `tests/test_combined_window.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: signal `TranslationAssistantWidget.upcoming_sentences_changed(list)` — up to 20 upcoming content lines after the current pointer, transformed like the displayed line (`replace_and_parse(...)[0].lstrip("%$").strip()`), emitted immediately after every `source_sentence_changed` emission in `_finish_load` and `_update_ui_for_pointer`. Bridged to `AggregatorWidget.set_prefetch_queue` (implemented in Task 5; the connect line is added there to keep this task green).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_combined_window.py`:

```python
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
```

- [ ] **Step 2: Run tests, verify fail**

Run: `pytest tests/test_combined_window.py::TestUpcomingSentences -q`
Expected: FAIL — `AttributeError: ... has no attribute 'upcoming_sentences_changed'`.

- [ ] **Step 3: Implement**

`translation_assistant/ui/main_widget.py` — signal declaration (below `source_sentence_changed`):

```python
    source_sentence_changed = Signal(str)
    upcoming_sentences_changed = Signal(list)
```

New helper (place next to `_update_ui_for_pointer`):

```python
    def _upcoming_sentences(self, limit: int = 20) -> list[str]:
        """Next `limit` content lines after the pointer, transformed like the
        displayed line, for the aggregator's prefetch queue."""
        from translation_assistant.core import replace_and_parse, line_has_content
        out: list[str] = []
        for i in range(self._array_pointer + 1, len(self._raw_lines)):
            if len(out) >= limit:
                break
            raw = self._raw_lines[i]
            if not line_has_content(raw):
                continue
            display, _, _ = replace_and_parse(raw, self._glossary, self._parse_chars)
            display = display.lstrip("%$").strip()
            if display:
                out.append(display)
        return out
```

In `_finish_load`, directly after `self.source_sentence_changed.emit(display.lstrip("%$").strip())` (~line 629):

```python
        self.upcoming_sentences_changed.emit(self._upcoming_sentences())
```

In `_update_ui_for_pointer`, directly after its `self.source_sentence_changed.emit(...)` (~line 677):

```python
        self.upcoming_sentences_changed.emit(self._upcoming_sentences())
```

Do NOT touch `combined_window.py` yet — `set_prefetch_queue` doesn't exist until Task 5.

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_combined_window.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_combined_window.py
git commit -m "feat(ta): emit upcoming sentences for aggregator prefetch"
```

---

### Task 4: Aggregator — cache thinking alongside translation

**Files:**
- Modify: `ta/ui/aggregator_widget.py` (`_mt_cache` type, `_setup_ui` ollama connections ~line 111, `_on_translate` ~line 160, `_on_ollama_ready` ~line 176, `_seed_mt_cache` ~line 202)
- Test: `tests/test_ollama.py` (`TestAggregatorOllamaCache` — update existing asserts, add thinking test)

**Interfaces:**
- Consumes: `TranslationPanel.show_result(..., thinking="")` from Task 2.
- Produces: `AggregatorWidget._mt_cache: dict[tuple[str, Language, Language], tuple[str, str]]` — value is `(translation, thinking)`. `AggregatorWidget._ollama_thinking: list[str]` accumulates the foreground thinking stream. Prefetch (Task 5) writes the same value shape.

- [ ] **Step 1: Update existing tests + add failing test**

In `tests/test_ollama.py::TestAggregatorOllamaCache`:

`test_cache_hit_skips_translator_and_debounce`: change the seed line to

```python
        w._mt_cache[(text, src, dst)] = ("cached!", "")
```

`test_ready_caches_result_and_records_history`: change the cache assert to

```python
        assert w._mt_cache[key] == ("Hello world", "")
```

`test_seed_cache_from_history`: change the assert to

```python
        assert w._mt_cache[("古い行", src, dst)] == ("old line", "")
```

Add to the class:

```python
    def test_ready_caches_thinking(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        w._ollama_translator.translate = lambda *a: None
        w.translate_source("some line")
        w._ollama_debounce.stop()
        w._fire_ollama()

        w._ollama_thinking[:] = ["consider", " nuance"]
        w._ollama_chunks[:] = ["Hello"]
        w._on_ollama_ready("")

        key = w._ollama_panel.request_key()
        assert w._mt_cache[key] == ("Hello", "consider nuance")

    def test_cache_hit_shows_cached_thinking(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        w._ollama_translator.translate = lambda *a: None
        text = w._preprocess("hello line")
        src = w._source_panel.src_language()
        dst = w._source_panel.dst_language()
        w._mt_cache[(text, src, dst)] = ("cached!", "some trace")

        w.translate_source("hello line")

        assert w._ollama_panel._output.toPlainText() == "cached!"
        assert w._ollama_panel._thinking_box.toPlainText() == "some trace"
        assert not w._ollama_panel._thinking_toggle.isHidden()

    def test_started_clears_thinking_accumulator(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        w._ollama_thinking[:] = ["stale"]
        w._ollama_chunks[:] = ["stale"]
        w._ollama_translator.translation_started.emit()
        assert w._ollama_thinking == []
        assert w._ollama_chunks == []
```

- [ ] **Step 2: Run tests, verify fail**

Run: `pytest tests/test_ollama.py::TestAggregatorOllamaCache -q`
Expected: FAIL — cache-hit test raises on tuple unpack / thinking attr missing.

- [ ] **Step 3: Implement**

`ta/ui/aggregator_widget.py`:

`__init__` — change declarations:

```python
        self._mt_cache: dict[tuple[str, Language, Language], tuple[str, str]] = {}
        self._ollama_chunks: list[str] = []
        self._ollama_thinking: list[str] = []
```

`_setup_ui` ollama branch — replace the started/chunk connections:

```python
                # Accumulate streamed tokens + thinking so the finished
                # translation can be cached and written to history (ready
                # itself emits "").
                translator.translation_started.connect(self._on_ollama_started)
                translator.translation_chunk.connect(self._ollama_chunks.append)
                translator.translation_thinking.connect(self._ollama_thinking.append)
                translator.translation_ready.connect(self._on_ollama_ready)
```

New slot (next to `_on_ollama_ready`):

```python
    def _on_ollama_started(self) -> None:
        self._ollama_chunks.clear()
        self._ollama_thinking.clear()
```

`_on_translate` cache-hit branch:

```python
        cached = self._mt_cache.get((text, src, dst))
        if cached is not None:
            self._ollama_debounce.stop()
            translation, thinking = cached
            self._ollama_panel.show_result(translation, text, src, dst, thinking)
        else:
```

`_on_ollama_ready`:

```python
    def _on_ollama_ready(self, _ignored: str) -> None:
        text = "".join(self._ollama_chunks)
        if not text:
            return
        key = self._ollama_panel.request_key()
        self._mt_cache[key] = (text, "".join(self._ollama_thinking))
        if key[0] == self._current_source:
            self._on_translation_received("ollama", text)
        self._notify_ollama_done(text)
```

`_seed_mt_cache` loop body:

```python
            if t:
                self._mt_cache[(e.source, src, dst)] = (t, "")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_ollama.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ta/ui/aggregator_widget.py tests/test_ollama.py
git commit -m "feat(aggregator): cache thinking trace with ollama translations"
```

---

### Task 5: Aggregator — prefetch engine + bridge wiring

**Files:**
- Modify: `ta/ui/aggregator_widget.py` (`__init__`, `_setup_ui` ollama branch, `_on_translate`, `_on_ollama_ready`, new methods)
- Modify: `translation_assistant/ui/combined_window.py` (`_connect_bridge`)
- Test: `tests/test_ollama.py` (new class), `tests/test_combined_window.py` (bridge test)

**Interfaces:**
- Consumes: `TranslatorConfig.prefetch_count/prefetch_idle_ms` (Task 1); `upcoming_sentences_changed` (Task 3); `_mt_cache` tuple values (Task 4).
- Produces: `AggregatorWidget.set_prefetch_queue(sentences: list)` slot; `_ollama_prefetcher` (second `OllamaTranslator` or `None`); `_prefetch_idle: QTimer`; `_fire_prefetch()`, `_on_prefetch_started()`, `_on_prefetch_ready(str)`, `_start_prefetch_idle()`, `_stop_prefetch()`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ollama.py`:

```python
# ---------------------------------------------------------------------------
# Prefetch: engine
# ---------------------------------------------------------------------------

class TestAggregatorPrefetch:
    def _make_widget(self, qapp, tmp_path, count=3, idle_ms=3000):
        from ta.config.settings import Settings, TranslatorConfig
        from ta.core.history import HistoryStore

        s = Settings()
        for cfg in s.translators.values():
            cfg.enabled = False
        s.translators["ollama"] = TranslatorConfig(
            enabled=True, url="http://test:1", model="m", system_prompt="p",
            prefetch_count=count, prefetch_idle_ms=idle_ms,
        )
        s.layout_panels = ["ollama"]
        s.enable_substitutions = False

        def make_history(max_bytes):
            return HistoryStore(path=tmp_path / "history.jsonl", max_bytes=max_bytes)

        with patch("ta.ui.aggregator_widget.Settings.load", return_value=s), \
             patch("ta.ui.aggregator_widget.HistoryStore", make_history), \
             patch("ta.ui.aggregator_widget.ClipboardMonitor"):
            from ta.ui.aggregator_widget import AggregatorWidget
            w = AggregatorWidget()
        # Never hit the network
        w._ollama_translator.translate = lambda *a: None
        w._sent = []
        w._ollama_prefetcher.translate = lambda *a: w._sent.append(a)
        w._ollama_prefetcher.halt = lambda: w._sent.append("halt")
        return w

    def test_disabled_when_count_zero(self, qapp, tmp_path):
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
            w = AggregatorWidget()
        assert w._ollama_prefetcher is None
        # Ready must not start the idle timer
        w._ollama_chunks[:] = ["x"]
        w._on_ollama_ready("")
        assert not w._prefetch_idle.isActive()

    def test_idle_timer_uses_configured_interval(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path, idle_ms=7000)
        assert w._prefetch_idle.interval() == 7000
        assert w._prefetch_idle.isSingleShot()

    def test_foreground_ready_starts_idle_timer(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        w.translate_source("line one")
        w._ollama_debounce.stop()
        w._ollama_chunks[:] = ["done"]
        w._on_ollama_ready("")
        assert w._prefetch_idle.isActive()

    def test_cache_hit_starts_idle_timer(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        text = w._preprocess("hello")
        src = w._source_panel.src_language()
        dst = w._source_panel.dst_language()
        w._mt_cache[(text, src, dst)] = ("cached", "")
        w.translate_source("hello")
        assert w._prefetch_idle.isActive()

    def test_navigation_halts_prefetch(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        w._prefetch_idle.start()
        w.translate_source("new line")
        assert not w._prefetch_idle.isActive()
        assert "halt" in w._sent

    def test_fire_sends_first_uncached(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        src = w._source_panel.src_language()
        dst = w._source_panel.dst_language()
        w.set_prefetch_queue(["line A", "line B"])
        w._mt_cache[(w._preprocess("line A"), src, dst)] = ("done", "")
        w._fire_prefetch()
        sent = [c for c in w._sent if c != "halt"]
        assert len(sent) == 1
        assert sent[0][0] == w._preprocess("line B")

    def test_ready_caches_and_chains(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path, count=2)
        w.set_prefetch_queue(["line A", "line B", "line C"])
        w._fire_prefetch()
        assert [c[0] for c in w._sent] == [w._preprocess("line A")]

        w._prefetch_chunks[:] = ["trans A"]
        w._prefetch_thinking[:] = ["think A"]
        w._on_prefetch_ready("")

        src = w._source_panel.src_language()
        dst = w._source_panel.dst_language()
        assert w._mt_cache[(w._preprocess("line A"), src, dst)] == ("trans A", "think A")
        # Chained to line B
        assert [c[0] for c in w._sent] == [
            w._preprocess("line A"), w._preprocess("line B"),
        ]

        w._prefetch_chunks[:] = ["trans B"]
        w._prefetch_thinking[:] = []
        w._on_prefetch_ready("")
        # count=2 reached: line C not sent
        assert len(w._sent) == 2

    def test_prefetch_does_not_touch_panel_or_history(self, qapp, tmp_path):
        w = self._make_widget(qapp, tmp_path)
        w.set_prefetch_queue(["line A"])
        w._fire_prefetch()
        w._prefetch_chunks[:] = ["trans A"]
        w._on_prefetch_ready("")
        assert w._ollama_panel._output.toPlainText() == ""
        assert w._history.all_entries() == []
```

Append to `tests/test_combined_window.py::TestUpcomingSentences`:

```python
    def test_bridge_fills_prefetch_queue(self, win, qapp):
        content = _sep_file("%First\n%Second\n%Third\n")
        win._ta_widget.load_content(content, title="Test")
        assert win._agg_widget._prefetch_queue == ["Second", "Third"]
```

- [ ] **Step 2: Run tests, verify fail**

Run: `pytest tests/test_ollama.py::TestAggregatorPrefetch tests/test_combined_window.py::TestUpcomingSentences -q`
Expected: FAIL — `AttributeError: 'AggregatorWidget' object has no attribute '_ollama_prefetcher'` etc.

- [ ] **Step 3: Implement**

`ta/ui/aggregator_widget.py` — `__init__`, after the `_ollama_debounce` block:

```python
        self._prefetch_queue: list[str] = []
        self._prefetch_chunks: list[str] = []
        self._prefetch_thinking: list[str] = []
        self._prefetch_key: tuple[str, Language, Language] | None = None
        self._prefetch_done = 0
        _ollama_cfg = self._settings.translators.get("ollama")
        self._prefetch_count = _ollama_cfg.prefetch_count if _ollama_cfg else 0
        self._prefetch_idle = QTimer(self)
        self._prefetch_idle.setSingleShot(True)
        self._prefetch_idle.setInterval(
            _ollama_cfg.prefetch_idle_ms if _ollama_cfg else 3000
        )
        self._prefetch_idle.timeout.connect(self._fire_prefetch)
```

`_setup_ui` — initialize `self._ollama_prefetcher = None` next to `self._ollama_translator = None`, and inside the `if name == "ollama":` branch (after the panel is inserted, before `continue`):

```python
                if cfg.prefetch_count > 0:
                    # Second instance so prefetch never streams into the
                    # visible panel and can be halted independently.
                    self._ollama_prefetcher = _build_translator("ollama", cfg)
                    self._ollama_prefetcher.translation_started.connect(
                        self._on_prefetch_started
                    )
                    self._ollama_prefetcher.translation_chunk.connect(
                        self._prefetch_chunks.append
                    )
                    self._ollama_prefetcher.translation_thinking.connect(
                        self._prefetch_thinking.append
                    )
                    self._ollama_prefetcher.translation_ready.connect(
                        self._on_prefetch_ready
                    )
```

`_on_translate` — after `self._ollama_translator.halt()` add `self._stop_prefetch()`; in the cache-hit branch, after `show_result(...)` add `self._start_prefetch_idle()`:

```python
        # Abort any in-flight generation for the line we just left. Prefetch
        # too: Ollama serves one request at a time, and the foreground line
        # must never wait behind a background one.
        self._ollama_translator.halt()
        self._stop_prefetch()
        cached = self._mt_cache.get((text, src, dst))
        if cached is not None:
            self._ollama_debounce.stop()
            translation, thinking = cached
            self._ollama_panel.show_result(translation, text, src, dst, thinking)
            self._start_prefetch_idle()
        else:
            # Debounce so rapid line-skipping only translates where we settle.
            self._ollama_debounce.start()
```

`_on_ollama_ready` — add `self._start_prefetch_idle()` as the last line.

New section (after `_seed_mt_cache`):

```python
    # ------------------------------------------------------------------
    # Prefetch — background translation of upcoming lines
    # ------------------------------------------------------------------

    @Slot(list)
    def set_prefetch_queue(self, sentences: list) -> None:
        """Upcoming source lines, nearest first (from the TA widget)."""
        self._prefetch_queue = list(sentences)

    def _start_prefetch_idle(self) -> None:
        if self._ollama_prefetcher is None:
            return
        self._prefetch_done = 0
        self._prefetch_idle.start()

    def _stop_prefetch(self) -> None:
        self._prefetch_idle.stop()
        if self._ollama_prefetcher is not None:
            self._ollama_prefetcher.halt()

    def _fire_prefetch(self) -> None:
        if self._ollama_prefetcher is None or self._prefetch_done >= self._prefetch_count:
            return
        src = self._source_panel.src_language()
        dst = self._source_panel.dst_language()
        for raw in self._prefetch_queue[: self._prefetch_count]:
            text = self._preprocess(raw)
            if not text:
                continue
            key = (text, src, dst)
            if key in self._mt_cache:
                continue
            self._prefetch_key = key
            self._ollama_prefetcher.translate(text, src, dst)
            return

    def _on_prefetch_started(self) -> None:
        self._prefetch_chunks.clear()
        self._prefetch_thinking.clear()

    def _on_prefetch_ready(self, _ignored: str) -> None:
        text = "".join(self._prefetch_chunks)
        if text and self._prefetch_key is not None:
            self._mt_cache[self._prefetch_key] = (
                text, "".join(self._prefetch_thinking),
            )
        self._prefetch_key = None
        self._prefetch_done += 1
        self._fire_prefetch()
```

`translation_assistant/ui/combined_window.py` — `_connect_bridge`:

```python
    def _connect_bridge(self) -> None:
        self._ta_widget.source_sentence_changed.connect(
            self._agg_widget.translate_source
        )
        self._ta_widget.upcoming_sentences_changed.connect(
            self._agg_widget.set_prefetch_queue
        )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_ollama.py tests/test_combined_window.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ta/ui/aggregator_widget.py translation_assistant/ui/combined_window.py tests/test_ollama.py tests/test_combined_window.py
git commit -m "feat(aggregator): eager ollama prefetch of upcoming lines while idle"
```

---

### Task 6: Settings dialog — prefetch spinboxes

**Files:**
- Modify: `ta/ui/dialogs/settings_dialog.py` (ollama group in `_make_translators_tab` ~line 145, `_load` ~line 245, `apply()` ~line 285)
- Test: `tests/test_ollama.py` (extend `TestSettingsDialogOllamaGroup` or new class)

**Interfaces:**
- Consumes: `TranslatorConfig.prefetch_count/prefetch_idle_ms` (Task 1).
- Produces: dialog widgets `_ollama_prefetch_spin` (0–20) and `_ollama_prefetch_idle_spin` (1–60 s); `apply()` writes `prefetch_count` and `prefetch_idle_ms` (seconds × 1000).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ollama.py`:

```python
class TestSettingsDialogPrefetch:
    def _make_settings(self):
        from ta.config.settings import Settings, TranslatorConfig
        s = Settings()
        s.translators["ollama"] = TranslatorConfig(
            enabled=True, url="http://localhost:11434", model="m",
            system_prompt="p", prefetch_count=5, prefetch_idle_ms=7000,
        )
        return s

    def test_load_populates_spinboxes(self, qapp):
        from ta.ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._make_settings())
        assert dlg._ollama_prefetch_spin.value() == 5
        assert dlg._ollama_prefetch_idle_spin.value() == 7

    def test_apply_writes_config(self, qapp):
        from ta.ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._make_settings())
        dlg._ollama_prefetch_spin.setValue(10)
        dlg._ollama_prefetch_idle_spin.setValue(4)
        s = dlg.apply()
        assert s.translators["ollama"].prefetch_count == 10
        assert s.translators["ollama"].prefetch_idle_ms == 4000

    def test_defaults_when_unconfigured(self, qapp):
        from ta.config.settings import Settings
        from ta.ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(Settings())
        assert dlg._ollama_prefetch_spin.value() == 0
        assert dlg._ollama_prefetch_idle_spin.value() == 3
```

- [ ] **Step 2: Run tests, verify fail**

Run: `pytest tests/test_ollama.py::TestSettingsDialogPrefetch -q`
Expected: FAIL — `AttributeError: ... '_ollama_prefetch_spin'`.

- [ ] **Step 3: Implement**

`_make_translators_tab`, ollama branch, after the system prompt row:

```python
                self._ollama_prefetch_spin = QSpinBox()
                self._ollama_prefetch_spin.setRange(0, 20)
                self._ollama_prefetch_spin.setToolTip(
                    "Pre-translate this many upcoming lines while idle (0 = off)"
                )
                form.addRow("Prefetch lines ahead:", self._ollama_prefetch_spin)

                self._ollama_prefetch_idle_spin = QSpinBox()
                self._ollama_prefetch_idle_spin.setRange(1, 60)
                self._ollama_prefetch_idle_spin.setSuffix(" s")
                self._ollama_prefetch_idle_spin.setToolTip(
                    "Idle time after the current line finishes before prefetch starts"
                )
                form.addRow("Prefetch idle delay:", self._ollama_prefetch_idle_spin)
```

`_load`, inside the `if name == "ollama":` block:

```python
                self._ollama_prefetch_spin.setValue(cfg.prefetch_count if cfg else 0)
                self._ollama_prefetch_idle_spin.setValue(
                    round((cfg.prefetch_idle_ms if cfg else 3000) / 1000) or 1
                )
```

`apply()`, inside the `if name == "ollama":` block:

```python
                s.translators[name].prefetch_count = self._ollama_prefetch_spin.value()
                s.translators[name].prefetch_idle_ms = (
                    self._ollama_prefetch_idle_spin.value() * 1000
                )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_ollama.py -q`
Expected: all pass.

- [ ] **Step 5: Full suite + commit**

Run: `pytest -q`
Expected: all pass (~865+ tests).

```bash
git add ta/ui/dialogs/settings_dialog.py tests/test_ollama.py
git commit -m "feat(settings-ui): ollama prefetch count and idle delay controls"
```

---

## Notes for implementers

- Prefetch config is read at `AggregatorWidget` construction, like panel layout — changing it in the settings dialog takes effect on next launch. This matches existing behavior for panel/translator config.
- `_fire_prefetch` scans only `_prefetch_queue[:prefetch_count]` — the window is "next N lines", and `_prefetch_done` guards the per-idle-cycle budget.
- Prefetcher errors are silently dropped (no `translation_error` connection): the next idle cycle retries naturally.
- Update `CLAUDE.md` test count only if you touch that section anyway (not required).

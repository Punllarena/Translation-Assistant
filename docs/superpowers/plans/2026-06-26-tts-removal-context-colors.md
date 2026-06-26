# TTS Removal + Color-Coded Context Panels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the TTS stub entirely and add green/red background banding to the context review panels so translated and untranslated lines are visually distinct.

**Architecture:** `build_review_text` in `core.py` gains a third return value — a `color_ranges` list — tracking per-group translated status. `main_widget.py` unpacks it and applies `QTextCharFormat` backgrounds after every `setPlainText` on the context panels.

**Tech Stack:** Python 3.11+, PySide6 (`QTextCursor`, `QTextCharFormat`, `QColor`), pytest

## Global Constraints

- `core.py` must remain Qt-free (no PySide6 imports)
- All existing tests must pass after each task
- Activate venv before running any command: `source .venv/bin/activate`

---

### Task 1: TTS Removal

**Files:**
- Delete: `translation_assistant/tts.py`
- Modify: `translation_assistant/settings.py`
- Modify: `translation_assistant/main_widget.py`
- Modify: `translation_assistant/ui/combined_window.py`

**Interfaces:**
- Produces: nothing consumed by later tasks — this is pure deletion

- [ ] **Step 1: Delete `tts.py`**

```bash
rm translation_assistant/tts.py
```

- [ ] **Step 2: Remove `tts` and `tts_lang` from `settings.py`**

In `translation_assistant/settings.py`, remove the two `_DEFAULTS` entries and both properties.

Remove from `_DEFAULTS` dict (lines ~31-32):
```python
        "TTS": False,
        "TTSLang": 0,
```

Remove both property blocks (lines ~99-117):
```python
    # --- TTS enabled ---

    @property
    def tts(self) -> bool:
        return self._qs.value("TTS", self._DEFAULTS["TTS"], type=bool)

    @tts.setter
    def tts(self, value: bool) -> None:
        self._qs.setValue("TTS", value)

    # --- TTS language (0 = Japanese, 1 = Chinese) ---

    @property
    def tts_lang(self) -> int:
        return self._qs.value("TTSLang", self._DEFAULTS["TTSLang"], type=int)

    @tts_lang.setter
    def tts_lang(self, value: int) -> None:
        self._qs.setValue("TTSLang", value)
```

- [ ] **Step 3: Remove TTS actions, engine, and handlers from `main_widget.py`**

In `translation_assistant/main_widget.py`, remove the following blocks:

In `_build_actions` (lines ~259-267), remove:
```python
        self.action_tts_jp = QAction("Japanese", self)
        self.action_tts_jp.setCheckable(True)
        self.action_tts_jp.setEnabled(False)
        self.action_tts_jp.triggered.connect(self._on_toggle_tts_jp)

        self.action_tts_cn = QAction("Chinese", self)
        self.action_tts_cn.setCheckable(True)
        self.action_tts_cn.setEnabled(False)
        self.action_tts_cn.triggered.connect(self._on_toggle_tts_cn)
```

In `_load_initial_state` (line ~533), remove:
```python
        self._try_init_tts()
```

Remove the entire `_try_init_tts` method (lines ~562-576):
```python
    def _try_init_tts(self) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            for v in (voices or []):
                name = getattr(v, "name", "")
                if "ja" in name.lower() or "japanese" in name.lower() or "haruka" in name.lower():
                    self.action_tts_jp.setEnabled(True)
                elif "zh" in name.lower() or "chinese" in name.lower() or "huihui" in name.lower():
                    self.action_tts_cn.setEnabled(True)
            engine.stop()
            self._tts_engine = engine
        except Exception:
            self._tts_engine = None
```

Remove both TTS toggle handlers (lines ~1493-1509):
```python
    def _on_toggle_tts_jp(self) -> None:
        if self.action_tts_jp.isChecked():
            self.action_tts_cn.setChecked(False)
            self._settings.tts = True
            self._settings.tts_lang = 0
        else:
            self._settings.tts = False
        self._settings.save()

    def _on_toggle_tts_cn(self) -> None:
        if self.action_tts_cn.isChecked():
            self.action_tts_jp.setChecked(False)
            self._settings.tts = True
            self._settings.tts_lang = 1
        else:
            self._settings.tts = False
        self._settings.save()
```

- [ ] **Step 4: Remove TTS submenu from `combined_window.py`**

In `translation_assistant/ui/combined_window.py`, remove the TTS submenu block (lines ~113-117):
```python
        tts_menu = QMenu("Text-To-Speech", self)
        tts_menu.addAction(ta.action_tts_jp)
        tts_menu.addAction(ta.action_tts_cn)
        settings_menu.addMenu(tts_menu)
```

- [ ] **Step 5: Run full test suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all tests pass, no `AttributeError` for removed attributes.

- [ ] **Step 6: Commit**

```bash
git add -u
git commit -m "remove TTS stub and all references"
```

---

### Task 2: Extend `build_review_text` to return color ranges

**Files:**
- Modify: `translation_assistant/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Produces: `build_review_text(...) -> tuple[str, dict[int, tuple[int, int]], list[tuple[int, int, bool]]]`
  - Third element: `[(group_char_start, group_char_end, is_translated), ...]`

- [ ] **Step 1: Write two failing tests in `tests/test_core.py`**

Add inside `class TestBuildReviewText` (after the last existing test method):

```python
    def test_color_ranges_translated_group(self):
        raw = ["%Hello"]
        tl = ["こんにちは"]
        text, offsets, colors = build_review_text(raw, tl, 0, 0)
        assert len(colors) == 1
        start, end, is_translated = colors[0]
        assert is_translated is True
        assert start == 0
        assert end == len(text)

    def test_color_ranges_untranslated_group(self):
        raw = ["%Hello"]
        tl = [""]
        text, offsets, colors = build_review_text(raw, tl, 0, 0)
        assert len(colors) == 1
        _, _, is_translated = colors[0]
        assert is_translated is False
```

- [ ] **Step 2: Also update the 6 existing tests that use 2-value unpacking**

In `tests/test_core.py`, change each 2-value unpack to 3-value (using `_` for the colors):

| Line | Before | After |
|------|--------|-------|
| 316 | `text, offsets = build_review_text(raw, tl, 0, 0)` | `text, offsets, _ = build_review_text(raw, tl, 0, 0)` |
| 324 | `text, offsets = build_review_text(raw, tl, 0, 1)` | `text, offsets, _ = build_review_text(raw, tl, 0, 1)` |
| 334 | `text, _ = build_review_text(raw, tl, 0, 2)` | `text, _, _ = build_review_text(raw, tl, 0, 2)` |
| 341 | `_, offsets = build_review_text(raw, tl, 0, 1)` | `_, offsets, _ = build_review_text(raw, tl, 0, 1)` |
| 349 | `_, offsets = build_review_text(raw, tl, 0, 1)` | `_, offsets, _ = build_review_text(raw, tl, 0, 1)` |
| 366 | `text, offsets = build_review_text(raw, tl, 1, 2)` | `text, offsets, _ = build_review_text(raw, tl, 1, 2)` |

(Line 360 calls `build_review_text` without unpacking — leave it unchanged.)

- [ ] **Step 3: Run tests to confirm failures**

```bash
source .venv/bin/activate && pytest tests/test_core.py::TestBuildReviewText -v
```

Expected: `test_color_ranges_translated_group` and `test_color_ranges_untranslated_group` FAIL with `ValueError: not enough values to unpack`. The 6 updated existing tests also fail.

- [ ] **Step 4: Implement the new `build_review_text` in `core.py`**

Replace the body of `build_review_text` in `translation_assistant/core.py` with:

```python
def build_review_text(
    raw_lines: list[str],
    translated_lines: list[str],
    start: int,
    end: int,
) -> tuple[str, dict[int, tuple[int, int]], list[tuple[int, int, bool]]]:
    """
    Build the display string for reviewTop or reviewBottom.

    Consecutive lines starting with '$' are concatenated onto the same visual
    row as their preceding '%' line.  Their translations are appended below,
    space-separated.  Empty raw lines produce blank lines.

    Returns (display_text, offset_map, color_ranges) where
    offset_map[i] = (char_start, char_end) for line index i.
    color_ranges[i] = (group_start, group_end, is_translated) per visual group.
    The double-click handler uses strict `char_start < cursor_pos < char_end`
    to navigate — matching the VB linenumber comparison exactly.

    NOTE: does not mutate raw_lines (the VB original stripped % in-place).
    """
    parts: list[str] = []
    offset_map: dict[int, tuple[int, int]] = {}
    color_ranges: list[tuple[int, int, bool]] = []
    char_pos = 0
    count = start

    while count <= end:
        line = raw_lines[count]
        if line:
            group_start_off = char_pos
            # Group this line with any consecutive $-continuation lines
            group_size = 0
            while True:
                idx = count + group_size
                stripped = raw_lines[idx].replace("%", "").replace("$", "")
                start_off = char_pos
                parts.append(stripped)
                char_pos += len(stripped)
                offset_map[idx] = (start_off, char_pos)

                group_size += 1
                next_idx = count + group_size
                if (next_idx > len(raw_lines) - 1
                        or next_idx > end
                        or not raw_lines[next_idx].startswith("$")):
                    break

            # Newline after the raw block
            parts.append("\n")
            char_pos += 1

            # Translations for every line in the group, space-separated
            for x in range(group_size):
                t = translated_lines[count + x]
                parts.append(t + " ")
                char_pos += len(t) + 1

            parts.append("\n\n")
            char_pos += 2

            is_translated = all(
                bool(translated_lines[count + x].strip())
                for x in range(group_size)
            )
            color_ranges.append((group_start_off, char_pos, is_translated))

            count += group_size
        else:
            parts.append("\n")
            char_pos += 1
            count += 1

    return "".join(parts), offset_map, color_ranges
```

- [ ] **Step 5: Run tests to confirm all pass**

```bash
source .venv/bin/activate && pytest tests/test_core.py::TestBuildReviewText -v
```

Expected: all 9 tests (7 existing + 2 new) PASS.

- [ ] **Step 6: Run full suite to confirm no regressions**

```bash
source .venv/bin/activate && pytest -q
```

Expected: same pass count as after Task 1 (minus the 2 new tests now also passing).

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/core.py tests/test_core.py
git commit -m "extend build_review_text to return color ranges per visual group"
```

---

### Task 3: Apply color banding in `main_widget.py`

**Files:**
- Modify: `translation_assistant/main_widget.py`

**Interfaces:**
- Consumes: `build_review_text(...) -> tuple[str, dict[int, tuple[int, int]], list[tuple[int, int, bool]]]` (Task 2)

- [ ] **Step 1: Add `QColor` and `QTextCharFormat` to the Qt imports**

In `translation_assistant/main_widget.py`, update the `PySide6.QtGui` import line (currently line ~9):

```python
from PySide6.QtGui import QAction, QColor, QFont, QKeyEvent, QTextCharFormat, QTextCursor
```

- [ ] **Step 2: Add `_apply_review_colors` helper method**

Add this method to `TranslationAssistantWidget`, directly after `_update_tm_panel` (around line 800):

```python
    def _apply_review_colors(
        self, widget: "QTextEdit", ranges: list[tuple[int, int, bool]]
    ) -> None:
        if not ranges:
            return
        doc = widget.document()
        translated_color = QColor(100, 200, 100, 60)
        untranslated_color = QColor(220, 80, 80, 60)
        fmt = QTextCharFormat()
        for start, end, is_translated in ranges:
            fmt.setBackground(translated_color if is_translated else untranslated_color)
            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeCharFormat(fmt)
```

- [ ] **Step 3: Update `_finish_load` — bottom panel caller**

In `_finish_load`, find:
```python
        if p + 1 < n:
            bottom_text, self._bottom_map = build_review_text(
                raw_lines, translated_lines, p + 1, n - 1
            )
        else:
            bottom_text = ""
            self._bottom_map = {}
        self._review_bottom.setPlainText(bottom_text)
```

Replace with:
```python
        if p + 1 < n:
            bottom_text, self._bottom_map, _bottom_colors = build_review_text(
                raw_lines, translated_lines, p + 1, n - 1
            )
        else:
            bottom_text, self._bottom_map, _bottom_colors = "", {}, []
        self._review_bottom.setPlainText(bottom_text)
        self._apply_review_colors(self._review_bottom, _bottom_colors)
```

- [ ] **Step 4: Update `_finish_load` — top panel caller**

In `_finish_load`, find:
```python
        if p > 0:
            top_text, self._top_map = build_review_text(raw_lines, translated_lines, 0, p - 1)
            self._review_top.setPlainText(top_text)
```

Replace with:
```python
        if p > 0:
            top_text, self._top_map, _top_colors = build_review_text(
                raw_lines, translated_lines, 0, p - 1
            )
            self._review_top.setPlainText(top_text)
            self._apply_review_colors(self._review_top, _top_colors)
```

- [ ] **Step 5: Update `_update_ui_for_pointer` — top panel caller**

In `_update_ui_for_pointer`, find:
```python
        if p > 0:
            top_text, self._top_map = build_review_text(
                self._raw_lines, self._translated_lines, 0, p - 1
            )
        else:
            top_text, self._top_map = "", {}
        self._review_top.setPlainText(top_text)
        self._review_top.moveCursor(QTextCursor.MoveOperation.End)
```

Replace with:
```python
        if p > 0:
            top_text, self._top_map, _top_colors = build_review_text(
                self._raw_lines, self._translated_lines, 0, p - 1
            )
        else:
            top_text, self._top_map, _top_colors = "", {}, []
        self._review_top.setPlainText(top_text)
        self._apply_review_colors(self._review_top, _top_colors)
        self._review_top.moveCursor(QTextCursor.MoveOperation.End)
```

- [ ] **Step 6: Update `_update_ui_for_pointer` — bottom panel caller**

In `_update_ui_for_pointer`, find:
```python
        if p < n - 1:
            bottom_text, self._bottom_map = build_review_text(
                self._raw_lines, self._translated_lines, p + 1, n - 1
            )
        else:
            bottom_text, self._bottom_map = "", {}
        self._review_bottom.setPlainText(bottom_text)
```

Replace with:
```python
        if p < n - 1:
            bottom_text, self._bottom_map, _bottom_colors = build_review_text(
                self._raw_lines, self._translated_lines, p + 1, n - 1
            )
        else:
            bottom_text, self._bottom_map, _bottom_colors = "", {}, []
        self._review_bottom.setPlainText(bottom_text)
        self._apply_review_colors(self._review_bottom, _bottom_colors)
```

- [ ] **Step 7: Run full test suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all tests pass.

- [ ] **Step 8: Manual visual check**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

Open any document with a mix of translated and untranslated lines. Verify:
- Context Above / Context Below panels show green-tinted backgrounds on translated groups
- Untranslated groups show red-tinted backgrounds
- Double-click navigation still jumps to the correct line

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/main_widget.py
git commit -m "add green/red color banding to context review panels"
```

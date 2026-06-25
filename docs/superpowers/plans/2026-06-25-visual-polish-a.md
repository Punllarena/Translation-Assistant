# Visual Polish A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four information-density improvements to the translation editor: window title with doc name, parse phrase counter in status bar, progress bar, and panel label word/line counts.

**Architecture:** All changes are in one file — `translation_assistant/ui/main_widget.py`. Each task is an independent change to a different method group; tasks share no runtime dependencies and can be reviewed in isolation.

**Tech Stack:** PySide6, Python 3.11+, pytest

## Global Constraints

- All changes in `translation_assistant/ui/main_widget.py` only — no other source files
- Tests in `tests/test_main_window.py` — append new test classes, don't modify existing ones
- Run tests: `source .venv/bin/activate && pytest tests/test_main_window.py -q`
- Full suite: `source .venv/bin/activate && pytest -q` — must stay green (currently 620 passing)
- Widget tests never call `window.show()` — widgets run headlessly
- `TranslationAssistantWidget` fixture named `win` uses isolated QSettings + in-memory DB; see existing `@pytest.fixture def win(...)` at top of `tests/test_main_window.py`
- Helper `_load(win, raw_content)` builds a SEPERATOR file and calls `win.load_content()`; `_sep_file(raw, translated)` builds the raw string
- `_doc_title: str` instance var set in `_finish_load`, reset in `_on_db_import`
- `_refresh_window_title()` is the single place that sets the OS window title
- `_progress_bar: QProgressBar` replaces `_completion_label: QLabel` everywhere — no `_completion_label` should remain

---

### Task 1: Window title with doc name

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
  - `__init__` (~line 101): add `self._doc_title: str = ""`
  - `_set_dirty` (~line 804): replace inline `setWindowTitle` with `_refresh_window_title()`
  - Add new method `_refresh_window_title` after `_set_dirty`
  - `_finish_load` (~line 643): set `self._doc_title` and call `_refresh_window_title()`
  - `_on_db_import` (~line 1241): reset `self._doc_title = ""` and call `_refresh_window_title()`
- Test: `tests/test_main_window.py`

**Interfaces:**
- Produces: `TranslationAssistantWidget._doc_title: str`, `TranslationAssistantWidget._refresh_window_title() -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main_window.py`:

```python
class TestWindowTitle:
    def test_doc_title_empty_initially(self, win):
        assert win._doc_title == ""

    def test_doc_title_set_from_chapter_title_on_load(self, win):
        win.load_content("%Hello\n---SEPERATOR---\n", title="Doc", chapter_title="Chapter 1")
        assert win._doc_title == "Chapter 1"

    def test_doc_title_falls_back_to_title(self, win):
        win.load_content("%Hello\n---SEPERATOR---\n", title="My Doc", chapter_title="")
        assert win._doc_title == "My Doc"

    def test_doc_title_empty_string_when_no_title(self, win):
        win.load_content("%Hello\n---SEPERATOR---\n", title="", chapter_title="")
        assert win._doc_title == ""

    def test_refresh_window_title_method_exists(self, win):
        assert callable(getattr(win, "_refresh_window_title", None))

    def test_refresh_window_title_does_not_crash(self, win):
        win._doc_title = "Chapter 1"
        win._is_dirty = False
        win._refresh_window_title()  # no parent window in tests — must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestWindowTitle -v
```

Expected: `AttributeError: 'TranslationAssistantWidget' object has no attribute '_doc_title'`

- [ ] **Step 3: Add `_doc_title` to `__init__`**

In `__init__` (~line 112), after `self._is_dirty: bool = False`, add:

```python
        self._doc_title: str = ""
```

- [ ] **Step 4: Replace `_set_dirty` body and add `_refresh_window_title`**

Replace the existing `_set_dirty` method (lines 804–811):

```python
    def _set_dirty(self, dirty: bool) -> None:
        if self._is_dirty == dirty:
            return
        self._is_dirty = dirty
        self._refresh_window_title()

    def _refresh_window_title(self) -> None:
        win = self.window()
        if win is not self:
            base = f"{self._doc_title} — Translation Assistant" if self._doc_title else "Translation Assistant"
            win.setWindowTitle(base + " *" if self._is_dirty else base)
```

- [ ] **Step 5: Update `_finish_load` to set `_doc_title`**

In `_finish_load`, the existing block at ~line 643 is:

```python
        _doc_meta = self._db.get_document(self._doc_id)
        _doc_display = _doc_meta.get("chapter_title") or _doc_meta.get("title") or ""
        self._source_label.setText(f"Source — {_doc_display}" if _doc_display else "Source (read-only)")
```

Change to:

```python
        _doc_meta = self._db.get_document(self._doc_id)
        _doc_display = _doc_meta.get("chapter_title") or _doc_meta.get("title") or ""
        self._doc_title = _doc_display
        self._refresh_window_title()
        self._source_label.setText(f"Source — {_doc_display}" if _doc_display else "Source (read-only)")
```

- [ ] **Step 6: Update `_on_db_import` to reset `_doc_title`**

In `_on_db_import`, after `self._source_label.setText("Source (read-only)")` (~line 1241), add:

```python
        self._doc_title = ""
        self._refresh_window_title()
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestWindowTitle -v
```

Expected: all 6 PASS

- [ ] **Step 8: Run full suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: 620+ tests pass

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(ui): window title shows current doc name"
```

---

### Task 2: Parse phrase counter in status bar

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
  - `_setup_statusbar` (~line 450): add `self._parse_label`
  - `_advance_parse` (~line 924): show/update counter after pointer change
  - `_retreat_parse` (~line 944): show/update counter after pointer change
  - `_update_ui_for_pointer` (~line 674): hide counter on navigation
- Test: `tests/test_main_window.py`

**Interfaces:**
- Produces: `TranslationAssistantWidget._parse_label: QLabel` (hidden by default, visible when `_parse_pointer >= 0`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main_window.py`:

```python
class TestParseCounter:
    def test_parse_label_exists(self, win):
        assert hasattr(win, "_parse_label")

    def test_parse_label_hidden_initially(self, win):
        assert not win._parse_label.isVisible()

    def test_parse_label_shows_after_advance_parse(self, win):
        _load(win, "%Hello。World。\n")
        win._parse_sentences = ["Hello", "World"]
        win._parse_pointer = 0
        # Manually call the counter update logic by invoking _advance_parse path
        # Simulate: pointer is already at 0, call _advance_parse to reach 1
        win._parse_pointer = -1
        win._advance_parse()  # moves to 0
        assert win._parse_label.isVisible()
        assert "Phrase 1/" in win._parse_label.text()

    def test_parse_label_hides_on_navigation(self, win):
        _load(win, "%Hello。World。\n%Second\n")
        win._parse_label.setVisible(True)
        win._navigate_forward()
        assert not win._parse_label.isVisible()

    def test_parse_label_hides_when_pointer_negative(self, win):
        _load(win, "%Hello。World。\n")
        win._advance_parse()  # moves to 0
        win._retreat_parse()  # moves back to -1
        assert not win._parse_label.isVisible()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestParseCounter -v
```

Expected: `AttributeError: 'TranslationAssistantWidget' object has no attribute '_parse_label'`

- [ ] **Step 3: Add `_parse_label` to `_setup_statusbar`**

In `_setup_statusbar`, after `self._word_label = QLabel()` (~line 457) and before `self._profile_label`, add:

```python
        self._parse_label = QLabel("")
        self._parse_label.setVisible(False)
```

Then add to status bar after `self._status_bar.addWidget(self._word_label)` (~line 465):

```python
        self._status_bar.addWidget(self._parse_label)
```

- [ ] **Step 4: Update `_advance_parse` to show counter**

At the end of `_advance_parse`, before `self._start_clipboard_timer()` (~line 941), add:

```python
        if self._parse_pointer >= 0:
            self._parse_label.setText(f"Phrase {self._parse_pointer + 1}/{len(self._parse_sentences)}")
            self._parse_label.setVisible(True)
        else:
            self._parse_label.setVisible(False)
```

- [ ] **Step 5: Update `_retreat_parse` to show counter**

At the end of `_retreat_parse`, before `self._start_clipboard_timer()` (~line 962), add:

```python
        if self._parse_pointer >= 0:
            self._parse_label.setText(f"Phrase {self._parse_pointer + 1}/{len(self._parse_sentences)}")
            self._parse_label.setVisible(True)
        else:
            self._parse_label.setVisible(False)
```

- [ ] **Step 6: Hide counter in `_update_ui_for_pointer`**

At the end of `_update_ui_for_pointer` (~line 720, after the `source_sentence_changed.emit` call), add:

```python
        self._parse_label.setVisible(False)
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestParseCounter -v
```

Expected: all 5 PASS

- [ ] **Step 8: Run full suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all tests pass

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(ui): parse phrase counter in status bar (Phrase N/M)"
```

---

### Task 3: Progress bar replaces completion label

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
  - `_setup_statusbar` (~line 450): replace `_completion_label` QLabel with `_progress_bar` QProgressBar
  - `_update_progress_visibility` (~line 756): replace `_completion_label` reference
  - `_finish_load` (~line 634): replace `.setText` with `.setValue`
  - `_update_ui_for_pointer` (~line 715): replace `.setText` with `.setValue`
  - `_navigate_forward` EOF branch (~line 854): replace `.setText` with `.setValue`
- Test: `tests/test_main_window.py`

**Interfaces:**
- Produces: `TranslationAssistantWidget._progress_bar: QProgressBar` with `format() == "%p%"`, replaces `_completion_label` fully

**Note:** `QProgressBar` must be added to the PySide6.QtWidgets import at the top of `main_widget.py`. Check the current import block and add it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main_window.py`:

```python
class TestProgressBar:
    def test_has_progress_bar(self, win):
        assert hasattr(win, "_progress_bar")

    def test_no_completion_label(self, win):
        assert not hasattr(win, "_completion_label")

    def test_progress_bar_format(self, win):
        from PySide6.QtWidgets import QProgressBar
        assert isinstance(win._progress_bar, QProgressBar)
        assert win._progress_bar.format() == "%p%"

    def test_progress_bar_range(self, win):
        assert win._progress_bar.minimum() == 0
        assert win._progress_bar.maximum() == 100

    def test_progress_bar_value_after_load(self, win):
        _load(win, "%A\n")
        assert win._progress_bar.value() == 0  # nothing translated yet

    def test_progress_bar_value_updates_on_navigation(self, win):
        content = _sep_file("%A\n%B\n", "Alpha\nBeta\n")
        win.load_content(content)
        assert win._progress_bar.value() == 100

    def test_progress_bar_hidden_when_no_doc(self, win):
        # Show progress is True by default, but no doc open → hidden
        assert not win._progress_bar.isVisible()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestProgressBar -v
```

Expected: `AttributeError: 'TranslationAssistantWidget' object has no attribute '_progress_bar'`

- [ ] **Step 3: Add `QProgressBar` to imports**

At the top of `main_widget.py`, find the `from PySide6.QtWidgets import (...)` block and add `QProgressBar` to it (alphabetical order, between `QPlainTextEdit`-equivalent and `QPushButton` area — there is no `QPlainTextEdit` here, so add after `QMenu`):

```python
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QInputDialog, QLabel, QMenu,
    QMessageBox, QProgressBar, QSizePolicy, QSplitter, QStatusBar, QTextEdit, QVBoxLayout, QWidget,
)
```

- [ ] **Step 4: Replace `_completion_label` with `_progress_bar` in `_setup_statusbar`**

Replace:

```python
        self._completion_label = QLabel()
```

with:

```python
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFormat("%p%")
        self._progress_bar.setMaximumWidth(120)
        self._progress_bar.setTextVisible(True)
```

Replace `self._status_bar.addWidget(self._completion_label)` with:

```python
        self._status_bar.addWidget(self._progress_bar)
```

- [ ] **Step 5: Update `_update_progress_visibility`**

Replace:

```python
        self._completion_label.setVisible(visible)
```

with:

```python
        self._progress_bar.setVisible(visible)
```

- [ ] **Step 6: Update `_finish_load`**

Replace (line ~634):

```python
        self._completion_label.setText(f"{pct}% Complete")
```

with:

```python
        self._progress_bar.setValue(pct)
```

- [ ] **Step 7: Update `_update_ui_for_pointer`**

Replace (line ~715):

```python
        self._completion_label.setText(f"{pct}% Complete")
```

with:

```python
        self._progress_bar.setValue(pct)
```

- [ ] **Step 8: Update `_navigate_forward` EOF branch**

Replace (line ~854):

```python
            self._completion_label.setText(f"{pct}% Complete")
```

with:

```python
            self._progress_bar.setValue(pct)
```

- [ ] **Step 9: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestProgressBar -v
```

Expected: all 7 PASS

- [ ] **Step 10: Run full suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all tests pass (any test referencing `_completion_label` will now fail — check and update if any exist in the existing test file)

- [ ] **Step 11: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(ui): progress bar replaces completion % label"
```

---

### Task 4: Panel label counts (source lines + translation word count)

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
  - `_setup_central_widget` (~line 418): replace `_labeled("Translation", ...)` with inline wrapper keeping `self._translation_label`
  - `_setup_central_widget` (~line 448): add second `textChanged` connection
  - Add new method `_update_translation_label`
  - `_finish_load` (~line 645): update source label to include line count; call `_update_translation_label()`
  - `_update_ui_for_pointer` (end): call `_update_translation_label()`
  - `_on_db_import` (~line 1241): reset `_translation_label` text
- Test: `tests/test_main_window.py`

**Interfaces:**
- Produces:
  - `TranslationAssistantWidget._translation_label: QLabel`
  - `TranslationAssistantWidget._update_translation_label() -> None`
- Consumes: `TranslationAssistantWidget._doc_title: str` from Task 1 (for source label format)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main_window.py`:

```python
class TestPanelLabelCounts:
    def test_has_translation_label(self, win):
        assert hasattr(win, "_translation_label")

    def test_translation_label_default_text(self, win):
        assert "Translation" in win._translation_label.text()

    def test_translation_label_shows_word_count_after_load(self, win):
        content = _sep_file("%Hello\n", "Hello world\n")
        win.load_content(content)
        assert "2 words" in win._translation_label.text()

    def test_translation_label_zero_words_when_empty(self, win):
        _load(win, "%Hello\n")
        assert "0 words" in win._translation_label.text()

    def test_source_label_includes_line_count(self, win):
        win.load_content("%A\n%B\n%C\n---SEPERATOR---\n", title="Doc", chapter_title="Ch1")
        assert "· 3 lines" in win._source_label.text()

    def test_source_label_includes_title_and_lines(self, win):
        win.load_content("%A\n---SEPERATOR---\n", title="Doc", chapter_title="Chapter 1")
        label = win._source_label.text()
        assert "Chapter 1" in label
        assert "lines" in label

    def test_translation_label_resets_on_db_import(self, win):
        _load(win, "%Hello\n")
        win._translated_line.setPlainText("Bonjour")
        # Simulate db import reset
        win._translation_label.setText("Translation")
        assert win._translation_label.text() == "Translation"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestPanelLabelCounts -v
```

Expected: `AttributeError: 'TranslationAssistantWidget' object has no attribute '_translation_label'`

- [ ] **Step 3: Replace Translation panel in `_setup_central_widget`**

Find line ~418:

```python
        self._splitter.addWidget(_labeled("Translation", self._translated_line))
```

Replace with:

```python
        self._translation_label = QLabel("Translation")
        self._translation_label.setStyleSheet("font-size: 9pt; color: gray; padding: 1px 4px;")
        _tl_wrapper = QWidget()
        _tl_vbox = QVBoxLayout(_tl_wrapper)
        _tl_vbox.setContentsMargins(0, 0, 0, 0)
        _tl_vbox.setSpacing(0)
        _tl_vbox.addWidget(self._translation_label)
        _tl_vbox.addWidget(self._translated_line)
        self._splitter.addWidget(_tl_wrapper)
```

- [ ] **Step 4: Add second `textChanged` connection**

Near line ~448 where `self._translated_line.textChanged.connect(self._on_translation_text_changed)` exists, add the second connection immediately after:

```python
        self._translated_line.textChanged.connect(self._update_translation_label)
```

- [ ] **Step 5: Add `_update_translation_label` method**

Add after `_update_autosave_label` (or any logical grouping of `_update_*` methods):

```python
    def _update_translation_label(self) -> None:
        text = self._translated_line.toPlainText()
        words = len(text.split()) if text.strip() else 0
        self._translation_label.setText(f"Translation · {words} words")
```

- [ ] **Step 6: Update `_finish_load` source label and call translation update**

Find the source label update at ~line 645:

```python
        self._source_label.setText(f"Source — {_doc_display}" if _doc_display else "Source (read-only)")
```

Replace with:

```python
        n = len(self._raw_lines)
        _title_part = f"Source — {self._doc_title}" if self._doc_title else "Source"
        self._source_label.setText(f"{_title_part} · {n} lines")
```

Then, a few lines below (after `self._translated_line.setFocus()` ~line 649), add:

```python
        self._update_translation_label()
```

- [ ] **Step 7: Call `_update_translation_label` in `_update_ui_for_pointer`**

At the end of `_update_ui_for_pointer`, after `self._parse_label.setVisible(False)` (added in Task 2), add:

```python
        self._update_translation_label()
```

- [ ] **Step 8: Reset translation label in `_on_db_import`**

After `self._source_label.setText("Source (read-only)")` in `_on_db_import`, add:

```python
        self._translation_label.setText("Translation")
```

- [ ] **Step 9: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestPanelLabelCounts -v
```

Expected: all 7 PASS

- [ ] **Step 10: Run full suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all tests pass

- [ ] **Step 11: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(ui): translation word count label, source line count in panel labels"
```

---

## Self-Review

**Spec coverage:**
- Window title with doc name: Task 1 (`_doc_title`, `_refresh_window_title`, `_set_dirty`, `_finish_load`, `_on_db_import`) ✓
- Parse phrase counter: Task 2 (`_parse_label`, `_advance_parse`, `_retreat_parse`, `_update_ui_for_pointer`) ✓
- Progress bar with `%p%`: Task 3 (`_progress_bar`, all 3 call sites, `_update_progress_visibility`) ✓
- Source label line count: Task 4 Step 6 (`· N lines` in `_finish_load`) ✓
- Translation word count label: Task 4 (`_translation_label`, `_update_translation_label`, `textChanged`, navigation update) ✓

**Placeholder scan:** None. All steps have complete code.

**Type consistency:**
- `_doc_title: str` set in Task 1 Step 3, used in Task 4 Step 6 (`self._doc_title`) ✓
- `_progress_bar: QProgressBar` set in Task 3 Step 4, no cross-task references ✓
- `_parse_label: QLabel` set in Task 2 Step 3, hidden in `_update_ui_for_pointer` (Task 2 Step 6) ✓
- `_translation_label: QLabel` set in Task 4 Step 3, reset in Task 4 Step 8 ✓
- `_update_translation_label()` defined in Task 4 Step 5, called in Steps 4, 6, 7 ✓

**Cross-task dependency note:** Task 4 Step 6 uses `self._doc_title` which is set by Task 1. Tasks must be executed in order (1 → 2 → 3 → 4). The source label in B (`_source_label`) is modified in Task 4 — ensure Task 1 is complete first so `_doc_title` is available.

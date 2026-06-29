# UI Overhaul Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Phase 2 of the UI modernisation: tabbed dictionary panel, conversation-style context display, Copy button on MT panels, status bar redesign, and button/icon polish.

**Source spec:** `docs/superpowers/ui-overhaul.md` — Phase 2 items only.

**Tech Stack:** PySide6, pytest, QSS

## Global Constraints

- All existing tests must pass after each task
- Activate venv before running any command: `source .venv/bin/activate`
- Run tests with: `pytest tests/ -q`
- No new pip dependencies (icon integration uses Unicode, not qtawesome)
- Do not touch `translation_assistant/ui/main_window.py` (legacy — not launched)

---

## Task Overview

| # | Task | Files |
|---|------|-------|
| 1 | Tabbed dictionary | `ta/ui/panels_container.py` |
| 2 | MT panel Copy button | `ta/ui/translation_panel.py` |
| 3 | Status bar redesign | `translation_assistant/ui/main_widget.py` |
| 4 | Conversation-style context separators | `translation_assistant/core.py` |
| 5 | Button/icon polish | `ta/ui/source_panel.py` |

---

### Task 1: Tabbed dictionary

**Files:**
- Modify: `ta/ui/panels_container.py`

**What this task does:**

Replaces the 2-column `QSplitter` grid in `PanelsContainer` with a `QTabWidget`. Each `TranslationPanel` becomes a tab. Public interface (`add_panel`, `remove_panel`, `translate_all`, `set_languages`) is preserved. `save_layout`/`restore_layout` saves the current tab index instead of splitter sizes (backward-compatible: existing `layout.json` files with splitter data are silently ignored).

**Interfaces consumed:**
- `panel.translator_name` used as tab label
- `AggregatorWidget` calls `add_panel`, `translate_all`, `set_languages`, `save_layout`, `restore_layout` — all preserved

- [ ] **Step 1: Write failing tests**

Create `tests/test_panels_container.py`:

```python
import pytest

@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    return app

@pytest.fixture
def container(qapp):
    from ta.ui.panels_container import PanelsContainer
    return PanelsContainer()

class FakeTranslator:
    name = "FakeEngine"
    translation_ready = None
    translation_error = None
    translation_started = None
    translation_chunk = None

    def can_translate(self, src, dst):
        return True

    def translate(self, text, src, dst):
        pass


def make_panel(name="FakeEngine"):
    from unittest.mock import MagicMock
    from PySide6.QtCore import Signal, QObject

    class FakeSig(QObject):
        sig = Signal(str)

    s = FakeSig()
    translator = MagicMock()
    translator.name = name
    translator.translation_ready = s.sig
    translator.translation_error = s.sig
    translator.translation_started = s.sig
    translator.translation_chunk = s.sig
    from ta.ui.translation_panel import TranslationPanel
    return TranslationPanel(translator)


def test_uses_tab_widget(container):
    from PySide6.QtWidgets import QTabWidget
    assert isinstance(container._tab_widget, QTabWidget)


def test_add_panel_creates_tab(container):
    panel = make_panel("DeepL")
    container.add_panel(panel)
    assert container._tab_widget.count() == 1
    assert container._tab_widget.tabText(0) == "DeepL"


def test_add_two_panels(container):
    container.add_panel(make_panel("DeepL"))
    container.add_panel(make_panel("Google"))
    assert container._tab_widget.count() == 2


def test_remove_panel(container):
    container.add_panel(make_panel("DeepL"))
    container.add_panel(make_panel("Google"))
    container.remove_panel("DeepL")
    assert container._tab_widget.count() == 1
    assert container._tab_widget.tabText(0) == "Google"


def test_save_restore_layout(container):
    container.add_panel(make_panel("DeepL"))
    container.add_panel(make_panel("Google"))
    container._tab_widget.setCurrentIndex(1)
    layout = container.save_layout()
    container._tab_widget.setCurrentIndex(0)
    container.restore_layout(layout)
    assert container._tab_widget.currentIndex() == 1


def test_restore_layout_with_old_splitter_data(container):
    """Backward compat: old layout.json with splitter keys is silently ignored."""
    container.add_panel(make_panel("DeepL"))
    old_data = {"horizontal": [300, 300], "col0": [200], "col1": []}
    container.restore_layout(old_data)  # must not raise
    assert container._tab_widget.currentIndex() == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_panels_container.py -q
```

Expected: all 7 tests fail (no `_tab_widget` attribute).

- [ ] **Step 3: Rewrite `panels_container.py`**

Replace the entire file:

```python
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QSizePolicy

from ta.ui.translation_panel import TranslationPanel
from ta.config.languages import Language


class PanelsContainer(QWidget):
    """Tabbed container of TranslationPanels — one tab per translator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels: list[TranslationPanel] = []

        self._tab_widget = QTabWidget()
        self._tab_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tab_widget)

    def add_panel(self, panel: TranslationPanel) -> None:
        self._panels.append(panel)
        self._tab_widget.addTab(panel, panel.translator_name)

    def remove_panel(self, name: str) -> None:
        for i, panel in enumerate(self._panels):
            if panel.translator_name == name:
                self._tab_widget.removeTab(i)
                self._panels.pop(i)
                break

    def translate_all(self, text: str, src: Language, dst: Language) -> None:
        for panel in self._panels:
            panel.translate(text, src, dst)

    def set_languages(self, src: Language, dst: Language) -> None:
        for panel in self._panels:
            panel.set_languages(src, dst)

    def save_layout(self) -> dict:
        return {"tab_index": self._tab_widget.currentIndex()}

    def restore_layout(self, data: dict) -> None:
        idx = data.get("tab_index", 0)
        if isinstance(idx, int) and 0 <= idx < self._tab_widget.count():
            self._tab_widget.setCurrentIndex(idx)
```

- [ ] **Step 4: Run all tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass including the 7 new ones.

- [ ] **Step 5: Run the app and verify**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

Verify:
- Aggregator right panel shows tabs (DeepL, Google, etc.) instead of side-by-side grid
- Clicking a tab switches the active translator panel
- Tab selection persists after close/reopen

- [ ] **Step 6: Commit**

```bash
git add ta/ui/panels_container.py tests/test_panels_container.py
git commit -m "feat(aggregator): replace 2-col splitter grid with tabbed dictionary panel"
```

---

### Task 2: MT panel Copy button

**Files:**
- Modify: `ta/ui/translation_panel.py`

**What this task does:**

Adds a `[ ⎘ ]` Copy button to each `TranslationPanel` title bar. Copies the panel's current output text to the system clipboard. The output is already read-only; this is the only new interactive control.

- [ ] **Step 1: Add Copy button to `_setup_ui` in `translation_panel.py`**

Find the title bar section (after `_translate_btn` is added):

```python
        self._translate_btn = QPushButton("▶")
        self._translate_btn.setObjectName("EngineRunBtn")
        self._translate_btn.setFixedWidth(28)
        self._translate_btn.setToolTip(f"Translate with {self._translator.name}")
        self._translate_btn.clicked.connect(self._on_single_translate)
        title_bar.addWidget(self._translate_btn)
```

Add after it (still inside `_setup_ui`, before `layout.addLayout(title_bar)`):

```python
        self._copy_btn = QPushButton("⎘")
        self._copy_btn.setObjectName("EngineCopyBtn")
        self._copy_btn.setFixedWidth(28)
        self._copy_btn.setToolTip("Copy translation to clipboard")
        self._copy_btn.clicked.connect(self._on_copy)
        title_bar.addWidget(self._copy_btn)
```

- [ ] **Step 2: Add `_on_copy` method**

Add after `_on_single_translate`:

```python
    def _on_copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        text = self._output.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
```

- [ ] **Step 3: Run all tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 4: Run the app and verify**

Verify Copy button appears in each translator panel title bar and copies output text.

- [ ] **Step 5: Commit**

```bash
git add ta/ui/translation_panel.py
git commit -m "feat(aggregator): add Copy button to MT translation panels"
```

---

### Task 3: Status bar redesign

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`

**What this task does:**

Two targeted changes to the status bar:

1. **"Page N/N" format:** Change `_line_label` text from `"Line: N/N"` → `"Page N/N"` (two setText call sites).
2. **"✓ Autosaved X min ago":** Replace the 2-second flash `_filesaved_label` with a persistent display that shows time since last save. Tracks `_last_save_time` (monotonic float). A 60-second tick timer updates the relative-time label. Shows "✓ Autosaved just now" immediately after save, then "✓ Autosaved 1m ago", "✓ Autosaved 2m ago", etc.

No new status bar widgets are added or removed; this is label text changes only.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_main_window.py` at end of `TestInstantiation`:

```python
def test_line_label_says_page_format(self, win, tmp_settings, qapp):
    """After loading a doc, line label uses Page N/N format."""
    # This tests the format string — we verify the attribute and its content
    # after a navigate call would set it. Just check the label exists and
    # that it does NOT start with "Line:" initially (empty doc state).
    assert not win._line_label.text().startswith("Line:")

def test_has_last_save_time(self, win):
    assert hasattr(win, "_last_save_time")

def test_has_autosave_tick_timer(self, win):
    from PySide6.QtCore import QTimer
    assert isinstance(win._autosave_tick_timer, QTimer)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestInstantiation -q
```

Expected: 3 new tests fail.

- [ ] **Step 3: Add `_last_save_time` and `_autosave_tick_timer`**

In `_setup_timers` (or wherever `_filesaved_timer` is initialised — around line 541), add after the `_filesaved_timer` block:

```python
        self._last_save_time: float = 0.0
        self._autosave_tick_timer = QTimer(self)
        self._autosave_tick_timer.setInterval(60_000)
        self._autosave_tick_timer.timeout.connect(self._update_filesaved_label)
```

- [ ] **Step 4: Replace `_filesaved_timer` clear logic with `_update_filesaved_label`**

Remove the `_filesaved_timer` single-shot timer and its timeout connect (the one that calls `self._filesaved_label.setText("")`). Add instead:

```python
    def _update_filesaved_label(self) -> None:
        if self._last_save_time == 0.0:
            self._filesaved_label.setText("")
            return
        import time
        elapsed_m = int((time.monotonic() - self._last_save_time) / 60)
        if elapsed_m < 1:
            self._filesaved_label.setText("✓ Autosaved just now")
        else:
            self._filesaved_label.setText(f"✓ Autosaved {elapsed_m}m ago")
```

- [ ] **Step 5: Update `_save_to_db` to record save time**

Find `_save_to_db` (around line 720):

```python
    def _save_to_db(self) -> None:
        if self._doc_id is None:
            return
        self._db.save_lines(self._doc_id, self._lines_as_db_rows())
        self._filesaved_label.setText("File saved....")
        self._filesaved_timer.start()
```

Replace with:

```python
    def _save_to_db(self) -> None:
        if self._doc_id is None:
            return
        import time
        self._db.save_lines(self._doc_id, self._lines_as_db_rows())
        self._last_save_time = time.monotonic()
        self._update_filesaved_label()
        self._autosave_tick_timer.start()
```

- [ ] **Step 6: Change "Line:" → "Page" in `setText` calls**

There are two call sites. Find both occurrences of:

```python
        self._line_label.setText(f"Line: {p + 1}/{n}")
```

Replace both with:

```python
        self._line_label.setText(f"Page {p + 1}/{n}")
```

- [ ] **Step 7: Run all tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 8: Run the app and verify**

- Status bar shows "Page N/N" instead of "Line: N/N"
- After navigating and saving: "✓ Autosaved just now" appears and persists
- After 1 minute: label updates to "✓ Autosaved 1m ago"

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/main_widget.py
git commit -m "feat(status_bar): Page N/N format, persistent autosaved timestamp label"
```

---

### Task 4: Conversation-style context separators

**Files:**
- Modify: `translation_assistant/core.py`

**What this task does:**

Adds a horizontal separator line between context entries in `build_review_text`. Currently entries are separated only by `\n\n`; this appends `"─" * 30 + "\n"` after each group's translation block, giving clear visual breaks in the `ReviewTextEdit`.

The `offset_map` (character positions for double-click navigation) is unaffected: source-line offsets are recorded before any translation or separator text is appended, and `char_pos` continues to accumulate correctly for subsequent groups.

- [ ] **Step 1: Verify existing test coverage**

```bash
source .venv/bin/activate && pytest tests/test_core.py -k "review" -q
```

Note how many `build_review_text` tests exist. These will serve as regression guard.

- [ ] **Step 2: Modify `build_review_text` in `core.py`**

Find the group-level block (after `parts.append("\n\n")` and `char_pos += 2`):

```python
            parts.append("\n\n")
            char_pos += 2

            is_translated = all(
```

Add the separator **between** `char_pos += 2` and `is_translated = all(`:

```python
            parts.append("\n\n")
            char_pos += 2

            sep = "─" * 30 + "\n"
            parts.append(sep)
            char_pos += len(sep)

            is_translated = all(
```

- [ ] **Step 3: Update tests that assert exact `build_review_text` output**

Any existing test that checks the exact string returned by `build_review_text` will need the separator appended to each group in the expected value. Find and update them:

```bash
source .venv/bin/activate && pytest tests/test_core.py -k "review" -q
```

For each failing test, append `"─" * 30 + "\n"` after each `\n\n` in the expected strings.

- [ ] **Step 4: Run all tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 5: Run the app and verify**

Open a document with multiple lines. Context above/below should show horizontal separator lines between each source+translation group, with double-click navigation still working correctly.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/core.py tests/test_core.py
git commit -m "feat(context): add horizontal separators between context groups"
```

---

### Task 5: Button/icon polish (SourcePanel)

**Files:**
- Modify: `ta/ui/source_panel.py`

**What this task does:**

Minor polish pass on `SourcePanel` button labels and tooltips for clarity. No new dependencies. Existing Unicode symbols are kept or improved. The Translate button gets a cleaner label. History buttons get tooltips. The swap button tooltip is already good.

Changes:
- `"▶▶ Translate All"` → `"▶ Translate All"` (single chevron, less aggressive)
- `hist_prev` label: `"◀ Hist"` → `"◀ History"`, tooltip added if missing
- `hist_next` label: `"Hist ▶"` → `"History ▶"`, tooltip added if missing
- Add `objectName` to history buttons for QSS targeting: `"HistPrevBtn"`, `"HistNextBtn"`

- [ ] **Step 1: Apply changes to `source_panel.py`**

Find:

```python
        self._translate_btn = QPushButton("▶▶ Translate All")
```

Replace with:

```python
        self._translate_btn = QPushButton("▶ Translate All")
```

Find:

```python
        hist_prev = QPushButton("◀ Hist")
        hist_prev.setToolTip("Previous history entry (Ctrl+Alt+Up)")
        hist_prev.clicked.connect(self.history_prev_requested)
        toolbar.addWidget(hist_prev)

        hist_next = QPushButton("Hist ▶")
        hist_next.setToolTip("Next history entry (Ctrl+Alt+Down)")
        hist_next.clicked.connect(self.history_next_requested)
        toolbar.addWidget(hist_next)
```

Replace with:

```python
        hist_prev = QPushButton("◀ History")
        hist_prev.setObjectName("HistPrevBtn")
        hist_prev.setToolTip("Previous history entry (Ctrl+Alt+Up)")
        hist_prev.clicked.connect(self.history_prev_requested)
        toolbar.addWidget(hist_prev)

        hist_next = QPushButton("History ▶")
        hist_next.setObjectName("HistNextBtn")
        hist_next.setToolTip("Next history entry (Ctrl+Alt+Down)")
        hist_next.clicked.connect(self.history_next_requested)
        toolbar.addWidget(hist_next)
```

- [ ] **Step 2: Run all tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass (no tests assert exact button labels).

- [ ] **Step 3: Run the app and verify**

Verify Translate button and History buttons show updated labels. Tooltips visible on hover.

- [ ] **Step 4: Commit**

```bash
git add ta/ui/source_panel.py
git commit -m "feat(aggregator): polish SourcePanel button labels and add objectNames"
```

---

## Phase 2 Complete

After all 5 tasks:

- Aggregator's translator panels are in a `QTabWidget` (one tab per engine)
- Each MT panel has a Copy button
- Status bar shows "Page N/N" and persistent "✓ Autosaved Xm ago"
- Context panels have visual separators between source/translation groups
- SourcePanel buttons are labelled consistently

Phase 3 items (collapsible panels, word highlighting, syntax colouring, toolbar widget, theme customisation) remain deferred.

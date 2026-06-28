# UI Overhaul Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current vertical-splitter-only layout with a unified 2D workspace where Context + Source are in the left column, Aggregator + TM matches are in the right column, and Translation Editor + Context Below span full width.

**Architecture:** `TranslationAssistantWidget` is refactored into a pure logic controller — its 5 panel widgets are exposed as public properties and no longer arranged internally. `CombinedMainWindow` builds the full 4-splitter nested layout using those panels plus `AggregatorWidget`. Cards are implemented via `QFrame#Card` in QSS.

**Tech Stack:** PySide6, pytest, QSS

## Global Constraints

- All existing tests must pass after each task
- No toolbar widget (deferred to Phase 2)
- `setChildrenCollapsible(False)` on all splitters
- `QFrame` with `objectName("Card")` for all panel wrappers
- Activate venv before running any command: `source .venv/bin/activate`
- Run tests with: `pytest tests/ -q`

---

### Task 1: Expose TranslationAssistantWidget panels as public properties

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
- Test: `tests/test_main_window.py`

**What this task does:**
- Removes `self._splitter` entirely from TA widget
- Changes `_labeled()` to return `QFrame` (card) instead of `QWidget`
- Stores the 5 panel wrappers as `self._panel_ctx_above`, `self._panel_source`, `self._panel_tm`, `self._panel_translation`, `self._panel_ctx_below`
- Renames `self._tm_wrapper` → `self._panel_tm` throughout
- Removes `QVBoxLayout(self)` — widget has no layout (CombinedMainWindow owns layout)
- Fixes `_setup_statusbar` to not call `self.layout().addWidget()`
- Removes splitter state save from `save_state()`
- Adds 6 public `@property` methods

**Interfaces:**
- Produces: `ta.context_above_panel → QFrame`, `ta.source_panel → QFrame`, `ta.tm_panel → QFrame`, `ta.translation_panel → QFrame`, `ta.context_below_panel → QFrame`, `ta.status_bar → QStatusBar`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_main_window.py` at end of `TestInstantiation` class:

```python
def test_exposes_context_above_panel(self, win):
    from PySide6.QtWidgets import QWidget
    assert isinstance(win.context_above_panel, QWidget)

def test_exposes_source_panel(self, win):
    from PySide6.QtWidgets import QWidget
    assert isinstance(win.source_panel, QWidget)

def test_exposes_tm_panel(self, win):
    from PySide6.QtWidgets import QWidget
    assert isinstance(win.tm_panel, QWidget)

def test_exposes_translation_panel(self, win):
    from PySide6.QtWidgets import QWidget
    assert isinstance(win.translation_panel, QWidget)

def test_exposes_context_below_panel(self, win):
    from PySide6.QtWidgets import QWidget
    assert isinstance(win.context_below_panel, QWidget)

def test_exposes_status_bar(self, win):
    from PySide6.QtWidgets import QStatusBar
    assert isinstance(win.status_bar, QStatusBar)

def test_has_no_layout(self, win):
    assert win.layout() is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestInstantiation -q
```

Expected: 7 new tests FAIL with `AttributeError: 'TranslationAssistantWidget' object has no attribute 'context_above_panel'`

- [ ] **Step 3: Rewrite `_setup_central_widget` in `main_widget.py`**

Replace the entire `_setup_central_widget` method body. The new version:
- Removes `layout = QVBoxLayout(self)` — no layout on self
- Removes `self._splitter` creation
- Changes `_labeled()` to return `QFrame` with `objectName("Card")`
- Stores panels as `self._panel_*` attributes instead of adding to a splitter

```python
def _setup_central_widget(self) -> None:
    font = QFont()
    font.setFamilies(_CJK_FAMILIES)
    font.setPointSizeF(self._settings.font_size)

    def _labeled(title, inner: QWidget) -> QFrame:
        w = QFrame()
        w.setObjectName("Card")
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(4)
        if isinstance(title, str):
            lbl = QLabel(title)
            lbl.setObjectName("PanelLabel")
        else:
            lbl = title  # already a QLabel/ClickableLabel
        vbox.addWidget(lbl)
        vbox.addWidget(inner)
        return w

    self._review_top = ReviewTextEdit()
    self._review_top.setObjectName("ContextAbove")
    self._review_top.setReadOnly(True)
    self._review_top.setFont(font)
    self._review_top.setPlaceholderText(
        "Open a document to begin — prior sentences appear here."
    )
    self._review_top.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
    )
    self._review_top.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    self._review_top.setMinimumHeight(50)
    self._review_top.line_double_clicked.connect(self._on_review_top_double_click)
    self._panel_ctx_above = _labeled("Context (Above)", self._review_top)

    self._raw_line = QTextEdit()
    self._raw_line.setObjectName("SourceText")
    self._raw_line.setReadOnly(True)
    self._raw_line.setFont(font)
    self._raw_line.setMinimumHeight(40)
    self._raw_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    self._raw_line.setPlaceholderText("No document open — File → New or Ctrl+O")
    self._source_label = QLabel("Source (read-only)")
    self._source_label.setObjectName("PanelLabel")
    self._panel_source = _labeled(self._source_label, self._raw_line)

    self._tm_panel = QWidget()
    self._tm_panel.setMinimumHeight(0)
    self._tm_layout = QVBoxLayout(self._tm_panel)
    self._tm_layout.setContentsMargins(2, 2, 2, 2)
    self._tm_layout.setSpacing(2)
    _tm_lbl = _ClickableLabel("TM Matches")
    _tm_lbl.setObjectName("PanelLabel")
    _tm_lbl.clicked.connect(self._toggle_tm_panel)
    self._panel_tm = _labeled(_tm_lbl, self._tm_panel)

    self._translated_line = QTextEdit()
    self._translated_line.setObjectName("TranslationText")
    self._translated_line.setFont(font)
    self._translated_line.setMinimumHeight(40)
    self._translated_line.setAcceptRichText(False)
    self._translated_line.setPlaceholderText("Type translation here…")
    self._translated_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    self._translated_line.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    self._translated_line.customContextMenuRequested.connect(self._on_translated_context_menu)
    self._translation_label = QLabel("Translation")
    self._translation_label.setObjectName("PanelLabel")
    self._panel_translation = _labeled(self._translation_label, self._translated_line)
    self._spell_highlighter = SpellHighlighter(self._translated_line.document())

    self._review_bottom = ReviewTextEdit()
    self._review_bottom.setObjectName("ContextBelow")
    self._review_bottom.setReadOnly(True)
    self._review_bottom.setFont(font)
    self._review_bottom.setPlaceholderText(
        "Enter / PgDn = next sentence  ·  PgUp = previous  ·  Ctrl+← / → = phrase"
    )
    self._review_bottom.setMinimumHeight(50)
    self._review_bottom.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    self._review_bottom.line_double_clicked.connect(self._on_review_bottom_double_click)
    self._panel_ctx_below = _labeled("Context (Below)", self._review_bottom)

    self._translated_line.textChanged.connect(self._on_translation_text_changed)
    self._translated_line.textChanged.connect(self._update_translation_label)
```

- [ ] **Step 4: Fix `_setup_statusbar` — remove layout reference**

Find this in `_setup_statusbar` (around line 484):
```python
def _setup_statusbar(self) -> None:
    self._status_bar = QStatusBar()
    layout = self.layout()
    layout.addWidget(self._status_bar)
```

Replace with:
```python
def _setup_statusbar(self) -> None:
    self._status_bar = QStatusBar()
```

All remaining lines in `_setup_statusbar` (creating `_progress_bar`, `_line_label`, etc.) stay unchanged.

- [ ] **Step 5: Fix `_update_tm_panel` — rename `_tm_wrapper` → `_panel_tm`**

Find these 3 lines in `_update_tm_panel` (around line 769):
```python
            self._tm_wrapper.setVisible(False)
            return
        ...
            self._tm_wrapper.setVisible(False)
            return
        ...
        self._tm_wrapper.setVisible(True)
```

Replace each `self._tm_wrapper` with `self._panel_tm`.

- [ ] **Step 6: Fix `save_state` — remove splitter save**

Find in `save_state` (around line 1788):
```python
def save_state(self) -> None:
    """Called by CombinedMainWindow.closeEvent."""
    self._settings.splitter_state = self._splitter.saveState()
    self._save_current_translation()
    self._settings.last_doc_id = self._doc_id
    self._settings.save()
```

Replace with:
```python
def save_state(self) -> None:
    """Called by CombinedMainWindow.closeEvent."""
    self._save_current_translation()
    self._settings.last_doc_id = self._doc_id
    self._settings.save()
```

- [ ] **Step 7: Add 6 public properties**

Add after the `save_state` method:

```python
# ------------------------------------------------------------------
# Panel access (consumed by CombinedMainWindow to build layout)
# ------------------------------------------------------------------

@property
def context_above_panel(self) -> QFrame:
    return self._panel_ctx_above

@property
def source_panel(self) -> QFrame:
    return self._panel_source

@property
def tm_panel(self) -> QFrame:
    return self._panel_tm

@property
def translation_panel(self) -> QFrame:
    return self._panel_translation

@property
def context_below_panel(self) -> QFrame:
    return self._panel_ctx_below

@property
def status_bar(self) -> QStatusBar:
    return self._status_bar
```

Note: `QFrame` is already imported in `main_widget.py`.

- [ ] **Step 8: Run all tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass including the 7 new ones. The app will not render correctly yet (panels have no parent layout) — that is fixed in Task 2.

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "refactor(main_widget): expose panels as public properties, remove internal splitter"
```

---

### Task 2: CombinedMainWindow — build unified 2D layout

**Files:**
- Modify: `translation_assistant/ui/combined_window.py`
- Test: `tests/test_combined_window.py`

**What this task does:**
- Replaces the old horizontal TA/Aggregator splitter with 4 nested splitters
- TA widget is kept as a child of CombinedMainWindow (for Qt object ownership) but not added to any layout
- Adopts TA widget's `QStatusBar` as the window's native status bar
- Saves/restores 4 splitter states using the existing raw QSettings pattern

**Interfaces:**
- Consumes: `ta.context_above_panel`, `ta.source_panel`, `ta.tm_panel`, `ta.translation_panel`, `ta.context_below_panel`, `ta.status_bar` from Task 1

- [ ] **Step 1: Write failing tests**

Add to `tests/test_combined_window.py` in `TestCombinedWindowInstantiation`:

```python
def test_has_outer_splitter(self, win):
    from PySide6.QtWidgets import QSplitter
    from PySide6.QtCore import Qt
    assert isinstance(win._outer_splitter, QSplitter)
    assert win._outer_splitter.orientation() == Qt.Orientation.Vertical

def test_outer_splitter_has_three_children(self, win):
    assert win._outer_splitter.count() == 3

def test_mid_splitter_is_horizontal(self, win):
    from PySide6.QtCore import Qt
    assert win._mid_splitter.orientation() == Qt.Orientation.Horizontal

def test_mid_splitter_has_two_columns(self, win):
    assert win._mid_splitter.count() == 2

def test_status_bar_is_ta_status_bar(self, win):
    assert win.statusBar() is win._ta_widget.status_bar
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_combined_window.py::TestCombinedWindowInstantiation -q
```

Expected: 5 new tests FAIL. Existing tests continue to pass.

- [ ] **Step 3: Rewrite `__init__` and add `_build_workspace` in `combined_window.py`**

First, update the import line at the top of `combined_window.py`.

Find:
```python
from PySide6.QtWidgets import QMainWindow, QMenu, QSplitter
```

Replace with:
```python
from PySide6.QtWidgets import QMainWindow, QMenu, QSplitter, QVBoxLayout, QWidget
```

Next, replace the `__init__` method body (keep the docstring at top of file and `_RESOURCES` line unchanged):

```python
    def __init__(self, _settings: AppSettings | None = None, _db=None) -> None:
        super().__init__()
        self.setWindowTitle("Translation Assistant")
        self.resize(1200, 700)
        self.setMinimumSize(900, 500)

        icon_path = _RESOURCES / "TA.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._ta_widget = TranslationAssistantWidget(_settings=_settings, _db=_db)
        self._agg_widget = AggregatorWidget()

        self._build_workspace()
        self.setStatusBar(self._ta_widget.status_bar)
        self._setup_menubar()
        self._restore_splitter()
        self._connect_bridge()

        if _settings is not None and _settings.on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
```

Then add `_build_workspace` as a new method after `__init__` (before `_connect_bridge`):

```python
    def _build_workspace(self) -> None:
        ta = self._ta_widget

        self._left_splitter = QSplitter(Qt.Orientation.Vertical)
        self._left_splitter.setChildrenCollapsible(False)
        self._left_splitter.addWidget(ta.context_above_panel)
        self._left_splitter.addWidget(ta.source_panel)
        self._left_splitter.setStretchFactor(0, 2)
        self._left_splitter.setStretchFactor(1, 1)

        self._right_splitter = QSplitter(Qt.Orientation.Vertical)
        self._right_splitter.setChildrenCollapsible(False)
        self._right_splitter.addWidget(self._agg_widget)
        self._right_splitter.addWidget(ta.tm_panel)
        self._right_splitter.setStretchFactor(0, 2)
        self._right_splitter.setStretchFactor(1, 1)

        self._mid_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._mid_splitter.setChildrenCollapsible(False)
        self._mid_splitter.addWidget(self._left_splitter)
        self._mid_splitter.addWidget(self._right_splitter)
        self._mid_splitter.setStretchFactor(0, 2)
        self._mid_splitter.setStretchFactor(1, 1)

        self._outer_splitter = QSplitter(Qt.Orientation.Vertical)
        self._outer_splitter.setChildrenCollapsible(False)
        self._outer_splitter.addWidget(self._mid_splitter)
        self._outer_splitter.addWidget(ta.translation_panel)
        self._outer_splitter.addWidget(ta.context_below_panel)
        self._outer_splitter.setStretchFactor(0, 3)
        self._outer_splitter.setStretchFactor(1, 2)
        self._outer_splitter.setStretchFactor(2, 1)

        # Wrap in container to provide window margins
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(12, 12, 12, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self._outer_splitter)
        self.setCentralWidget(container)
```

All other methods (`_connect_bridge`, `_setup_menubar`, `_rebuild_recent_menu`, `_on_shortcuts`, `_on_wp_settings`, `_open_setup_guide`, `_toggle_topmost`) remain **completely unchanged**.

- [ ] **Step 4: Rewrite `_restore_splitter` and `_save_splitter`**

Replace the existing `_restore_splitter`, `_save_splitter`, and `closeEvent` methods with:

```python
    # ------------------------------------------------------------------
    # Layout persistence
    # ------------------------------------------------------------------

    def _restore_splitter(self) -> None:
        qs = self._ta_widget._settings._qs
        defaults_applied = False
        for key, splitter in [
            ("combined/splitter_outer", self._outer_splitter),
            ("combined/splitter_mid",   self._mid_splitter),
            ("combined/splitter_left",  self._left_splitter),
            ("combined/splitter_right", self._right_splitter),
        ]:
            raw = qs.value(key)
            if raw:
                splitter.restoreState(QByteArray.fromBase64(raw.encode()))
            else:
                defaults_applied = True

        if defaults_applied:
            self._outer_splitter.setSizes([500, 200, 100])
            self._mid_splitter.setSizes([500, 400])
            self._left_splitter.setSizes([300, 120])
            self._right_splitter.setSizes([300, 150])

    def _save_splitter(self) -> None:
        qs = self._ta_widget._settings._qs
        for key, splitter in [
            ("combined/splitter_outer", self._outer_splitter),
            ("combined/splitter_mid",   self._mid_splitter),
            ("combined/splitter_left",  self._left_splitter),
            ("combined/splitter_right", self._right_splitter),
        ]:
            qs.setValue(key, splitter.saveState().toBase64().data().decode())

    def closeEvent(self, event) -> None:
        self._save_splitter()
        self._ta_widget.save_state()
        self._agg_widget.save_layout()
        super().closeEvent(event)
```

- [ ] **Step 5: Run all tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass including the 5 new combined window tests.

- [ ] **Step 6: Run the app and verify layout**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

Verify:
- App launches without errors
- Left column shows Context Above (top) and Source text (bottom)
- Right column shows Aggregator (top) and TM Matches (bottom)
- Full-width bottom shows Translation Editor and Context Below
- All splitter handles are draggable
- Status bar appears at bottom of window

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/combined_window.py tests/test_combined_window.py
git commit -m "feat(combined_window): build unified 2D workspace layout with nested splitters"
```

---

### Task 3: Cards + Typography in QSS

**Files:**
- Modify: `translation_assistant/resources/style.qss`

**What this task does:**
- Adds `QFrame#Card` rule for card styling (rounded corners, thin border, slightly lighter background)
- Bumps base font from 12px → 13px
- Bumps PanelLabel from 10px → 11px
- Bumps JP source text from 16px → 20px
- Updates splitter handle width to 6px for comfortable dragging

**Interfaces:**
- Consumes: `objectName("Card")` set on panel wrappers from Task 1
- No code interfaces — purely visual

- [ ] **Step 1: Add `QFrame#Card` rule**

In `style.qss`, after the `/* === Panels === */` block (after the `QFrame { ... }` rule), add:

```css
/* === Cards === */
QFrame#Card {
    background: #1A1D27;
    border: 1px solid #2E3350;
    border-radius: 8px;
    padding: 4px;
}
```

- [ ] **Step 2: Bump base font size**

Find:
```css
QWidget {
    background-color: #0F1117;
    color: #E8E6F0;
    font-family: 'Inter';
    font-size: 12px;
}
```

Change `font-size: 12px;` → `font-size: 13px;`

- [ ] **Step 3: Bump PanelLabel font size**

Find:
```css
QLabel#PanelLabel {
    font-family: 'Inter';
    font-size: 10px;
```

Change `font-size: 10px;` → `font-size: 11px;`

- [ ] **Step 4: Bump JP source text font size**

Find:
```css
QTextEdit#SourceText {
    background: #1A1D27;
    color: #F0EDE8;
    border: none;
    font-family: 'Noto Sans JP';
    font-size: 16px;
```

Change `font-size: 16px;` → `font-size: 20px;`

- [ ] **Step 5: Add splitter handle width**

Add at end of `style.qss`:

```css
/* === Splitter handles === */
QSplitter::handle {
    background: #2E3350;
}
QSplitter::handle:horizontal {
    width: 6px;
}
QSplitter::handle:vertical {
    height: 6px;
}
```

- [ ] **Step 6: Run all tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass (QSS changes have no effect on unit tests).

- [ ] **Step 7: Run the app and verify visual result**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

Verify:
- All panels render as rounded cards (visible border radius, thin border)
- JP source text is noticeably larger than surrounding text
- Splitter handles are visible and 6px wide/tall
- PanelLabel headers are readable above each card

- [ ] **Step 8: Commit**

```bash
git add translation_assistant/resources/style.qss
git commit -m "feat(style): add card panels, bump JP source font, widen splitter handles"
```

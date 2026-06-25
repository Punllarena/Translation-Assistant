# Visual Polish B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four targeted visual polish improvements — adjustable font size via View menu, cleaner TM match panel, raw line empty-state placeholder, and source panel label that shows the current document title.

**Architecture:** All changes are in three files: `settings.py` (new property), `main_widget.py` (new widget class + action methods + UI tweaks), and `combined_window.py` (View menu addition). No new files.

**Tech Stack:** PySide6, Python 3.11+, pytest + QApplication fixture from `conftest.py`

## Global Constraints

- Python 3.11+, PySide6
- All tests run via `pytest` from repo root with venv activated (`source .venv/bin/activate`)
- Single `QApplication` instance provided by session-scoped `qapp` fixture in `conftest.py`
- `TranslationAssistantWidget` takes `_settings: AppSettings` and `_db: Database` — always pass isolated instances in tests
- `Database` test seam: `Database(":memory:", _conn=conn)` with `sqlite3.connect(":memory:")`
- `AppSettings` test seam: `AppSettings(_qs=QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))`
- Never call `window.show()` in tests — widgets are exercised headlessly
- Font size range: 8.0–24.0 pt, step 1.0

---

### Task 1: AppSettings.font_size property

**Files:**
- Modify: `translation_assistant/settings.py` (after `tm_visible` property, ~line 136)
- Test: `tests/test_settings.py` (append to end of file)

**Interfaces:**
- Produces: `AppSettings.font_size: float` — readable/writable, default `12.5`, persisted under key `"FontSize"`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_settings.py`:

```python
def test_default_font_size(tmp_settings):
    assert tmp_settings.font_size == 12.5


def test_font_size_persists(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")
    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.font_size = 16.0
    s1.save()
    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.font_size == 16.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_settings.py::test_default_font_size tests/test_settings.py::test_font_size_persists -v
```

Expected: `AttributeError: 'AppSettings' object has no attribute 'font_size'`

- [ ] **Step 3: Implement**

In `translation_assistant/settings.py`, add after the `tm_visible` setter (around line 136) and before `# --- setup wizard shown ---`:

```python
    # --- editor font size ---

    @property
    def font_size(self) -> float:
        return self._qs.value("FontSize", 12.5, type=float)

    @font_size.setter
    def font_size(self, value: float) -> None:
        self._qs.setValue("FontSize", value)
```

Also add `"FontSize": 12.5` to `_DEFAULTS` dict at the top of the class:

```python
    _DEFAULTS: dict = {
        "ParseChar": "、 。 ？ ！ 「 」 …… ",
        "ProfileUsed": "Default",
        "ShowProgress": True,
        "AutoSave": 5,
        "OnTop": True,
        "TTS": False,
        "TTSLang": 0,
        "FontSize": 12.5,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_settings.py::test_default_font_size tests/test_settings.py::test_font_size_persists -v
```

Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/settings.py tests/test_settings.py
git commit -m "feat(settings): add font_size property (default 12.5, persisted)"
```

---

### Task 2: Font size controls (actions, View menu, shortcut registry)

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
  - `_build_actions` (~line 140): add `action_font_larger`, `action_font_smaller`
  - `_build_shortcut_registry` (~line 267): register both actions
  - `_setup_central_widget` (~line 299): replace hardcoded `12.5`
  - Add `_adjust_font_size` and `_apply_font` methods
- Modify: `translation_assistant/ui/combined_window.py`
  - `_setup_menubar` View section (~line 122): add Font Size submenu
- Test: `tests/test_main_window.py` (append to end)

**Interfaces:**
- Consumes: `AppSettings.font_size: float` from Task 1
- Produces:
  - `TranslationAssistantWidget.action_font_larger: QAction` (shortcut `Ctrl+=`)
  - `TranslationAssistantWidget.action_font_smaller: QAction` (shortcut `Ctrl+-`)
  - `TranslationAssistantWidget._adjust_font_size(delta: int) -> None`
  - `TranslationAssistantWidget._apply_font() -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main_window.py`:

```python
class TestFontSize:
    def test_has_font_larger_action(self, win):
        assert hasattr(win, "action_font_larger")

    def test_has_font_smaller_action(self, win):
        assert hasattr(win, "action_font_smaller")

    def test_font_larger_increases_size(self, win):
        initial = win._settings.font_size
        win._adjust_font_size(+1)
        assert win._settings.font_size == initial + 1.0

    def test_font_smaller_decreases_size(self, win):
        win._settings.font_size = 14.0
        win._adjust_font_size(-1)
        assert win._settings.font_size == 13.0

    def test_font_size_clamped_at_max(self, win):
        win._settings.font_size = 24.0
        win._adjust_font_size(+1)
        assert win._settings.font_size == 24.0

    def test_font_size_clamped_at_min(self, win):
        win._settings.font_size = 8.0
        win._adjust_font_size(-1)
        assert win._settings.font_size == 8.0

    def test_apply_font_sets_font_on_all_panels(self, win):
        win._settings.font_size = 18.0
        win._apply_font()
        for panel in (win._review_top, win._raw_line,
                      win._translated_line, win._review_bottom):
            assert abs(panel.font().pointSizeF() - 18.0) < 0.1

    def test_font_larger_in_shortcut_registry(self, win):
        keys = [entry[0] for entry in win._shortcut_registry]
        assert "font_larger" in keys

    def test_font_smaller_in_shortcut_registry(self, win):
        keys = [entry[0] for entry in win._shortcut_registry]
        assert "font_smaller" in keys
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_main_window.py::TestFontSize -v
```

Expected: `AttributeError: 'TranslationAssistantWidget' object has no attribute 'action_font_larger'`

- [ ] **Step 3: Add actions to `_build_actions`**

In `translation_assistant/ui/main_widget.py`, at the end of `_build_actions` (before the closing of the method, after `self.action_series_phrases` block around line 265):

```python
        self.action_font_larger = QAction("Larger", self)
        self.action_font_larger.setShortcut("Ctrl+=")
        self.action_font_larger.triggered.connect(lambda: self._adjust_font_size(+1))

        self.action_font_smaller = QAction("Smaller", self)
        self.action_font_smaller.setShortcut("Ctrl+-")
        self.action_font_smaller.triggered.connect(lambda: self._adjust_font_size(-1))
```

- [ ] **Step 4: Register in `_build_shortcut_registry`**

In `_build_shortcut_registry` (around line 267), add to the initial list:

```python
        self._shortcut_registry: list[tuple[str, str, QAction, str]] = [
            ("new_doc",        "New Document",              self.action_new_doc,        "Ctrl+N"),
            ("open",           "Open",                      self.action_open,           "Ctrl+O"),
            ("save",           "Save",                      self.action_save,           "Ctrl+S"),
            ("profile",        "Profile",                   self.action_profile,        "Ctrl+P"),
            ("phrase",         "Phrase",                    self.action_phrase,         "Ctrl+L"),
            ("go_to_line",     "Go to Line",                self.action_go_to_line,     "Ctrl+G"),
            ("clipboard",      "Copy to Clipboard",         self.action_clipboard,      "Ctrl+Shift+C"),
            ("series_phrases", "Series Phrase Suggestions", self.action_series_phrases, "Ctrl+Shift+P"),
            ("font_larger",    "Font Size: Larger",         self.action_font_larger,    "Ctrl+="),
            ("font_smaller",   "Font Size: Smaller",        self.action_font_smaller,   "Ctrl+-"),
        ]
```

- [ ] **Step 5: Add `_adjust_font_size` and `_apply_font` methods**

Add these two methods to `TranslationAssistantWidget` (good location: after `_on_set_autosave` around line 733):

```python
    def _adjust_font_size(self, delta: int) -> None:
        new_size = max(8.0, min(24.0, self._settings.font_size + delta))
        self._settings.font_size = new_size
        self._settings.save()
        self._apply_font()

    def _apply_font(self) -> None:
        font = QFont()
        font.setFamilies(_CJK_FAMILIES)
        font.setPointSizeF(self._settings.font_size)
        for w in (self._review_top, self._raw_line,
                  self._translated_line, self._review_bottom):
            w.setFont(font)
```

- [ ] **Step 6: Replace hardcoded font size in `_setup_central_widget`**

At the top of `_setup_central_widget` (~line 299), change:

```python
        font = QFont()
        font.setFamilies(_CJK_FAMILIES)
        font.setPointSizeF(12.5)
```

to:

```python
        font = QFont()
        font.setFamilies(_CJK_FAMILIES)
        font.setPointSizeF(self._settings.font_size)
```

- [ ] **Step 7: Add Font Size submenu to View menu in `combined_window.py`**

In `_setup_menubar` (~line 122), the View menu block ends around line 132 with:
```python
        view_menu.addAction(ta.action_tm)
```

Add after it:

```python
        view_menu.addSeparator()
        font_menu = QMenu("Font Size", self)
        font_menu.addAction(ta.action_font_larger)
        font_menu.addAction(ta.action_font_smaller)
        view_menu.addMenu(font_menu)
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
pytest tests/test_main_window.py::TestFontSize -v
```

Expected: all PASS

- [ ] **Step 9: Run full suite to check for regressions**

```bash
pytest -q
```

Expected: all existing tests still pass (535+)

- [ ] **Step 10: Commit**

```bash
git add translation_assistant/settings.py translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py tests/test_main_window.py
git commit -m "feat(ui): font size controls via View > Font Size (Ctrl+=/-)"
```

---

### Task 3: TM match panel cleanup

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
  - Add `_TmRow` class (before `TranslationAssistantWidget`, after module-level helpers)
  - Add `QFrame` to Qt imports
  - Replace QPushButton loop in `_update_tm_panel` (~line 673)
- Test: `tests/test_main_window.py` (append)

**Interfaces:**
- Produces: `_TmRow(translation: str, meta: str, parent=None)` — emits `clicked(str)` on mouse press, has hover highlight

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main_window.py`:

```python
class TestTmRow:
    def test_tm_row_emits_clicked_with_translation(self, qapp):
        from translation_assistant.ui.main_widget import _TmRow
        received = []
        row = _TmRow("Hello world", "Doc A, 2026-01-01")
        row.clicked.connect(received.append)
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import Qt, QPointF
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(1, 1), QPointF(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        row.mousePressEvent(event)
        assert received == ["Hello world"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_main_window.py::TestTmRow -v
```

Expected: `ImportError: cannot import name '_TmRow'`

- [ ] **Step 3: Add `QFrame` to imports in `main_widget.py`**

Change the `QWidgets` import block at the top of `main_widget.py` from:

```python
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QLabel, QMenu,
    QMessageBox, QPushButton, QSizePolicy, QSplitter, QStatusBar, QTextEdit, QVBoxLayout, QWidget,
)
```

to:

```python
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QInputDialog, QLabel, QMenu,
    QMessageBox, QPushButton, QSizePolicy, QSplitter, QStatusBar, QTextEdit, QVBoxLayout, QWidget,
)
```

- [ ] **Step 4: Add `_TmRow` class**

Add this class after `_ClickableLabel` (around line 95, before `class TranslationAssistantWidget`):

```python
class _TmRow(QWidget):
    clicked = Signal(str)

    def __init__(self, translation: str, meta: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._translation = translation
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(4, 3, 4, 3)
        vbox.setSpacing(1)
        tl = QLabel(translation)
        tl.setWordWrap(True)
        vbox.addWidget(tl)
        meta_lbl = QLabel(meta)
        meta_lbl.setStyleSheet("font-size: 8pt; color: gray;")
        vbox.addWidget(meta_lbl)

    def mousePressEvent(self, event):
        self.clicked.emit(self._translation)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.setStyleSheet("background: palette(highlight); color: palette(highlighted-text);")

    def leaveEvent(self, event):
        self.setStyleSheet("")
```

- [ ] **Step 5: Replace `QPushButton` loop in `_update_tm_panel`**

In `_update_tm_panel` (~line 693), replace the entire `for m in matches:` loop:

```python
        # OLD — remove this:
        for m in matches:
            date_str = m["updated_at"][:10] if m.get("updated_at") else ""
            label = f"{m['translated_text']}  —  {m['doc_title']}, {date_str}"
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setStyleSheet("text-align: left; padding: 2px 4px;")
            translation = m["translated_text"]
            btn.clicked.connect(
                lambda checked, t=translation: self._translated_line.setPlainText(t)
            )
            self._tm_layout.addWidget(btn)
```

with:

```python
        for i, m in enumerate(matches):
            date_str = m["updated_at"][:10] if m.get("updated_at") else ""
            meta = f"{m['doc_title']}, {date_str}"
            row = _TmRow(m["translated_text"], meta)
            row.clicked.connect(self._translated_line.setPlainText)
            self._tm_layout.addWidget(row)
            if i < len(matches) - 1:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("color: palette(mid);")
                self._tm_layout.addWidget(sep)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_main_window.py::TestTmRow -v
```

Expected: PASS

- [ ] **Step 7: Run full suite**

```bash
pytest -q
```

Expected: all existing tests still pass

- [ ] **Step 8: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(ui): TM panel uses _TmRow widget (two-line, hover highlight)"
```

---

### Task 4: Source panel label + raw line empty state

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
  - `_setup_central_widget` (~line 337): keep `_source_label` reference, add raw line placeholder
  - `_finish_load` (~line 590): update `_source_label` text
  - `_on_db_import` (~line 1172): reset `_source_label` text
- Test: `tests/test_main_window.py` (append)

**Interfaces:**
- Produces: `TranslationAssistantWidget._source_label: QLabel` — updated in `_finish_load`, reset in `_on_db_import`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main_window.py`:

```python
class TestSourceLabel:
    def test_has_source_label(self, win):
        assert hasattr(win, "_source_label")

    def test_source_label_default_text(self, win):
        assert "Source" in win._source_label.text()

    def test_source_label_updates_on_load_with_chapter_title(self, win):
        win.load_content(
            "%Hello\n---SEPERATOR---\n",
            title="Doc Title",
            chapter_title="Chapter 1",
        )
        assert "Chapter 1" in win._source_label.text()

    def test_source_label_falls_back_to_title(self, win):
        win.load_content(
            "%Hello\n---SEPERATOR---\n",
            title="My Doc",
            chapter_title="",
        )
        assert "My Doc" in win._source_label.text()

    def test_raw_line_placeholder_text(self, win):
        assert "Ctrl+O" in win._raw_line.placeholderText() or \
               "File" in win._raw_line.placeholderText()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_main_window.py::TestSourceLabel -v
```

Expected: `AttributeError: 'TranslationAssistantWidget' object has no attribute '_source_label'`

- [ ] **Step 3: Replace the source panel section in `_setup_central_widget`**

In `_setup_central_widget`, find this block (~line 337):

```python
        self._raw_line = QTextEdit()
        self._raw_line.setReadOnly(True)
        self._raw_line.setFont(font)
        self._raw_line.setMinimumHeight(40)
        self._raw_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._splitter.addWidget(_labeled("Source (read-only)", self._raw_line))
```

Replace with:

```python
        self._raw_line = QTextEdit()
        self._raw_line.setReadOnly(True)
        self._raw_line.setFont(font)
        self._raw_line.setMinimumHeight(40)
        self._raw_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._raw_line.setPlaceholderText("No document open — File → New or Ctrl+O")
        self._source_label = QLabel("Source (read-only)")
        self._source_label.setStyleSheet("font-size: 9pt; color: gray; padding: 1px 4px;")
        _source_wrapper = QWidget()
        _sw_vbox = QVBoxLayout(_source_wrapper)
        _sw_vbox.setContentsMargins(0, 0, 0, 0)
        _sw_vbox.setSpacing(0)
        _sw_vbox.addWidget(self._source_label)
        _sw_vbox.addWidget(self._raw_line)
        self._splitter.addWidget(_source_wrapper)
```

- [ ] **Step 4: Update `_source_label` in `_finish_load`**

In `_finish_load` (~line 594), there is already this block:

```python
        _doc_meta = self._db.get_document(self._doc_id)
        _has_series = bool(_doc_meta.get("series_title", ""))
        self.action_export_md_tl_series.setEnabled(_has_series)
        self.action_export_md_ruby_series.setEnabled(_has_series)
```

Add two lines immediately after `_doc_meta = self._db.get_document(self._doc_id)`:

```python
        _doc_meta = self._db.get_document(self._doc_id)
        _doc_display = _doc_meta.get("chapter_title") or _doc_meta.get("title") or ""
        self._source_label.setText(f"Source — {_doc_display}" if _doc_display else "Source (read-only)")
        _has_series = bool(_doc_meta.get("series_title", ""))
        self.action_export_md_tl_series.setEnabled(_has_series)
        self.action_export_md_ruby_series.setEnabled(_has_series)
```

- [ ] **Step 5: Reset `_source_label` in `_on_db_import`**

In `_on_db_import` (~line 1172), after `self._translated_line.clear()`, add:

```python
        self._source_label.setText("Source (read-only)")
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_main_window.py::TestSourceLabel -v
```

Expected: all PASS

- [ ] **Step 7: Run full suite**

```bash
pytest -q
```

Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(ui): source label shows doc title, raw line empty-state placeholder"
```

---

## Self-Review Checklist

- [x] **Spec coverage:**
  - Font size (View menu, Ctrl+=/-): Tasks 1 + 2 ✓
  - Shortcut registry entries: Task 2 Step 4 ✓
  - TM panel cleanup (_TmRow, separator): Task 3 ✓
  - Raw line placeholder: Task 4 Step 3 ✓
  - Source label dynamic title: Task 4 Steps 4-5 ✓

- [x] **Placeholders:** None. Every step has concrete code.

- [x] **Type consistency:**
  - `AppSettings.font_size: float` used as `float` throughout (Task 1 → Task 2 `_apply_font`)
  - `_TmRow.clicked = Signal(str)` → connected to `self._translated_line.setPlainText` which accepts `str` ✓
  - `_source_label: QLabel` attr set in `_setup_central_widget`, read in `_finish_load` and `_on_db_import` ✓

- [x] **No gaps:** All four spec items covered across four tasks.

# Visual Polish B — Design Spec

**Date:** 2026-06-25  
**Scope:** Four targeted UI improvements — font size control, TM panel cleanup, raw line empty state, source label with doc title.

---

## 1. Font Size Control

### Goal
Let users adjust text size across all four main panels without restarting the app.

### AppSettings change
Add `font_size: float` property, default `12.5`, backed by key `"FontSize"` in QSettings.

```python
@property
def font_size(self) -> float:
    return self._qs.value("FontSize", 12.5, type=float)

@font_size.setter
def font_size(self, value: float) -> None:
    self._qs.setValue("FontSize", value)
```

### TranslationAssistantWidget changes

**New actions** (in `_build_actions`):
```python
self.action_font_larger = QAction("Larger", self)
self.action_font_larger.setShortcut("Ctrl+=")
self.action_font_larger.triggered.connect(lambda: self._adjust_font_size(+1))

self.action_font_smaller = QAction("Smaller", self)
self.action_font_smaller.setShortcut("Ctrl+-")
self.action_font_smaller.triggered.connect(lambda: self._adjust_font_size(-1))
```

**New methods**:
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
    for w in (self._review_top, self._raw_line, self._translated_line, self._review_bottom):
        w.setFont(font)
```

**`_setup_central_widget`**: replace `font.setPointSizeF(12.5)` with `font.setPointSizeF(self._settings.font_size)`.

### CombinedMainWindow change
Add "Font Size" submenu to View menu:
```python
font_menu = QMenu("Font Size", self)
font_menu.addAction(ta.action_font_larger)
font_menu.addAction(ta.action_font_smaller)
view_menu.addMenu(font_menu)
```

### Shortcut registry
Add both actions to `_build_shortcut_registry` so users can remap them via the Shortcuts dialog:
```python
("font_larger",  "Font Size: Larger",  self.action_font_larger,  "Ctrl+="),
("font_smaller", "Font Size: Smaller", self.action_font_smaller, "Ctrl+-"),
```

### Constraints
- Range clamped to [8.0, 24.0] pt, step 1.0
- Persisted immediately on each adjustment
- Applies live to all four panels: `_review_top`, `_raw_line`, `_translated_line`, `_review_bottom`

---

## 2. TM Match Panel Cleanup

### Goal
Replace flat `QPushButton` rows with a two-line widget (translation + metadata) that reads clearly and has hover feedback.

### New widget: `_TmRow` (in `main_widget.py`)
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

### `_update_tm_panel` change
Replace the `QPushButton` creation loop with:
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

### Imports to add
`QFrame` to the `QWidgets` import block in `main_widget.py`.

---

## 3. Raw Line Empty-State Placeholder

### Goal
`_raw_line` currently shows blank when no document is open. Add a discoverable hint.

### Change
One line in `_setup_central_widget`, after `self._raw_line = QTextEdit()`:
```python
self._raw_line.setPlaceholderText("No document open — File → New or Ctrl+O")
```

---

## 4. Source Panel Label Shows Doc Title

### Goal
"Source (read-only)" label updates to "Source — {chapter_title or title}" when a document loads, making it easy to confirm which document is active.

### Setup change
In `_setup_central_widget`, instead of discarding the label returned by `_labeled()`, keep a reference to the source panel label.

Change the source panel block from using `_labeled(...)` to:
```python
self._source_label = QLabel("Source (read-only)")
self._source_label.setStyleSheet("font-size: 9pt; color: gray; padding: 1px 4px;")
source_wrapper = QWidget()
_sw_vbox = QVBoxLayout(source_wrapper)
_sw_vbox.setContentsMargins(0, 0, 0, 0)
_sw_vbox.setSpacing(0)
_sw_vbox.addWidget(self._source_label)
_sw_vbox.addWidget(self._raw_line)
self._splitter.addWidget(source_wrapper)
```

### `_finish_load` change
`_finish_load` already calls `self._db.get_document(self._doc_id)` and stores the result as `_doc_meta`. Reuse it — do not call `get_document` a second time. Add after the existing `_doc_meta` block:
```python
_title = _doc_meta.get("chapter_title") or _doc_meta.get("title") or ""
self._source_label.setText(f"Source — {_title}" if _title else "Source (read-only)")
```

Also reset to `"Source (read-only)"` in `_on_db_import` after clearing the doc state.

---

## Files Changed

| File | Change |
|------|--------|
| `translation_assistant/settings.py` | Add `font_size` property |
| `translation_assistant/ui/main_widget.py` | `_TmRow` class, `action_font_larger/smaller`, `_adjust_font_size`, `_apply_font`, source label ref, placeholder, `_finish_load` update |
| `translation_assistant/ui/combined_window.py` | Font Size submenu in View menu |

## Out of Scope

- Theme/color scheme selection (future)
- Per-panel font size (all four panels share one size)
- Font family selection (CJK family stack is correct for the use case)

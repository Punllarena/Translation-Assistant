# Visual Polish A — Design Spec

**Date:** 2026-06-25  
**Scope:** Four information-density improvements — window title with doc name, parse phrase counter, progress bar, and panel label counts.

---

## 1. Window Title with Doc Name

### Goal
Show the current document title in the window title bar so the user always knows what's open.

### Format
- No doc open: `"Translation Assistant"`
- Doc open, clean: `"Chapter 1: The Beginning — Translation Assistant"`
- Doc open, dirty: `"Chapter 1: The Beginning — Translation Assistant *"`

### Implementation

**New instance var** (in `__init__`):
```python
self._doc_title: str = ""
```

**New method `_refresh_window_title`** (called from `_finish_load`, `_set_dirty`, `_on_db_import`):
```python
def _refresh_window_title(self) -> None:
    win = self.window()
    if win is not self:
        base = f"{self._doc_title} — Translation Assistant" if self._doc_title else "Translation Assistant"
        win.setWindowTitle(base + " *" if self._is_dirty else base)
```

**`_set_dirty` change**: replace the inline `win.setWindowTitle(...)` call with `self._refresh_window_title()`.

**`_finish_load` change**: after the existing `_doc_meta = self._db.get_document(self._doc_id)` block, set:
```python
self._doc_title = _doc_meta.get("chapter_title") or _doc_meta.get("title") or ""
self._refresh_window_title()
```

**`_on_db_import` change**: after clearing doc state, add:
```python
self._doc_title = ""
self._refresh_window_title()
```

### Constraint
`_set_dirty`'s early-return guard (`if self._is_dirty == dirty: return`) would suppress the title update when `_is_dirty` is already `False` on first load. Fix: call `_refresh_window_title()` from `_finish_load` directly (independent of `_set_dirty`).

---

## 2. Parse Phrase Counter in Status Bar

### Goal
Show "Phrase 2/5" in the status bar during phrase navigation (Ctrl+→ / Ctrl+←), hidden at all other times.

### Implementation

**New widget** in `_setup_statusbar`:
```python
self._parse_label = QLabel("")
self._parse_label.setVisible(False)
self._status_bar.addWidget(self._parse_label)
```

Add after `self._status_bar.addWidget(self._word_label)`.

**`_advance_parse` change**: after updating `_parse_pointer`, add:
```python
if self._parse_pointer >= 0:
    self._parse_label.setText(f"Phrase {self._parse_pointer + 1}/{len(self._parse_sentences)}")
    self._parse_label.setVisible(True)
else:
    self._parse_label.setVisible(False)
```

**`_retreat_parse` change**: same block after updating `_parse_pointer`.

**`_update_ui_for_pointer` change**: add at end:
```python
self._parse_label.setVisible(False)
```
(Navigation resets parse state — counter is stale and should disappear.)

---

## 3. Progress Bar

### Goal
Replace the plain text "47% Complete" QLabel with a visual `QProgressBar` that shows the same value inline.

### Implementation

**`_setup_statusbar` change**: replace:
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

Replace `self._status_bar.addWidget(self._completion_label)` with `self._status_bar.addWidget(self._progress_bar)`.

**All call sites** (search for `_completion_label`):
- `_completion_label.setText(f"{pct}% Complete")` → `_progress_bar.setValue(pct)`
- `_completion_label.setVisible(visible)` → `_progress_bar.setVisible(visible)`
- `_completion_label.setText(f"{pct}% Complete")` in `_navigate_forward` EOF branch → `_progress_bar.setValue(pct)`

All three call sites are in `main_widget.py`. No other files reference `_completion_label`.

---

## 4. Panel Label Counts

### Goal
- **Source label**: extend to `"Source — Chapter 1 · 24 lines"` (total raw line count)
- **Translation label**: keep a `_translation_label` reference, show `"Translation · N words"` (word count of current translation text), updated on navigation and on text change

### Source label count

In `_finish_load`, after setting `self._doc_title`, update source label to include line count:
```python
n = len(self._raw_lines)
_title_part = f"Source — {self._doc_title}" if self._doc_title else "Source"
self._source_label.setText(f"{_title_part} · {n} lines")
```

Reset to `"Source (read-only)"` in `_on_db_import` (already done by B spec).

### Translation label

**`_setup_central_widget` change**: replace:
```python
self._splitter.addWidget(_labeled("Translation", self._translated_line))
```
with an inline wrapper that keeps `self._translation_label`:
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

**New helper** `_update_translation_label`:
```python
def _update_translation_label(self) -> None:
    text = self._translated_line.toPlainText()
    words = len(text.split()) if text.strip() else 0
    self._translation_label.setText(f"Translation · {words} words")
```

**Call sites**:
- `_finish_load`: call `_update_translation_label()` after setting translated text
- `_update_ui_for_pointer`: call `_update_translation_label()` after setting translated text
- `_setup_central_widget`: connect `self._translated_line.textChanged.connect(self._update_translation_label)` (already has `textChanged` connected to `_on_translation_text_changed`; add second connection)
- `_on_db_import`: reset `self._translation_label.setText("Translation")`

---

## Files Changed

| File | Change |
|------|--------|
| `translation_assistant/ui/main_widget.py` | All 4 items — `_doc_title`, `_refresh_window_title`, `_parse_label`, `_progress_bar`, source label count, `_translation_label` |

No other files need changes.

## Out of Scope

- Animating the progress bar
- Showing parse counter as a tooltip instead of status bar label
- Per-line word count target or session word-count goal

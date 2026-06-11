# Design: Translation Memory + Navigation Improvements

**Date:** 2026-06-11
**Repo:** TranslationAssistant-PySide6-Port

## Goal

Two daily-workflow pain points:

1. **Repeated phrases** — identical raw sentences appear across chapters; user re-translates them manually instead of reusing past work.
2. **Navigation friction** — no way to jump to a specific line number; app forgets which document was open; Open dialog doesn't indicate current position.

---

## Feature 1: Translation Memory Panel

### What it does

When navigating to a line, a read-only panel shows previously translated versions of the **same** raw text from other documents. Clicking a suggestion fills the translation input.

### UI

- New `_tm_panel` (`QTextEdit`, read-only) inserted in the vertical splitter between `_raw_line` and `_translated_line`.
- Each match rendered as a `QPushButton` with text: `<translated text>  —  <doc title>, <date>` (truncated to one line).
- Clicking the button fills `_translated_line` with that translation (raw translation text, not the button label).
- Panel collapses to zero height when no matches exist for the current line.
- Toggle in Settings menu: **"Show Translation Memory"** (checkable). Visibility persisted in `AppSettings.tm_visible`.

### Data

- Exact-match only: `WHERE raw_text = ? AND document_id != <current_doc_id>`.
- Results ordered by `updated_at DESC`, limit 5.
- No fuzzy matching in this iteration.

### Files changed

| File | Change |
|------|--------|
| `translation_assistant/db.py` | Add `find_tm_matches(raw_text, current_doc_id, limit=5) -> list[dict]` |
| `translation_assistant/settings.py` | Add `tm_visible: bool` (default `True`) |
| `translation_assistant/ui/main_widget.py` | Add `_tm_panel` widget; call `find_tm_matches` in `_update_ui_for_pointer`; add Settings toggle action |

---

## Feature 2: Go-to-Line (Ctrl+G)

### What it does

`Ctrl+G` opens a line-number input. User enters a 1-based line number; widget navigates there.

### UI

- Uses `QInputDialog.getInt(self, "Go to Line", "Line (1–N):", value=current+1, min=1, max=N)`.
- On accept, calls the existing internal jump logic (same as `_jump_to_first` / `_jump_to_next_untranslated`).
- No new dialog file needed.

### Files changed

| File | Change |
|------|--------|
| `translation_assistant/ui/main_widget.py` | Add `_on_go_to_line()` handler, `action_go_to_line` QAction (Ctrl+G), add to View menu |
| `translation_assistant/ui/combined_window.py` | Add View menu if not present; wire `action_go_to_line` |

---

## Feature 3: Reliable Resume (Last Document)

### What it does

On startup, the app automatically reopens the last-opened document at the saved position.

### Design

- `AppSettings` gains `last_doc_id: int | None` (default `None`).
- `save_state()` in `TranslationAssistantWidget` writes `self._doc_id` to `settings.last_doc_id` before calling `settings.save()`.
- `_load_initial_state()` checks `settings.last_doc_id`; if not `None` and the doc exists in DB, calls `open_document(last_doc_id)`. Position is already stored in `documents.last_position` and read by `open_document`.
- If the stored doc_id no longer exists (deleted), silently falls back to blank state.

### Files changed

| File | Change |
|------|--------|
| `translation_assistant/settings.py` | Add `last_doc_id` property (int or None) |
| `translation_assistant/ui/main_widget.py` | Update `save_state()` to persist `_doc_id`; update `_load_initial_state()` to restore it |

---

## Feature 4: Open Dialog Pre-Selects Current Document

### What it does

When the Open dialog opens, the currently open document is highlighted in the tree, so the user sees their current position and can quickly pick the next chapter.

### Design

- `OpenDocumentDialog.__init__` gains optional `current_doc_id: int | None = None`.
- After `_load_documents()`, if `current_doc_id` is set, iterate tree items to find the matching leaf and call `self._tree.setCurrentItem(leaf)` + `self._tree.scrollToItem(leaf)`.
- `_on_open()` in `main_widget.py` passes `self._doc_id` as `current_doc_id`.

### Files changed

| File | Change |
|------|--------|
| `translation_assistant/ui/dlg_open.py` | Add `current_doc_id` param to `__init__`; post-load selection |
| `translation_assistant/ui/main_widget.py` | Pass `self._doc_id` to `OpenDocumentDialog` |

---

## Testing

- `test_db.py`: test `find_tm_matches` — exact match found, excluded from same doc, limit respected.
- `test_settings.py`: test `last_doc_id` round-trips through QSettings.
- `test_main_window.py` / `test_combined_window.py`: smoke tests for go-to-line action, resume on load.
- `test_dlg_open.py`: test pre-selection of `current_doc_id` item.

---

## Out of Scope (Spec 2)

Statistics (lines/words per day) and export templates are deferred to a separate spec.

# Open Document Dialog Improvements + Source Editor

**Date:** 2026-06-24  
**Scope:** `translation_assistant/ui/dlg_open.py` (primary), `translation_assistant/core.py` (read-only, reuse existing functions)

---

## Goals

1. Progress color coding in the document tree
2. Doc count on series group headers
3. Sort combo for flexible ordering
4. Preview pane showing first lines of selected document
5. Source text editor allowing OCR fixes and paragraph restructuring

---

## Architecture

All changes are self-contained in `dlg_open.py`. No new files. Reuses existing `db.get_lines()`, `db.replace_raw_content()`, `core.build_new_file()`, `core.parse_file_content()`.

---

## Components

### 1. Progress color coding

In `_load_documents`, after creating each leaf item:

- `0%` → gray foreground (`#888888`)
- `1–99%` → amber (`#c8a000`)
- `100%` → green (`#2a8a2a`)

Applied via `leaf.setForeground(1, QColor(...))`.

### 2. Doc count on series group headers

After all children of a group are added, update the group label:

```
group_item.setText(0, f"{series} ({child_count})")
```

Computed from the count of docs belonging to that series.

### 3. Sort combo

A `QComboBox` placed above the filter bar (`_sort_combo`). Options:

| Label | Sort behavior |
|---|---|
| Series Order (default) | Groups: alphabetical by series name. Leaves: `series_order` asc |
| Last Edited | Groups: by most-recently-edited leaf desc. Leaves: `updated_at` desc |
| Progress ↑ | Groups: by min progress asc. Leaves: `progress` asc |
| Progress ↓ | Groups: by max progress desc. Leaves: `progress` desc |
| Title A→Z | Groups: alphabetical (unchanged). Leaves: title alpha |

`_sort_combo.currentIndexChanged` connects to `_load_documents` (full reload). `_load_documents` reads `_sort_combo.currentIndex()` to determine sort key.

`list_documents()` already returns all needed fields (`series_order`, `updated_at`, `progress`, `chapter_title`, `title`).

### 4. Preview pane

Layout change: the `QTreeWidget` is placed inside a `QSplitter` (vertical). Below it, a `QPlainTextEdit` (`_preview`, read-only, monospace font, ~80px initial height).

On `_on_selection_changed`:
- If no leaf selected: clear preview
- If leaf selected: call `db.get_lines(doc_id)`, take first 8 rows where `raw_text` is non-empty, join `raw_text` values with `\n`, set as preview text

Preview pane has no label/border — minimalist. Splitter sizes: `[300, 80]` initial.

### 5. Source editor (`_EditSourceDialog`)

New button **"Edit Source…"** in the button row (between "Edit…" and "Delete"). Enabled only when a leaf is selected.

`_on_edit_source` opens `_EditSourceDialog(doc_id, db, parent=self)`.

**`_EditSourceDialog`** (~60 lines):

- Signature: `__init__(self, doc_id: int, doc_title: str, db: Database, parent=None)`
- Caller (`_on_edit_source`) passes `leaf.text(0)` as `doc_title`
- `__init__`: loads `db.get_lines(doc_id)`, strips `%`/`$` prefix from each `raw_text`, joins with `\n`, sets into a `QPlainTextEdit` (monospace, wraps)
- Title: `"Edit Source — {doc_title}"`
- Buttons: **Save** (default) and **Cancel**
- On Save:
  ```python
  text = editor.toPlainText()
  formatted = build_new_file(text)
  raw_lines, _, _ = parse_file_content(formatted)
  db.replace_raw_content(doc_id, raw_lines)
  ```
  Then `accept()`. Parent dialog calls `_load_documents()` after dialog returns `Accepted`.

**Translation preservation:** `replace_raw_content` maps old translations to new line indices. For pure OCR fixes (same line count), translations are preserved 1:1. For structural changes (merge/split), translations shift by index — same behavior as Re-fetch.

**Re-processing note:** `build_new_file` splits on `。`, so saving re-applies sentence-boundary splitting. This is intentional and consistent with the existing import/refetch pipeline. Users restructuring paragraphs get correct `%`/`$` prefix assignment automatically.

---

## UI Layout (button row)

```
[stretch] [Open] [Edit…] [Edit Source…] [Delete] [Re-fetch] [Cancel]
```

---

## Data flow

```
_EditSourceDialog.save()
  → build_new_file(edited_text)         # core.py: plain text → prefixed format
  → parse_file_content(formatted)       # core.py: → raw_lines list
  → db.replace_raw_content(doc_id, ...) # db.py: preserves translations by index
  → _load_documents()                   # refresh tree
```

---

## Error handling

- Source editor: no special error handling needed (local text edit, no network)
- Preview: if `get_lines` returns empty list, preview shows empty string

---

## Testing

Existing tests in `test_dlg_open.py` cover `OpenDocumentDialog`. New tests needed:
- `test_progress_color`: verify `0%` / `50%` / `100%` set correct foreground colors
- `test_doc_count_in_header`: verify series label includes `(N)` count
- `test_sort_combo_last_edited`: verify document order changes on sort selection
- `test_preview_loads_on_selection`: verify preview text matches first raw lines of doc
- `test_edit_source_dialog_save`: create doc with known lines, edit text, verify `get_lines` reflects changes after save

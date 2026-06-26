# Open Document Dialog — Two-Panel Redesign

**Date:** 2026-06-26  
**File:** `translation_assistant/ui/dlg_open.py`

## Goal

Replace the current single-tree layout with a two-panel (series | chapters) layout that eliminates cross-series scrolling, removes the unused preview panel, and adds sortable columns plus chapter context menu actions.

## Layout

```
┌────────────────────────────────────────────────────────────┐
│                 [Filter chapters…              ]            │
├──────────────────────┬─────────────────────────────────────┤
│ (No Series) (3)      │ # ▲  │ Title       │ Progress│ Edit │
│ My Series (47)  ◄    │  1   │ Chapter 1   │  100%   │ …   │
│ Another (12)         │  2   │ Chapter 2   │   45%   │ …   │
│                      │  …                                  │
├──────────────────────┴─────────────────────────────────────┤
│ [Open] [Edit…] [Edit Source…] [Delete] [Re-fetch] [Cancel] │
└────────────────────────────────────────────────────────────┘
```

## Panels

### Left — Series list (`QListWidget`)

- Default width ~220 px, user-resizable via `QSplitter` (horizontal orientation)
- `(No Series)` always first entry
- Named series sorted A→Z below it
- Each entry: `Series Name (N)` where N = chapter count
- Selected entry highlighted with standard Qt selection style
- Right-click → context menu: **Manage Series…** (replaces current leaf-level context menu)

### Right — Chapter list (`QTreeWidget`)

Columns (left to right):

| Column | Source | Header | Resize mode |
|--------|--------|--------|-------------|
| `#` | `series_order` | `#` | ResizeToContents |
| Title | `chapter_title` or `title` | `Title` | Stretch |
| Progress | `progress` | `Progress` | ResizeToContents |
| Last Edited | `updated_at` | `Last Edited` | ResizeToContents |

- `setSortingEnabled(False)`; header `sectionClicked` signal → Python sort with asc/desc toggle
- Arrow indicator appended to active sort column header label: `Title ▲` / `Title ▼`
- Default sort: `#` ascending (series_order)
- Progress display: `45%` coloured as before (grey = 0, amber = partial, green = 100)
- Double-click or Enter → open document

### Filter

- Single `QLineEdit` above the chapter panel (`Filter chapters…` placeholder)
- Filters chapter titles in the right panel only; does not affect series panel
- Filter clears when switching series

## Removed

- `QPlainTextEdit` preview widget
- Vertical `QSplitter`
- Sort `QComboBox`

## Right-click context menu on chapters

```
Open
─────────────
Edit…
Edit Source…
─────────────
Re-fetch        (disabled / greyed when no source_url)
─────────────
Delete
```

Same actions as bottom buttons; Delete still prompts confirmation.

## Keyboard navigation

- Tab switches focus between left (series) and right (chapter) panels
- Arrow keys navigate within focused panel
- Enter on a chapter → open

## Persistence

- Last-selected series name saved to `QSettings` key `open_dialog/last_series`
- Restored on next open (if series still exists); fallback to first series

## Sorting implementation

`header().sectionClicked` → `_sort_chapters(col)`:

```python
# ponytail: column-specific key functions; progress stored as int in UserRole
_SORT_KEYS = {
    0: lambda item: item.data(0, Qt.ItemDataRole.UserRole) or 0,   # series_order int
    1: lambda item: item.text(1).lower(),                           # title
    2: lambda item: item.data(2, Qt.ItemDataRole.UserRole) or 0,   # progress int
    3: lambda item: item.text(3),                                   # ISO date sorts lexically
}
```

`UserRole` data set at item creation: col 0 = `int(series_order)`, col 2 = `int(progress)`.

## Out of scope

- Batch selection / multi-delete
- Series-level filter
- Pagination or virtual scrolling (Qt handles 1k items natively)

# Chapter Reorder in Open Document Dialog — Design

**Date:** 2026-07-06
**Problem:** Chapters imported from a poorly-sorted folder have wrong `series_order`
values. Column-click sort in `OpenDocumentDialog` is view-only; the persisted order
stays wrong.

## Solution

Two persisted reorder mechanisms in `OpenDocumentDialog`, both writing
`series_order` back to the DB.

### 1. `core.natural_key(s)` (new, core.py)

Natural sort key so `ch2 < ch10`: split on digit runs via `re.split(r"(\d+)", s)`,
digit tokens become `int`, text tokens lowercased.

### 2. `Database.set_series_orders(pairs)` (new, db.py)

`pairs: list[tuple[doc_id, series_order]]`. One `executemany` UPDATE + one commit.
Only DB change.

### 3. Bulk renumber — "Renumber by Title"

New chapter context-menu action. Takes all chapters of the currently shown series,
natural-sorts by displayed title (col 1), writes `series_order = 1..N`, reloads the
tree.

### 4. Drag-and-drop reorder

- `_tree` becomes an internal `QTreeWidget` subclass whose `dropEvent` calls
  `super()` then a persist callback.
- `DragDropMode.InternalMove`; each item's `ItemIsDropEnabled` flag cleared so
  drops land between rows, never nesting.
- Persist: walk top-level items in visual order (hidden-by-filter included),
  assign `series_order = 1..N`, save via `set_series_orders`, refresh "#" column,
  reset sort header to "# ascending" (drag defines the new canonical order).
- WYSIWYG: order shown after drop = order saved, regardless of prior column sort.

## Edge cases

- Works on the "(No Series)" group too.
- Filtered (hidden) items keep their relative position on drag persist.

## Testing

- `natural_key` → test_core.py
- `set_series_orders` → test_db.py
- Renumber-by-title + drag persist (`_persist_tree_order`) → test_dlg_open.py

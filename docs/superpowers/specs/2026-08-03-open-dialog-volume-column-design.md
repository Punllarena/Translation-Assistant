# Open Dialog Volume Column — Design Spec

**Goal:** Show which volume each chapter belongs to directly in `OpenDocumentDialog`'s chapter tree, so users don't have to open "Edit Volume…" just to see the grouping.

**Background:** `Database.list_documents()` already returns `volume_title` per document (added in the edit-volume-metadata feature), and `OpenDocumentDialog` already caches it per row in `self._volume_titles` (used only for the "Edit Volume…" button's enable/disable state). It is not currently displayed anywhere in the tree.

**Out of scope:** No new column sorting by a numeric ordinal — `volume_title` is text, sorted as text. No filter-box changes (filter stays scoped to chapter title only, per decision). No schema change. A future `volume_index INTEGER` column remains a noted dependency for the separate WP-ToC-separation spec, not needed here since `series_order` already provides correct global reading-order across volumes at import time (`get_next_series_order` increments per-series regardless of volume).

## Design

**Column & data flow.** Add a "Volume" column to the tree in `_load_chapters` (`translation_assistant/ui/dlg_open.py`), populated from `doc.get("volume_title", "")` — already available from `list_documents()`, no new query. Blank cell for legacy/plain/syosetu documents (`volume_title == ""`).

**Placement.** Inserted right after "Order", before "Chapter" (reflects reading order: series → volume → chapter, even though the tree itself stays flat, non-nested).

**Sorting.** Wired into the existing `_sort_col`/`_update_sort_header` header-click sort mechanism as a plain text-sort column (same treatment as "Chapter").

**Filtering.** Unchanged — `_apply_filter` continues to match chapter title only.

**Edge cases:**
- Blank `volume_title` sorts before any named volume alphabetically — acceptable, no special-case needed.
- `_EditVolumeMetadataDialog`'s rename flow already reloads the tree (`_do_edit_volume` → `_load_series` → `_restore_series`) and refreshes `_volume_titles`, so the new column stays in sync automatically — no additional wiring required.
- Column width follows whatever sizing convention the existing columns use (no explicit new sizing requirement).

## Testing

- `test_tree_shows_volume_title_column` — create one document with `volume_title="Vol 1"` and one with no volume_title; load the dialog; assert the Volume column's cell text is `"Vol 1"` for the first row and empty for the second.

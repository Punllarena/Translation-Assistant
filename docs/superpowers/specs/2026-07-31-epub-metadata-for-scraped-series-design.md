# EPUB metadata for non-epub-imported series

## Problem

`_on_export_epub_series` (`ui/main_widget.py`) already exports any series to
EPUB, grouped by `volume_title`. For series built from `ImportEpubDialog`,
each doc carries `volume_title`/`volume_author`/`volume_illustrator`/
`volume_publisher`/`volume_identifier` and an optional cover image, all
stamped at import time. Series built by scraping (syosetu fetch) never pass
through that dialog, so every doc has `volume_title=""` and blank metadata
fields — the exported EPUB falls back to the series title with no author,
publisher, identifier, or cover.

There is currently no way to set this metadata for a scraped series short of
re-importing it as an EPUB.

## Scope

Single volume only. A scraped series always sits in the one
`volume_title=""` bucket today (nothing groups its docs into multiple
volumes), and this feature does not change that — it only lets the user
attach book-level metadata and a cover to that single bucket before export.
Splitting a scraped series into multiple EPUB volumes is a separate,
un-scoped feature.

## Design

### DB layer (`db.py`)

- `update_volume_metadata(series_title, volume_title, *, author="", illustrator="", publisher="", identifier="") -> int`
  Runs `UPDATE documents SET volume_author=?, volume_illustrator=?, volume_publisher=?, volume_identifier=? WHERE series_title=? AND volume_title=?`.
  Returns the affected row count.
- `set_volume_title(series_title, old_volume_title, new_volume_title) -> None`
  `UPDATE documents SET volume_title=? WHERE series_title=? AND volume_title=?`.
  Only invoked by the dialog when the title actually changed, since it
  changes the grouping key the exporter buckets on, not just a metadata
  column.
- `get_volume_metadata(series_title, volume_title) -> dict`
  Reads title/author/illustrator/publisher/identifier plus whether a cover
  exists (reuses `volume_has_cover`), from the first matching doc. Used to
  prefill the dialog. Mirrors the existing `get_series_wp_meta`.
- `replace_document_cover(document_id, src_path, data) -> None`
  Deletes any existing `is_cover=1` row for `document_id`, then inserts the
  new one via the existing `add_document_image` insert shape. Avoids
  orphaned duplicate cover rows when the user re-picks a cover.
- Clearing a cover: delete the `is_cover=1` row for that doc directly (no
  new bytes to insert).

### UI (`ui/dlg_series.py`)

- New `QAction("Set EPUB Metadata…")`, added next to the existing
  `_set_wp_action` in both the toolbar/menu wiring and the context menu —
  same discovery path as "Set WP Fields…".
- `_on_set_epub_metadata()`: same shape as `_on_set_wp_fields` — a small
  `QDialog` with a `QFormLayout`:
  - `QLineEdit` x5: Volume Title, Author, Illustrator, Publisher, Identifier
    — prefilled from `get_volume_metadata(series_title, "")`.
  - Cover row: filename label (or "None") + "Browse…" button
    (`QFileDialog.getOpenFileName`, image filter) + "Clear" button.
  - Standard Save/Cancel `QDialogButtonBox`.
- On accept:
  1. If the volume title field changed from its prefilled value, call
     `set_volume_title(series_title, "", new_title)`.
  2. Call `update_volume_metadata(series_title, new_title or "", author=, illustrator=, publisher=, identifier=)`.
  3. If a new cover file was picked: read its bytes, call
     `replace_document_cover(first_doc_id, path, data)`.
     If "Clear" was used: delete the existing cover row.
     If neither: leave the existing cover untouched.

### Error handling

- The menu item is only reachable when a series row is selected, which
  requires the series to already have ≥1 document (`get_series_list_full`),
  so there is no empty-series case to guard against.
- Cover file bytes are read as-is; `mimetypes.guess_type` (already used in
  `build_epub`) falls back to `application/octet-stream` for unrecognized
  extensions, so no separate validation is needed.

### Testing

- `test_db.py`: `update_volume_metadata`, `set_volume_title`,
  `get_volume_metadata`, `replace_document_cover` (including the "replace
  deletes the old cover row" case), and cover-clear.
- `test_dialogs.py` (or the series-manager test module): dialog prefill from
  existing volume metadata, save writes through to the DB, cover
  browse/clear wiring using the existing file-path/dict injection style
  already used for similar dialogs in the test suite.

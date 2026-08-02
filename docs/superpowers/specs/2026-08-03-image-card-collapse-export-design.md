# Image Cards: Collapse/Expand and Export Toggle

Date: 2026-08-03

## Problem

Inline illustrations render in the card list as bare, non-interactive `QLabel`
widgets ([card_list.py:416](../../../translation_assistant/ui/card_list.py)).
Two gaps:

1. On image-heavy chapters they consume a lot of vertical scroll with no way to
   get them out of the way.
2. Every non-cover image is exported unconditionally, to both EPUB and
   WordPress. There is no way to keep an image in the working document but omit
   it from output.

## Scope

- Per-image collapse/expand, plus a global collapse-all toggle.
- Per-image "Export" checkbox gating **both** EPUB export and WordPress publish
  with a single flag.
- Applies to inline images only. Cover images are filtered out of the card list
  before it is populated ([main_widget.py:595](../../../translation_assistant/ui/main_widget.py))
  and their export path is untouched.

Out of scope: deleting images, reordering images, changing anchor positions,
per-target export flags (EPUB vs WP separately).

## Data model

`document_images` gains one column, added through the existing idempotent
`PRAGMA table_info` migration pattern in `Database._apply_schema()`:

```sql
exclude_export INTEGER NOT NULL DEFAULT 0
```

Default 0 means every image in an existing database keeps exporting after the
upgrade — the migration changes no behaviour on its own.

`get_document_images()` returns the new column in its row dicts. One new
method:

```python
def set_image_exclude_export(self, image_id: int, exclude: bool) -> None
```

Collapse state gets **no** column. It is session-only view state. The global
default is stored in `AppSettings` under `images_collapsed` (bool).

## Widget

A new `ImageCard(QWidget)` in `card_list.py` replaces the `QLabel` returned by
`_make_image_widget`.

```
ImageCard (objectName "CardImage")
├── header QHBoxLayout
│   ├── QToolButton  chevron (▾ / ▸), flat, toggles collapse
│   ├── QLabel       "Image N"
│   ├── stretch
│   └── QCheckBox    "Export"
└── QLabel           pixmap, scaledToWidth(400)   ← hidden when collapsed
```

The header remains visible while collapsed, so the export checkbox is reachable
without expanding the image.

`ImageCard` is deliberately **not** a `LineCard`: no line index, no
participation in navigation, spellcheck, or progress counting. This matches the
current `QLabel` behaviour exactly.

`"Image N"` numbers inline images 1..n in anchor order within the document.
Covers are absent from the list and therefore unnumbered.

### Signals

- `export_toggled(image_id: int, exclude: bool)` — consumed by
  `TranslationAssistantWidget`, which calls `db.set_image_exclude_export(...)`
  immediately. No dirty-flag plumbing; the write is small and atomic.
- Collapse emits nothing; it is handled inside the widget.

### Compatibility

Existing tests construct image dicts without an `"id"` key. `ImageCard` reads
it with `image.get("id")` and suppresses `export_toggled` when it is absent, so
those tests continue to pass unmodified.

## CardListView

- `_image_widgets` becomes `list[ImageCard]`.
- New method `set_images_collapsed(collapsed: bool)` applies the state to every
  existing `ImageCard`.
- `_build_batch` applies the current global default to each `ImageCard` as it is
  constructed, so chunked builds stay consistent with the menu state.

## Menu

`TranslationAssistantWidget._build_actions()` adds a checkable `QAction`,
`action_collapse_images`, labelled "Collapse Images".
`CombinedMainWindow._setup_menubar()` places it in the View menu.

Toggling it writes `AppSettings.images_collapsed` and calls
`card_view.set_images_collapsed(...)`. Its checked state is initialised from
settings at startup, so a document opens collapsed if that is where the user
left the toggle.

Per-image chevrons override the global state freely within a session. Toggling
the menu action re-applies to every image.

## Exports

Both consumers already filter out covers. Each gains one condition:

```python
inline_images = [im for im in all_images
                 if not im["is_cover"] and not im["exclude_export"]]
```

- [main_widget.py:1261](../../../translation_assistant/ui/main_widget.py) — EPUB export
- [main_widget.py:1452](../../../translation_assistant/ui/main_widget.py) — WordPress publish

The EPUB path's cover lookup reads the unfiltered `all_images`, so excluding an
inline image can never suppress the cover.

Excluded images remain in the database and remain visible in the card list. The
checkbox is an export filter, never a delete.

## Testing

`test_db.py`
- `exclude_export` defaults to 0 for rows created before the migration.
- `set_image_exclude_export` round-trips through `get_document_images`.

`test_card_list.py`
- Chevron hides the pixmap while the header stays visible; expanding restores it.
- Checkbox emits `export_toggled` with the correct image id and value.
- `set_images_collapsed` applies to every `ImageCard` in the list.
- Image dicts lacking `"id"` do not raise and do not emit.

`test_main_window.py`
- An image with `exclude_export=1` is absent from the EPUB export image list.
- An image with `exclude_export=1` is absent from the WP publish payload.
- A cover still resolves when an inline image is excluded.

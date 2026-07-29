# EPUB Illustration Preservation (Sidecar Anchor Design)

## Goal

Follow-up to [2026-07-30-epub-import-export-design.md](2026-07-30-epub-import-export-design.md)
(text-only import/export, already shipped as its own spec). This spec restores
the two categories of image that spec #1 explicitly dropped:

- **Inline illustrations**: standalone `<p><img class="fit" src="..."/></p>`
  paragraphs, position-anchored within the chapter.
- **Cover image**: the volume's cover, from the OPF's cover-image manifest
  entry.

Gaiji glyph substitution (`<img alt="〜">` used as a font workaround for a
missing character) is unaffected — it was already handled in spec #1 by
folding the `alt` text into the sentence stream, and stays that way; it was
never a "dropped image" in the first place.

## Why sidecar, not a third line-kind

`raw_lines`/`translated_lines` (in `lines`, one row per document) are walked
by ~8-10 existing functions that assume every entry is translatable text:
`core.line_has_content`, `calculate_progress`, `build_clipboard_output`,
`build_markdown_translation`/`_ruby`, the spellcheck loop, `card_list.py`'s
index-to-`LineCard` mapping, and `main_widget.py`'s keyboard line navigation.
A third `#` "this is an image" row kind would require an image-skip branch in
every one of them.

Instead, images live in their own table and are never part of that array.
Only the two places that reconstruct a full chapter for *display* — the card
editor and EPUB export — need to merge images back in at render time. This
app has no per-line insert/delete/reorder operation (only whole-chapter
reordering via `series_order` exists — see `2026-07-06-chapter-reorder-design.md`),
so there's no operation that could make a stored `anchor_position` drift out
of sync with `raw_lines` after import.

## Schema

```sql
CREATE TABLE document_images (
    id              INTEGER PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    anchor_position INTEGER NOT NULL DEFAULT 0,
    is_cover        INTEGER NOT NULL DEFAULT 0,
    src_path        TEXT    NOT NULL,
    data            BLOB    NOT NULL
);
```

`anchor_position` is an insertion index into that document's `raw_lines`
array: 0 means "before the first line," `len(raw_lines)` means "after the
last line." Ties (rare: two illustrations back to back with no text between)
break on `id` order.

`is_cover` is a separate flag rather than an `anchor_position` sentinel — a
cover doesn't sit between two paragraphs, it isn't part of the text stream at
all. It attaches to whichever chapter document is created *first* within an
import batch, since there's no dedicated "volume" entity in the schema to
hang it on instead (`volume_title` is just a string column on `documents`).

Attaching per-*batch* rather than per-*volume* is only safe if a volume is
never imported across two separate batches. It can be: a user may import a
volume with some chapters unchecked, then later reopen the dialog on the
same file to pull in the rest — each batch's "first document created in
this batch" would otherwise attach its own cover, leaving the volume with
duplicate `is_cover` rows. Guarded below by checking before attaching,
rather than assuming single-batch import.

`db.py` additions:
- `add_document_image(document_id, anchor_position, is_cover, src_path, data) -> int`
- `get_document_images(document_id) -> list[dict]` — ordered by
  `(anchor_position, id)`, `is_cover` rows included (callers filter as needed).
- `volume_has_cover(series_title: str, volume_title: str) -> bool` — joins
  `document_images` to `documents` filtered on `series_title`/`volume_title`/
  `is_cover=1`. Powers the import-time guard below.

## Import (`epub.py`)

### Cover discovery

`open_book()` gains a `cover_href: str | None` key in its return dict —
found via the OPF manifest's `properties="cover-image"` item (EPUB3), falling
back to `<meta name="cover" content="ID">` + the manifest item with that `id`
(EPUB2).

### Anchor position calculation

The hard part: `anchor_position` must index into the *final* `raw_lines`
array, but `build_new_file()` splits each source paragraph into multiple
`%`/`$` sentence lines — "between source paragraph 3 and 4" is not the same
offset as "between raw_lines[3] and raw_lines[4]" once paragraph 3 has split
into two sentences.

Resolved without touching `build_new_file()`'s internals: walk the chapter
body producing an ordered sequence of `("text", paragraph)` /
`("image", src_path, data)` items. For each text item encountered, run it
*alone* through `build_new_file()` + `parse_file_content()` and take the
resulting raw-line count — this is a throwaway counting pass only, since
`build_new_file()`'s sentence-splitting is local per input line and produces
the same count whether run on one paragraph or as part of the full chapter
blob. Accumulate a running offset; each image's `anchor_position` is the
running offset at the point it's encountered. The real `raw_lines`/
`translated_lines` still come from a single `build_new_file()` call on the
full joined text, exactly as spec #1 already does — the per-paragraph calls
never feed the actual output, only the offset count.

Replaces spec #1's `extract_chapter_text` with:

```python
def extract_chapter_content(path: Path, href: str) -> tuple[str, list[dict]]:
    """Returns (text, images).
    text: same joined-paragraph string spec #1 fed to build_new_file().
    images: [{"anchor_position": int, "src_path": str, "data": bytes}, ...]
    in chapter order. Does not include the cover — that comes from
    open_book()'s cover_href, read separately.
    """
```

A standalone illustration `<p>` (the same "sole child is one `<img>`"
heuristic from spec #1) now contributes an image entry instead of being
silently skipped.

### Dialog changes (`dlg_import_epub.py`)

After `create_document()` for each checked chapter, insert its images via
`add_document_image(doc_id, anchor_position, is_cover=0, src_path, data)`.
If `open_book()` returned a `cover_href` **and**
`db.volume_has_cover(series_title, volume_title)` is `False`, read the cover
bytes once and attach to the first document created in this import batch
(`add_document_image(first_doc_id, anchor_position=0, is_cover=1, ...)`). The
guard makes a second, later batch against the same volume (e.g. importing
previously-unchecked chapters) a no-op for the cover instead of creating a
duplicate.

## Export

### `core.py`

`build_epub_paragraphs` (from spec #1) gains a sibling that also accepts the
images list and interleaves by `anchor_position`:

```python
def build_epub_content(
    raw_lines: list[str], translated_lines: list[str], images: list[dict],
) -> list[tuple[str, str]]:
    """Returns ordered [("text", paragraph), ("image", src_path), ...],
    merging build_epub_paragraphs' output with images at their
    anchor_position. images: same shape as extract_chapter_content's return
    (minus "data" — export re-reads bytes from document_images by src_path)."""
```

### `epub.py`

`build_epub()` (from spec #1) gains an images parameter per chapter (bytes +
src_path) and a book-level cover parameter:
- Each chapter image is written into the zip under `OEBPS/images/...`
  (media-type guessed via stdlib `mimetypes.guess_type` — no new dependency),
  referenced via `<img src="images/...">` at its interleaved position in that
  chapter's xhtml, and given a manifest `<item>` entry.
- If a cover is present: its manifest item gets `properties="cover-image"`,
  plus a `<meta name="cover" content="...">` entry in the OPF for
  older-reader compatibility.
- `ponytail:` no dedicated `cover.xhtml` title page is generated — the
  manifest/meta cover metadata alone is enough for the readers that matter.
  Add a real cover page later only if a specific reader needs one.

### `main_widget.py` (`_on_export_epub_series`)

Per chapter, fetch `get_document_images(doc_id)`, split into cover (only
relevant for the volume's first chapter) and inline images, pass inline
images to `build_epub_content` and the cover (if any, from the volume's first
chapter) through to `build_epub()`.

## UI: `card_list.py`

`CardListView` fetches `get_document_images(doc_id)` alongside `raw_lines`/
`translated_lines` when building its card list, and inserts a plain
non-editable `QLabel` (holding a `QPixmap` built from the blob) into the same
`QVBoxLayout` at each image's `anchor_position` — between the `LineCard`s on
either side of it. It does not become a `LineCard`, has no `index`, is not
part of navigation/spellcheck/progress — purely a decorative widget threaded
into the same scroll list. The cover image is not shown inline in the card
list (it belongs to the volume, not to a position within chapter text); it's
only relevant at export time.

## Error handling

- Missing/unreadable image bytes in the zip (broken manifest reference) —
  caught per-image, chapter import continues without that one image (mirrors
  spec #1's per-chapter error tolerance).
- No cover found — `cover_href` is `None`, exported EPUB simply has no cover
  metadata, same as spec #1's baseline (no regression).

## Testing

Extends spec #1's synthetic-EPUB fixture with:
- one chapter containing an illustration after a paragraph that itself
  splits into multiple sentences (verifies `anchor_position` accounts for
  sentence-splitting, not just paragraph count)
- two illustrations with no text between them (verifies `id` tiebreak)
- a cover-image manifest entry (EPUB3 `properties`) and, in a separate
  fixture, the EPUB2 `<meta name="cover">` fallback

`tests/test_epub.py`: `extract_chapter_content` anchor correctness,
`build_epub_content` interleaving, `build_epub()` round-trip (write then
re-parse with `open_book()`/`extract_chapter_content` to confirm images
survive at the same anchor).

`tests/test_dlg_import_epub.py`: importing the same volume in two batches
(first batch with some chapters unchecked, second batch importing the rest)
attaches the cover only once — `volume_has_cover` returns `True` after the
first batch and the second batch's import skips cover-attach entirely.

`tests/test_card_list.py`: image widget appears at the right position in the
card list's layout, doesn't participate in card indexing/navigation.

## Deferred (spec #3 candidate, not this spec)

In-body chapter heading (`<h2 class="oo-midashi">`), span-level formatting
(`bold`, `tcy` vertical-punctuation typesetting), and book-level metadata
(`dc:creator`, `dc:language`, `dc:identifier`/ISBN, publisher/date). None of
these are restored by this spec either — tracked separately per user request,
not folded into illustration work. Now designed in
[2026-07-30-epub-metadata-heading-formatting-design.md](2026-07-30-epub-metadata-heading-formatting-design.md).

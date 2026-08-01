# WP Upload API — Illustration Support

## Goal

The EPUB illustration import
([2026-07-30-epub-illustrations-design.md](2026-07-30-epub-illustrations-design.md))
stores inline chapter images and volume covers in `document_images`, but the
WordPress publish path (`translation_assistant/wp_publisher.py` →
`translation-assistant-publisher` plugin's `/publish` REST route) has no
concept of images at all — `build_payload()` sends text only. This spec
extends the publish payload and the plugin's `TAP_Publisher` to carry and
render both inline illustrations and volume covers.

## Payload schema

`images`/`cover` are new, optional top-level keys on the existing
`/wp-json/ta-publisher/v1/publish` JSON body. Omitted when a document has
none.

```json
{
  "...existing fields...": "unchanged",
  "images": [
    { "position": 2, "filename": "img_003.jpg", "mime": "image/jpeg", "data_base64": "..." }
  ],
  "cover": { "filename": "cover.jpg", "mime": "image/jpeg", "data_base64": "..." }
}
```

- `images[].position`: paragraph-index into the `<p>` blocks
  `build_chapter_body` emits for `chapter_body` — 0 = before the first
  paragraph, N = after the last. Not the same number as `document_images
  .anchor_position` (which indexes `raw_lines`, one row per sentence); see
  mapping below.
- `cover`: present only on the one `publish()` call whose document owns the
  `is_cover=1` row for that volume (per the EPUB spec's "first document
  created in this import batch" rule). Always a real chapter
  (`chapter_index >= 1`) — the synopsis/index-page path (`chapter_index ==
  0`) is never the batch's first document under the current EPUB import
  flow (`dlg_import_epub.py`'s `first_new_doc_id` is only ever set inside
  the per-chapter loop), so the plugin does not need to special-case
  `chapter_index == 0` carrying a cover.
- `required` fields in `translation-assistant-publisher.php` are unchanged;
  `images`/`cover` are additive and optional.

## Anchor mapping (`anchor_position` → `position`)

`document_images.anchor_position` indexes into `raw_lines` (one row per
sentence, post `$`-continuation split). `build_chapter_body` groups
continuation (`$`-prefixed) lines into the same `<p>` as their preceding
non-`$` line, so the two indices diverge whenever a paragraph split into
multiple sentences.

`wp_publisher.py` gains `build_image_payload(lines, images) ->
list[dict]`: re-runs `build_chapter_body`'s grouping loop, and whenever the
loop's raw-line cursor passes an image's `anchor_position`, records the
paragraph count so far as that image's `position`. Ties (two images with
the same `anchor_position`) resolve by `document_images.id` order, matching
the EPUB exporter's tiebreak.

Rejected alternative: send raw `anchor_position` and have the plugin
reconstruct paragraph boundaries from `chapter_body`'s `<p>` tags. Rejected
because it duplicates the line-grouping logic in PHP and the plugin never
receives `raw_lines`, so it has no independent way to validate the mapping
— any future change to `build_chapter_body`'s grouping would silently
desync the two implementations.

## Client changes (`wp_publisher.py`)

- `build_image_payload(lines, images)` — described above. Also base64-
  encodes each image's `data` (`base64.b64encode`, stdlib) and derives
  `mime` via `mimetypes.guess_type(src_path)` (stdlib).
- `build_payload()` gains `images: list[dict] | None = None` and `cover:
  dict | None = None` params, forwarded into the payload dict as `images`/
  `cover` keys when non-empty/non-None.
- Caller (`main_widget.py`'s publish flow, near the existing `build_payload`
  call at `translation_assistant/ui/main_widget.py:1576`) fetches
  `db.get_document_images(doc_id)` once per publish, splits on `is_cover`,
  passes inline images through `build_image_payload` and the cover (if any,
  base64-encoded the same way) into `build_payload`.

## Server changes (plugin)

**`attach_image(string $filename, string $mime, string $base64, int
$post_id): int|WP_Error`** (new, `class-publisher.php`) — decodes the
base64 payload to a temp file, runs `wp_check_filetype`, calls
`media_handle_sideload()` parented to `$post_id`, returns the attachment
ID. Failures return `WP_Error` and are caught per-image by the caller —
one bad image never fails the whole `/publish` call, mirroring the EPUB
importer's existing per-image error tolerance.

**`convert_to_blocks(string $html, array $images = [], ?array $cover =
null): string`** — gains the two new params.
- `$images`: after splitting `$html` into the existing per-paragraph
  `$blocks` array, splice a `wp:image` block at each image's `position`
  (attachment created via `attach_image()`, parented to the chapter page
  being built) before joining with `NAV_BLOCK`/`SEPARATOR` as today.
- `$cover`: if present, `attach_image()` parented to the same chapter page,
  its `wp:image` block prepended before the leading `NAV_BLOCK` (i.e. above
  the nav/separator wrapper entirely, not interleaved with paragraphs).
- Generated block shape per image:
  ```
  <!-- wp:image {"id":123} -->
  <figure class="wp-block-image"><img src="..." class="wp-image-123" alt=""/></figure>
  <!-- /wp:image -->
  ```

**`create_chapter_page()`** passes `$data['images']` and `$data['cover']`
(both default to `[]`/`null` when absent) through to `convert_to_blocks()`.

**`build_index_content()`** — unchanged. The index/series page never
carries a cover (see rejected-design note below); only a volume's own first
chapter page does.

**`publish()`** — no change to control flow. The existing idempotency
short-circuit (`chapter_exists()` → early return before
`create_chapter_page()`) already means `images`/`cover` are inert on a
repeat publish of an existing chapter; no new dedupe logic needed.

**`translation-assistant-publisher.php`** — no change to the `$required`
array; `images`/`cover` are read directly off `$data` inside the publisher
and simply absent when the client sends none.

## Rejected: cover on the series index page

Initial design put the cover as a `wp:image` block in
`build_index_content()`, reasoning it's "the volume's cover" so belongs on
the series page. Wrong: the series index page is a single shared page
across *all* volumes of a series (`find_or_create_index_page()` keys only
on `series_slug`), while covers are per-*volume* (`document_images.is_cover`
guarded by `volume_has_cover(series_title, volume_title)`). A second
volume's cover publish would collide with — overwrite or duplicate next to
— the first volume's cover block on that single shared page. Attaching the
cover to the volume's own first chapter page instead (same page the inline
images and `chapter_body` text already go to) gives each volume's cover a
distinct, uncontested home with no dedupe/replace logic required.

## Idempotency

Images ride along only on first chapter creation (`chapter_exists()` ==
false). Adding an illustration to an already-published chapter later
requires deleting the WP page and re-publishing — the same limitation the
plugin already has for text edits; no update path exists today for either.

## Error handling

- Per-image `attach_image()` failure: `error_log`'d, chapter publish
  continues without that image. Matches the EPUB importer's per-image
  tolerance (broken manifest reference → skip that image, keep the
  chapter).
- No cover / no images in payload: `convert_to_blocks()`'s `$images`/
  `$cover` params default to empty/null, output identical to pre-spec
  behavior.

## Payload size

Base64 inflates image bytes by ~33%. Typical chapters carry 0-3 small
illustrations; the cover is sent once per volume (only on that volume's
first chapter publish). No chunking or streaming needed — a plain JSON
POST is sufficient at this scale.

## Testing

`tests/test_wp_publisher.py`:
- `build_image_payload`: anchor-to-paragraph mapping across a paragraph
  that splits into multiple sentences (position must land on the
  paragraph, not the sentence); two images at the same `anchor_position`
  preserve `id`-order in the output list.
- `build_payload`: `images`/`cover` keys present/absent correctly based on
  params; base64/mime encoding round-trips.

Plugin-side (PHP): there is no automated PHP test harness (no PHPUnit
setup) in the `translation-assistant-publisher` repo. PHP-side
verification for this feature was done manually against a local Docker WP
instance, matching the Global Constraints already stated in the
implementation plan. That manual verification covered:
- `convert_to_blocks()` with images: `wp:image` blocks appear at the right
  paragraph boundaries, cover block appears before `NAV_BLOCK`.
- `attach_image()` failure for one image among several: publish still
  succeeds, other images/text land correctly.
- Two-volume series: publishing volume 2's first chapter with its own
  `cover` does not alter or duplicate anything on the shared index page or
  volume 1's chapter page.

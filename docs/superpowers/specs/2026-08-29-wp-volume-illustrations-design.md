# WordPress Volume Illustrations Gallery — Design Spec

**Date:** 2026-08-29
**Status:** approved, ready for implementation plan

## Goal

Add a menu command **"Publish Volume Illustrations to WordPress…"** that
collects every illustration in the current document's volume and publishes
them as a single WordPress gallery page, linked from the series Table of
Contents under that volume's heading. Readers can then preview a volume's
art in one place — including illustrations that live on chapters with no
translated text (colour plates, frontispieces), which the per-chapter
publish flow currently refuses (`"Nothing to Publish"` guard at
`main_widget.py:1465`).

## Two repositories

| Repo | Path | Language / tests |
|------|------|------------------|
| TA app | `/home/pun/workspace/TranslationAssistant-PySide6-Port` | Python 3 + pytest; `wp_publisher.py` is Qt-free |
| WP plugin | `/home/pun/workspace/wp-dev` (plugin at `plugins/translation-assistant-publisher/`) | PHP 8 + WordPress API; **no test harness** |

**Commit separately in each tree. Never `git add` across them.** The TA
working tree has unrelated in-flight modifications — stage only the exact
files each task names; never `git add -A` / `git commit -a`.

TA venv required before pytest: `source .venv/bin/activate`.

## Decisions (from brainstorming)

- **Output:** one gallery page per volume. Overwrites in place on re-run
  (no duplicate pages).
- **Images:** volume cover first (first `is_cover` image found across the
  volume's chapters, mirroring the series-EPUB export), then every inline
  image that is `not is_cover and not exclude_export`, ordered by chapter
  `series_order` then image anchor order.
- **Scope:** the open document's volume only. No "all volumes" loop, no
  volume picker.
- **TOC:** a `Illustrations` link is added beneath that volume's `<h3>`
  heading on the series index page, via the existing `append_toc_entry()`.
- **Cuts (YAGNI):** no scheduling, no password protection (gallery goes
  live immediately), no per-image captions or chapter labels (flat image
  stack), no teaser `post`.

---

## Part A — WordPress plugin

### A1. New REST route

`translation-assistant-publisher.php` — register a third route alongside
`/publish` and `/status`:

```php
register_rest_route( 'ta-publisher/v1', '/illustrations', [
    'methods'             => 'POST',
    'callback'            => 'tap_handle_illustrations',
    'permission_callback' => '__return_true',
] );
```

`tap_handle_illustrations( WP_REST_Request $request ): WP_REST_Response`:

- `get_json_params()`; 400 if not an array.
- Required fields: `api_key`, `series_title`, `series_slug`,
  `series_title_short`, `series_link`, `images`. `volume_title` optional
  (may be `""` / absent). `cover` optional.
  - `images` must be a non-empty array — 400 `"Missing field: images"`
    otherwise.
- `TAP_Auth::validate_key()` → 401 on failure.
- `new TAP_Publisher()->publish_illustrations( $data, $user_id )`.
- `is_wp_error` → 500 with message; else 200 with the result array.

### A2. `TAP_Publisher::publish_illustrations( array $data, int $user_id ): array|WP_Error`

```
$series_slug  = sanitize_title( $data['series_slug'] );
$volume_title = isset( $data['volume_title'] ) && is_string( $data['volume_title'] )
              ? $data['volume_title'] : '';

$index_id = $this->find_or_create_index_page(
    $series_slug, $data['series_title'], $data['series_link'], $user_id
);
if ( is_wp_error( $index_id ) ) return $index_id;
```

**Gallery slug** — child of the index page:

```
$slug = $volume_title !== ''
      ? "{$series_slug}-illustrations-" . sanitize_title( $volume_title )
      : "{$series_slug}-illustrations";
```

**Find-or-create / overwrite:**

```
$existing = get_page_by_path( "{$series_slug}/{$slug}", OBJECT, 'page' );
```

- If `$existing`: delete its child attachments (same loop as
  `update_chapter_page()`), rebuild `post_content`, `wp_update_post`.
  `created => false, updated => true`.
- Else: `wp_insert_post` a `page` — `post_parent => $index_id`,
  `post_name => $slug`, `post_status => 'publish'`,
  `post_title` per A3, `menu_order => 0`, empty content; then set content
  via `wp_update_post` (so `attach_image` has the real `$post_id`).
  On content-update `WP_Error`, `wp_delete_post( $id, true )` and return
  the error (mirrors `create_chapter_page`). `created => true`.

**TOC link** (both branches, after the page id is known):

```
$this->append_toc_entry( $index_id, 'Illustrations', get_permalink( $gallery_id ), $volume_title );
```

`append_toc_entry` is already idempotent (substring check) and already
emits the volume `<h3>` before the first entry that carries a
`volume_title` — so calling it here before any chapter of the volume is
published is safe and order-independent.

**Return:**

```
[ 'status' => 'ok', 'page_url' => get_permalink( $gallery_id ),
  'created' => $created, 'updated' => ! $created ]
```

### A3. Gallery page content

New private helper, e.g. `build_illustrations_content( array $images, ?array $cover, int $post_id ): string`:

- `post_title`: `"{$volume_title} — Illustrations"` when `$volume_title`,
  else `"{$data['series_title_short']} Illustrations"`. (Computed in
  `publish_illustrations` and passed to `wp_insert_post`/`wp_update_post`;
  the content helper only builds the body.)
- Body: if `$cover`, `attach_image()` it and prepend its
  `image_block()`. Then for each entry in `$images`, `attach_image()` and
  append `image_block()`. On any `attach_image` `WP_Error`, `error_log`
  and skip that image (same tolerance as `convert_to_blocks`).
- Blocks joined with `"\n\n"`. **No** `NAV_BLOCK`, **no** `SEPARATOR`.
- Each image dict is `{ filename, mime, data_base64 }` — same shape
  `convert_to_blocks` already consumes, minus `position`.

`image_block()` and `attach_image()` are reused unchanged.

### A4. Version bump

`translation-assistant-publisher.php` header `Version: 1.5.2` → `1.5.3`.

### A5. Plugin files touched

- Modify: `plugins/translation-assistant-publisher/translation-assistant-publisher.php`
  (route + `tap_handle_illustrations` + version)
- Modify: `plugins/translation-assistant-publisher/includes/class-publisher.php`
  (`publish_illustrations` + `build_illustrations_content`)
- No new files.

---

## Part B — TA app

### B1. `wp_publisher.py` — payload + client

**Refactor:** extract the shared POST/JSON/`HTTPError`-body logic from
`publish()` into `_post_json(url: str, payload: dict, timeout: int) -> dict`.
`publish()` keeps its 409-specific branch (that stays in `publish`, not in
the shared helper) — so `_post_json` covers the common path and `publish`
wraps it. Simplest split: `_post_json` does the request + success JSON +
generic `HTTPError`/`URLError` → `WPPublishError`; `publish` calls it and,
for the 409 case, catches `WPPublishError` with `status_code == 409` and
returns `{"created": False}` / the parsed body. If that reshaping proves
awkward, leave `publish` fully intact and give `publish_illustrations` its
own small request block — duplication of ~15 lines is acceptable.

**New:** `_ILLUSTRATIONS_PATH = "/wp-json/ta-publisher/v1/illustrations"`
and

```python
def publish_illustrations(endpoint_url: str, payload: dict, timeout: int = 15) -> dict:
    base = endpoint_url.rstrip("/")
    if base.endswith(_ENDPOINT_PATH):
        base = base[: -len(_ENDPOINT_PATH)]
    url = base + _ILLUSTRATIONS_PATH
    ...POST JSON, same error handling as publish()'s non-409 path...
```

**New:** `build_illustrations_payload`:

```python
def build_illustrations_payload(
    doc_meta: dict,
    series_meta: dict,
    images: list[dict],
    api_key: str,
    cover: dict | None = None,
) -> dict:
    if not series_meta.get("series_slug"):
        raise ValueError("series_slug is required — set it in Series Manager")
    if not series_meta.get("series_title_short"):
        raise ValueError("series_title_short is required — set it in Series Manager")
    payload = {
        "api_key":            api_key,
        "series_title":       doc_meta["series_title"],
        "series_slug":        series_meta["series_slug"],
        "series_title_short": series_meta["series_title_short"],
        "series_link":        series_meta["syosetu_url"],
        "images":             [_encode_image(im) for im in images],
    }
    if doc_meta.get("volume_title"):
        payload["volume_title"] = doc_meta["volume_title"]
    if cover is not None:
        payload["cover"] = _encode_image(cover)
    return payload
```

`_encode_image` already returns `{filename, mime, data_base64}` — reused
as-is; the `position` key that `build_image_payload` adds is simply not
applied here.

### B2. `main_widget.py`

**Action** (in `_build_actions`, near `action_publish_wp`):

```python
self.action_publish_volume_illus = QAction("Publish Volume Illustrations to WordPress…", self)
self.action_publish_volume_illus.triggered.connect(self._on_publish_volume_illustrations)
self.action_publish_volume_illus.setEnabled(False)
```

Enable it wherever `action_publish_wp` is enabled/disabled
(`main_widget.py:622` enable, `:1390` disable, `:1609`/`:1677`/`:1681`
around the publish worker — match the same lifecycle).

**Extract** an `_ensure_wp_ready()` helper from the top of
`_on_publish_wp` (lines ~1407–1459): endpoint/api-key resolution
(prompting `WPSettingsDialog` when missing) plus the
series-slug/short-title guard (prompting `SeriesManagerDialog`). Returns
`(endpoint_url, api_key, series_meta)` or `None` if the user backed out.
`_on_publish_wp` calls it; `_on_publish_volume_illustrations` calls it.

**Handler:**

```python
def _on_publish_volume_illustrations(self) -> None:
    self._save_current_translation()
    if self._doc_id is None:
        return
    doc_meta = self._db.get_document(self._doc_id)
    series_title = doc_meta["series_title"]
    volume_title = doc_meta.get("volume_title", "")

    ready = self._ensure_wp_ready(series_title)
    if ready is None:
        return
    endpoint_url, api_key, series_meta = ready

    import mimetypes
    doc_ids = self._db.get_document_ids_by_series(series_title)
    vol_doc_ids = [
        d for d in doc_ids
        if self._db.get_document(d).get("volume_title", "") == volume_title
    ]
    # doc_ids from get_document_ids_by_series is already series_order-ordered;
    # confirm in the plan and keep that order.

    inline_images: list[dict] = []
    cover_image: dict | None = None
    for d in vol_doc_ids:
        for im in self._db.get_document_images(d):
            if im["is_cover"]:
                if cover_image is None:
                    cover_image = im
            elif not im["exclude_export"]:
                inline_images.append(im)

    if not inline_images and cover_image is None:
        QMessageBox.information(self, "No Illustrations",
                               "This volume has no illustrations to publish.")
        return

    vol_label = volume_title or series_title
    n = len(inline_images) + (1 if cover_image else 0)
    if QMessageBox.question(
        self, "Publish Volume Illustrations",
        f"Publish {n} illustration(s) from “{vol_label}” to WordPress?\n\n"
        "An existing illustrations page for this volume will be overwritten.",
    ) != QMessageBox.StandardButton.Yes:
        return

    from translation_assistant.wp_publisher import build_illustrations_payload
    try:
        payload = build_illustrations_payload(
            doc_meta, series_meta, inline_images, api_key=api_key, cover=cover_image,
        )
    except ValueError as exc:
        QMessageBox.warning(self, "Payload Error", str(exc))
        return

    self.action_publish_volume_illus.setEnabled(False)
    self._illus_worker = _PublishWorker(
        endpoint_url, payload, parent=self, publish_fn=publish_illustrations,
    )
    self._illus_worker.succeeded.connect(self._on_publish_illus_done)
    self._illus_worker.error.connect(self._on_publish_illus_error)
    self._illus_worker.start()
```

`_on_publish_illus_done(result)` — re-enable the action, show a
`QMessageBox` with `result.get("page_url")` (and a "created / updated"
word from `result`). `_on_publish_illus_error(msg)` — re-enable, warn.

**`_PublishWorker`** (`main_widget.py:28`) gains a `publish_fn` ctor kwarg
defaulting to the module-level `publish`; its `run()` calls
`self._publish_fn(...)` instead of the hard import. Import
`publish_illustrations` where `_PublishWorker`'s call site needs it.

### B3. `combined_window.py`

`_setup_menubar` — add after line 117:

```python
file_menu.addAction(ta.action_publish_volume_illus)
```

### B4. Tests — `tests/test_wp_publisher.py`

- `build_illustrations_payload` with `volume_title` set → key present;
  with `doc_meta["volume_title"] == ""` → key absent, no error.
- `images` list order preserved; each entry has
  `filename`/`mime`/`data_base64`, **no** `position`.
- `cover=None` → no `cover` key; `cover` given → `cover` key with encoded
  dict.
- Missing `series_slug` / `series_title_short` in `series_meta` →
  `ValueError`.
- `publish_illustrations` builds the `/wp-json/ta-publisher/v1/illustrations`
  URL from a bare site URL and from one already ending in
  `/wp-json/ta-publisher/v1/publish` (monkeypatch `urllib.request.urlopen`,
  assert the `Request.full_url`).

### B5. TA files touched

- Modify: `translation_assistant/wp_publisher.py`
- Modify: `translation_assistant/ui/main_widget.py`
- Modify: `translation_assistant/ui/combined_window.py`
- Modify: `tests/test_wp_publisher.py`
- No new files.

---

## Data flow

```
user → File ▸ Publish Volume Illustrations…
  main_widget._on_publish_volume_illustrations
    _save_current_translation
    _ensure_wp_ready(series_title) → endpoint, api_key, series_meta
    db.get_document_ids_by_series → filter by volume_title
    db.get_document_images  per doc → cover (first) + inline (not is_cover, not exclude_export)
    confirm dialog
    wp_publisher.build_illustrations_payload(doc_meta, series_meta, inline, api_key, cover)
    _PublishWorker(publish_fn=wp_publisher.publish_illustrations) → POST /ta-publisher/v1/illustrations
       plugin tap_handle_illustrations → TAP_Publisher::publish_illustrations
         find_or_create_index_page
         get_page_by_path(series/slug-illustrations[-volume])  → insert | (wipe attachments + update)
         build_illustrations_content(cover first, then images) via attach_image + image_block
         append_toc_entry(index_id, "Illustrations", gallery_url, volume_title)
       → { status, page_url, created, updated }
    _on_publish_illus_done → QMessageBox with page_url
```

## Edge cases

- **Volume with only a cover, no inline images:** still publishes (page
  with one image). Guard only blocks when both are empty.
- **`volume_title == ""`** (syosetu-imported series with no EPUB volume
  grouping): slug falls back to `{series_slug}-illustrations`, title to
  `"{short} Illustrations"`, `append_toc_entry` adds a bare link with no
  `<h3>` — matches existing behaviour for volume-less chapters.
- **Re-run after adding/removing an image:** existing page's attachments
  are deleted and content rebuilt; TOC link already present, substring
  check skips a duplicate.
- **Gallery published before any chapter of the volume:** `append_toc_entry`
  emits the `<h3>` now; later chapter publishes see it and skip — order
  independent, by existing design.
- **Synopsis doc (`series_order == 0`)** in the volume: included only if
  it carries images; normally it does not.

## Out of scope

- Editing / reordering images from within the gallery.
- A status check for the gallery page (no `/status` equivalent).
- Publishing illustrations for every volume of a series in one action.

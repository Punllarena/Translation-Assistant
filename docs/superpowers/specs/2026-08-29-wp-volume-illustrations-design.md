# WordPress Volume Illustrations Gallery — Design Spec

**Date:** 2026-08-29
**Status:** approved, ready for implementation plan
**Revised:** 2026-08-29 — reconciled with in-flight "photo upload" work
(see *Conflicts with in-flight work* at the end).

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

## Payload size (the hard constraint)

EasyWP's proxy resets any request body over ~1 MB. `imageopt.shrink_image`
(in-flight work) knocks each image down to ~350 KB, but a whole volume's
art is still several MB. **The gallery is therefore sent in chunks:**

- The client shrinks every image, then splits the ordered list
  (cover first) into batches whose encoded size stays under **~800 KB**.
- The **first** batch is sent with `mode: "replace"` — the plugin
  creates or finds the gallery page and **wipes its existing
  attachments**, then writes a page whose body is exactly this batch's
  image blocks.
- Each **subsequent** batch is sent with `mode: "append"` — the plugin
  sideloads those images and appends their blocks to the existing page
  body.
- The TOC link is (idempotently) ensured on the `replace` call only.
- A volume small enough to fit in one request still works: one
  `replace` batch, no `append`.

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
  `series_title_short`, `images`. `series_link`, `volume_title`, `cover`
  all optional (`series_link` optional to match `tap_handle_publish`
  after plugin commit `a94aded` — EPUB-imported series send `""`).
  - `images` must be an array; it may be `[]` **when a `cover` object is
    present** (cover-only volume → a page with just the cover). 400
    `"Missing field: images"` only when `images` is not an array, or is
    empty with no `cover`.
  - `mode` optional; `"replace"` (default) or `"append"`. Anything else
    → 400.
- `TAP_Auth::validate_key()` → 401 on failure.
- `new TAP_Publisher()->publish_illustrations( $data, $user_id )`.
- `is_wp_error` → 500 with `[ 'error' => $result->get_error_message() ]`
  (the client reads `error` first, then `message`).
- This route (with the cover-only `images: []` acceptance above) ships in
  plugin version **1.5.5**.

### A2. `TAP_Publisher::publish_illustrations( array $data, int $user_id ): array|WP_Error`

```
$series_slug  = sanitize_title( $data['series_slug'] );
$series_link  = isset( $data['series_link'] ) && is_string( $data['series_link'] )
              ? $data['series_link'] : '';
$volume_title = isset( $data['volume_title'] ) && is_string( $data['volume_title'] )
              ? $data['volume_title'] : '';
$mode         = ( $data['mode'] ?? 'replace' ) === 'append' ? 'append' : 'replace';

$index_id = $this->find_or_create_index_page(
    $series_slug, $data['series_title'], $series_link, $user_id
);
if ( is_wp_error( $index_id ) ) return $index_id;
```

**Gallery slug** — child of the index page:

```
$slug = $volume_title !== ''
      ? "{$series_slug}-illustrations-" . sanitize_title( $volume_title )
      : "{$series_slug}-illustrations";
$existing = get_page_by_path( "{$series_slug}/{$slug}", OBJECT, 'page' );
```

**`mode === 'replace'`** (first batch of a run):

- If `$existing`: delete its child attachments (same loop as
  `update_chapter_page()`), then `wp_update_post` with a freshly built
  body (this batch's blocks only). `created => false`.
- Else: `wp_insert_post` a `page` — `post_parent => $index_id`,
  `post_name => $slug`, `post_status => 'publish'`, `post_title` per A3,
  `menu_order => 0`, empty content; then `wp_update_post` the built body
  (so `attach_image` has the real `$post_id`). On content-update
  `WP_Error`, `wp_delete_post( $id, true )` and return it (mirrors
  `create_chapter_page`). `created => true`.
- Then, **only when `$created` is true** (the gallery page was just
  inserted), `append_toc_entry( $index_id, 'Illustrations',
  get_permalink( $gallery_id ), $volume_title )`. The substring check inside
  `append_toc_entry` guards only the volume `<h3>` heading — the
  `<p><a>…Illustrations…</a></p>` entry line itself is NOT de-duped, so
  calling it on every `replace` would stack a second identical link on each
  re-publish. Gating on `if ($created)` means a re-publish of an existing
  gallery does not touch the ToC at all. The `<h3>` emit stays
  order-independent.

**`mode === 'append'`** (later batches):

- If `! $existing` → `WP_Error( 'no_gallery', 'append before replace' )`
  (client always sends `replace` first; this only fires on a client bug).
- Build this batch's blocks and append them:
  `wp_update_post([ 'ID' => $existing->ID,
  'post_content' => rtrim( $existing->post_content ) . "\n\n" . $blocks ])`.
- No TOC call (already done on the `replace` batch).
- `created => false`.

**Return:**

```
[ 'status' => 'ok', 'page_url' => get_permalink( $gallery_id ),
  'created' => $created, 'updated' => ! $created ]
```

### A3. Gallery page content

New private helper
`build_illustrations_blocks( array $images, ?array $cover, int $post_id ): string`:

- Returns the `"\n\n"`-joined image blocks only — **no** page-title
  logic, **no** `NAV_BLOCK`, **no** `SEPARATOR`. The caller concatenates
  (replace) or appends (append) this string.
- If `$cover`, `attach_image()` it and put its `image_block()` first.
  Then each entry in `$images`: `attach_image()` + `image_block()`.
  On any `attach_image` `WP_Error`, `error_log` and skip that image
  (same tolerance as `convert_to_blocks`).
- `$cover` is only ever present on the first (`replace`) batch — the
  client puts it at the head of batch 1.
- Each image dict is `{ filename, mime, data_base64 }` — same shape
  `convert_to_blocks` consumes, minus `position`.

`post_title` (computed in `publish_illustrations`, `replace` branch only):
`"{$volume_title} — Illustrations"` when `$volume_title`, else
`"{$data['series_title_short']} Illustrations"`.

`image_block()` and `attach_image()` are reused unchanged.

### A4. Version bump

`translation-assistant-publisher.php` header `Version: 1.5.3` → `1.5.4`.
(Plugin is already at 1.5.3 as of commit `a94aded`; the spec's original
`1.5.2` is stale.) The final review wave then took it to **1.5.5** — a
deployed 1.5.4 still 400s a cover-only request, so accepting `images: []`
with a `cover` present needs its own version.

### A5. Plugin files touched

- Modify: `plugins/translation-assistant-publisher/translation-assistant-publisher.php`
  (route + `tap_handle_illustrations` + version)
- Modify: `plugins/translation-assistant-publisher/includes/class-publisher.php`
  (`publish_illustrations` + `build_illustrations_blocks`)
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

Note: the shared error-body parse must keep the in-flight form
`msg = body.get("error") or body.get("message") or str(exc)` (already in
the working tree at `publish()` / `check_status()`).

**New:** `_ILLUSTRATIONS_PATH = "/wp-json/ta-publisher/v1/illustrations"`
and

```python
def publish_illustrations(endpoint_url: str, payload: dict, timeout: int = 20) -> dict:
    base = endpoint_url.rstrip("/")
    if base.endswith(_ENDPOINT_PATH):
        base = base[: -len(_ENDPOINT_PATH)]
    url = base + _ILLUSTRATIONS_PATH
    ...POST JSON, same error handling as publish()'s non-409 path...
```

**New:** `build_illustrations_payloads` — **plural**: returns a *list* of
per-batch payload dicts (one request each). Images arrive already
shrunk (the UI handler runs `imageopt.shrink_image` first — `imageopt`
is Qt-only and must not be imported here).

```python
_ILLUS_BATCH_BYTES = 800_000   # encoded-size budget per request body

def build_illustrations_payloads(
    doc_meta: dict,
    series_meta: dict,
    images: list[dict],          # ordered; already shrunk
    api_key: str,
    cover: dict | None = None,   # already shrunk
) -> list[dict]:
    if not series_meta.get("series_slug"):
        raise ValueError("series_slug is required — set it in Series Manager")
    if not series_meta.get("series_title_short"):
        raise ValueError("series_title_short is required — set it in Series Manager")

    base = {
        "api_key":            api_key,
        "series_title":       doc_meta["series_title"],
        "series_slug":        series_meta["series_slug"],
        "series_title_short": series_meta["series_title_short"],
        "series_link":        series_meta.get("syosetu_url") or "",
    }
    if doc_meta.get("volume_title"):
        base["volume_title"] = doc_meta["volume_title"]

    # cover is the first item of the first batch; count its bytes there.
    encoded = [_encode_image(im) for im in images]
    enc_cover = _encode_image(cover) if cover is not None else None

    batches: list[list[dict]] = [[]]
    size = len(enc_cover["data_base64"]) if enc_cover else 0
    for e in encoded:
        b = len(e["data_base64"])
        if batches[-1] and size + b > _ILLUS_BATCH_BYTES:
            batches.append([])
            size = 0
        batches[-1].append(e)
        size += b

    payloads = []
    for i, batch in enumerate(batches):
        p = {**base, "images": batch, "mode": "replace" if i == 0 else "append"}
        if i == 0 and enc_cover is not None:
            p["cover"] = enc_cover
        payloads.append(p)
    return payloads
```

- Single-batch volumes → a one-element list, `mode="replace"`.
- `images == [] and cover is None` never reaches here (UI guards it), but
  if it did the result is one empty `replace` batch — harmless, plugin
  400s on empty `images`. The UI guard is the real contract.
- `_encode_image` already returns `{filename, mime, data_base64}`; no
  `position` key here.

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

    # Shrink every image before it enters a payload — same guard the
    # per-chapter path uses (imageopt is Qt-only, so it lives here, not
    # in wp_publisher). Mutating copies, not the DB rows.
    from translation_assistant.imageopt import shrink_image
    def _shrunk(im: dict) -> dict:
        out = dict(im)
        s = shrink_image(im["data"])
        if s is not im["data"]:
            out["data"] = s
            out["src_path"] = im["src_path"].rsplit(".", 1)[0] + ".jpg"
        return out
    inline_images = [_shrunk(im) for im in inline_images]
    cover_image = _shrunk(cover_image) if cover_image else None

    from translation_assistant.wp_publisher import (
        build_illustrations_payloads, publish_illustrations,
    )
    try:
        payloads = build_illustrations_payloads(
            doc_meta, series_meta, inline_images, api_key=api_key, cover=cover_image,
        )
    except ValueError as exc:
        QMessageBox.warning(self, "Payload Error", str(exc))
        return

    self.action_publish_volume_illus.setEnabled(False)
    self._illus_worker = _IllustrationsPublishWorker(
        endpoint_url, payloads, parent=self,
    )
    self._illus_worker.succeeded.connect(self._on_publish_illus_done)
    self._illus_worker.error.connect(self._on_publish_illus_error)
    self._illus_worker.start()
```

`_on_publish_illus_done(result)` — re-enable the action, show a
`QMessageBox` with `result.get("page_url")` (and a "created / updated"
word from `result`). `_on_publish_illus_error(msg)` — re-enable, warn.

**`_IllustrationsPublishWorker`** — a new `QThread` next to
`_PublishWorker` (`main_widget.py:28`). Takes `endpoint_url` and the
`payloads` list. `run()` loops the batches **in order**, calling
`wp_publisher.publish_illustrations(endpoint_url, p)` for each; the
first (`replace`) result is what it emits on `succeeded` once every
batch has landed. Any `WPPublishError` → stop, emit `error` with the
message and which batch failed (`f"batch {i+1}/{len(payloads)}: {exc}"`).
Sequential, not parallel — `append` must never overtake `replace`.
`_PublishWorker` is left untouched (no `publish_fn` kwarg needed after
all).

### B3. `combined_window.py`

`_setup_menubar` — add after line 117:

```python
file_menu.addAction(ta.action_publish_volume_illus)
```

### B4. Tests — `tests/test_wp_publisher.py`

`build_illustrations_payloads` (all assert against the returned list):

- `volume_title` set → `"volume_title"` in every batch; `doc_meta["volume_title"] == ""`
  → key absent, no error.
- One batch when total encoded size < `_ILLUS_BATCH_BYTES`: `len(result) == 1`,
  `result[0]["mode"] == "replace"`.
- Many small images whose combined base64 exceeds the budget → `len(result) > 1`,
  `result[0]["mode"] == "replace"`, all others `"append"`; concatenating the
  batches' `images` reproduces the input order.
- `cover` only on `result[0]` (`"cover"` not in any `append` batch); its bytes
  count toward batch 0's budget.
- Each image entry has `filename`/`mime`/`data_base64`, **no** `position`.
- Missing `series_slug` / `series_title_short` → `ValueError`.
- `series_meta` with no `syosetu_url` key → `series_link` == `""`, no `KeyError`.
- `publish_illustrations` builds the `/wp-json/ta-publisher/v1/illustrations`
  URL from a bare site URL and from one already ending in
  `/wp-json/ta-publisher/v1/publish` (monkeypatch `urllib.request.urlopen`,
  assert `Request.full_url`); a `{"error": "..."}` body surfaces as
  `WPPublishError.message`.

(The file already carries in-flight additions — keep them; append the new
tests.)

### B5. TA files touched

- Modify: `translation_assistant/wp_publisher.py`
- Modify: `translation_assistant/ui/main_widget.py`
- Modify: `translation_assistant/ui/combined_window.py`
- Modify: `tests/test_wp_publisher.py`
- **Depends on (do not modify):** `translation_assistant/imageopt.py`
  `shrink_image` — currently untracked in the working tree; this feature
  assumes it is committed by the time the plan runs. If it is still
  untracked, the plan's first task is to land the in-flight image-upload
  work (or at least `imageopt.py` + `tests/test_imageopt.py`).
- No new files.

---

## Data flow

```
user → File ▸ Publish Volume Illustrations…
  main_widget._on_publish_volume_illustrations
    _save_current_translation
    _ensure_wp_ready(series_title) → endpoint, api_key, series_meta
    db.get_document_ids_by_series → filter by volume_title (series_order order)
    db.get_document_images per doc → cover (first) + inline (not is_cover, not exclude_export)
    confirm dialog
    imageopt.shrink_image on every image + cover  (Qt-only, UI side)
    wp_publisher.build_illustrations_payloads(...) → [batch0(replace,+cover), batch1(append), …]
    _IllustrationsPublishWorker(endpoint, payloads):
      for p in payloads (in order):
        wp_publisher.publish_illustrations(endpoint, p) → POST /ta-publisher/v1/illustrations
          plugin tap_handle_illustrations → TAP_Publisher::publish_illustrations
            find_or_create_index_page
            get_page_by_path(series/slug-illustrations[-volume])
            mode=replace → insert | (wipe attachments + overwrite body); append_toc_entry
            mode=append  → append this batch's image blocks to existing body
            build_illustrations_blocks(cover first on batch0, then images) via attach_image + image_block
          → { status, page_url, created, updated }
      emit succeeded(batch0 result)
    _on_publish_illus_done → QMessageBox with page_url
```

## Edge cases

- **Volume with only a cover, no inline images:** still publishes (page
  with one image). Guard only blocks when both are empty.
- **`volume_title == ""`** (syosetu-imported series with no EPUB volume
  grouping): slug falls back to `{series_slug}-illustrations`, title to
  `"{short} Illustrations"`, `append_toc_entry` adds a bare link with no
  `<h3>` — matches existing behaviour for volume-less chapters.
- **Re-run after adding/removing an image:** the `replace` batch deletes
  the page's attachments and overwrites the body; `append` batches rebuild
  the rest. The ToC is untouched — `append_toc_entry` runs only on the
  first-ever create (`if ($created)`), so a re-run adds no second link.
- **Illustrations published *after* a later volume's chapters exist:**
  `append_toc_entry` always inserts immediately before `<!-- ta-toc-end -->`
  (the ToC tail), so the "Illustrations" link lands at the bottom of the
  ToC — visually under the wrong volume heading. Publish volumes in order,
  or move the link by editing the index page. (Pre-existing plugin
  behaviour, not specific to this feature.)
- **A later `append` batch fails mid-run:** the page is left with batch 0
  (+ any batches that landed). Re-running the whole action from `replace`
  is the recovery — it wipes and rebuilds. No partial-resume logic.
- **Gallery published before any chapter of the volume:** `append_toc_entry`
  emits the `<h3>` now; later chapter publishes see it and skip — order
  independent, by existing design.
- **Synopsis doc (`series_order == 0`)** in the volume: included only if
  it carries images; normally it does not.
- **`shrink_image` returns the original bytes** (already small / undecodable):
  handler keeps the original `src_path` extension — the `is s` identity
  check in `_shrunk` handles this.

## Out of scope

- Editing / reordering images from within the gallery.
- A status check for the gallery page (no `/status` equivalent).
- Publishing illustrations for every volume of a series in one action.

---

## Conflicts with in-flight work (reconciled 2026-08-29)

The working tree of both repos carries an unfinished "photo upload with
chapters" effort. This spec was revised to sit on top of it.

| # | In-flight change | Where | Effect on this spec |
|---|------------------|-------|---------------------|
| 1 | Plugin bumped to **1.5.3**, `series_link` dropped from `$required`, normalized to `''`, index heading rendered without `<a>` when empty | plugin commit `a94aded` (committed) | A1/A2/A4: `series_link` optional in `tap_handle_illustrations`; version bump target is now **1.5.4**, not 1.5.3. |
| 2 | `imageopt.shrink_image()` — downscale + JPEG re-encode to ~350 KB before a WP payload; `_on_publish_wp` shrinks every inline image + cover and rewrites `src_path`→`.jpg` | `translation_assistant/imageopt.py`, `tests/test_imageopt.py` (**untracked**), `main_widget.py` (uncommitted) | B2: `_on_publish_volume_illustrations` runs the same shrink loop before building payloads. B5: hard dependency on `imageopt.py` being committed — plan's first task ensures it. |
| 3 | `build_payload` now sends `cover` **only when `series_order == 1`** — a single ~1 MB base64 cover was already tripping EasyWP's proxy reset | `wp_publisher.py` (uncommitted), `tests/test_wp_publisher.py` (uncommitted) | Confirms the ~1 MB cap is real and tight → the gallery **must** batch (Payload-size section, `build_illustrations_payloads`, `_IllustrationsPublishWorker`). A single-payload gallery is not viable. |
| 4 | Error-body parse changed to `body.get("error") or body.get("message") or str(exc)` | `wp_publisher.py` `publish()` / `check_status()` (uncommitted) | B1: the shared/`_post_json` path and `publish_illustrations` must use this exact form. Plugin returns `{'error': ...}`, so A1's error responses use the `error` key. |
| 5 | `build_chapter_body` now runs `_bold_to_html` (`**x**`→`<strong>`) | `wp_publisher.py` (uncommitted) | None — the gallery carries no text. Noted so a merge doesn't look surprising. |
| 6 | `db.list_documents()` rewritten: adds `line_count` / `image_count`, image-only chapters report 100 % progress | `db.py` (uncommitted) | None directly — this feature uses `get_document_ids_by_series` / `get_document` / `get_document_images`, none touched. Confirms "image-only chapters" is an active theme. |
| 7 | `tests/test_wp_publisher.py`, `tests/test_epub.py`, `tests/test_main_window.py` already dirty | uncommitted | B4: **append** the new tests; when staging, `git add tests/test_wp_publisher.py` also stages the in-flight additions — that is fine, both are wanted. Never `git add -A`. |

**Ordering guidance for the plan:** land (or rebase onto) the in-flight
image-upload work first — at minimum `imageopt.py` + its test and the
`wp_publisher.py` error-key change — then build this feature. Do not
re-implement `shrink_image` or the error-key parse; consume them.

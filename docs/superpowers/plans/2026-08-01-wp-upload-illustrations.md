# WP Upload Illustration Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the WP publish payload and the `translation-assistant-publisher` plugin so inline chapter illustrations and volume covers (already stored in `document_images`) travel to WordPress and render on the published page.

**Architecture:** Client (`wp_publisher.py`) base64-encodes `document_images` rows into `images`/`cover` keys on the existing `/publish` JSON payload, converting each image's line-indexed `anchor_position` into a paragraph-indexed `position`. The plugin (`class-publisher.php`) decodes, creates WP attachments via `media_handle_sideload()`, and splices `wp:image` blocks into the chapter page content at the given position (cover always at the top of its own chapter page, never the shared series index page).

**Tech Stack:** Python 3 (client, stdlib `base64`/`mimetypes` only), PHP 8 (plugin, WordPress attachment APIs).

## Global Constraints

- Plugin: `Requires at least: 6.0` (WP core), `Requires PHP: 8.0` — from `translation-assistant-publisher.php` header. No new dependency may raise these floors.
- No new third-party dependency on either side — stdlib (`base64`, `mimetypes`) on the Python side, core WP APIs (`media_handle_sideload`, `wp_insert_post`) on the PHP side.
- `document_images.anchor_position` values are always at paragraph-group boundaries (never mid-`$`-continuation-run) — guaranteed by the EPUB import's counting-pass design (`2026-07-30-epub-illustrations-design.md`). Code may rely on this; no need to handle a mid-group anchor.
- Plugin has no PHPUnit/test harness in this repo (`wp-dev`) — verify PHP changes manually against the local Docker WP instance (`docker compose` in `/home/pun/workspace/wp-dev`, WP reachable at `http://localhost:8080`, plugin dir bind-mounted live). Do not introduce a new PHP test framework — out of scope.
- Cover only ever accompanies a real chapter publish (`chapter_index >= 1`); the synopsis/index-page path (`chapter_index == 0`, `handle_synopsis()`) is unaffected by this plan — confirmed against `dlg_import_epub.py`'s `first_new_doc_id` assignment (only set inside the per-chapter loop, never for the synopsis).

---

## File Structure

- `translation_assistant/wp_publisher.py` — add `_encode_image()`, `build_image_payload()`; extend `build_payload()` with `images`/`cover` params.
- `tests/test_wp_publisher.py` — tests for the two new/changed functions.
- `translation_assistant/ui/main_widget.py` — `_on_publish_wp()` fetches `document_images`, splits cover/inline, passes both into `build_payload()`.
- `/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher/includes/class-publisher.php` — add `attach_image()`, `image_block()`; extend `convert_to_blocks()`; restructure `create_chapter_page()` (two-step insert-then-update-content, since attachments need a real post ID that doesn't exist until after `wp_insert_post()`).
- `/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher/translation-assistant-publisher.php` — version bump (`1.3.3` → `1.4.0`).

---

### Task 1: `build_image_payload()` — anchor-to-paragraph mapping

**Files:**
- Modify: `translation_assistant/wp_publisher.py`
- Test: `tests/test_wp_publisher.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure function, first task).
- Produces: `_encode_image(row: dict) -> dict` (`row` has `src_path: str`, `data: bytes` keys — same shape as `db.get_document_images()` rows). `build_image_payload(lines: list[dict], images: list[dict]) -> list[dict]` (`images` is a list of `db.get_document_images()` rows, each with `id: int`, `anchor_position: int`, `src_path: str`, `data: bytes`). Returns a list of `{"position": int, "filename": str, "mime": str, "data_base64": str}` dicts, sorted by `(anchor_position, id)`. Both are used by Task 2.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_wp_publisher.py` (near the existing `build_chapter_body` tests):

```python
from translation_assistant.wp_publisher import build_image_payload

def test_build_image_payload_simple_paragraph_boundary():
    lines = [
        {"prefix": "%", "translated_text": "First paragraph."},
        {"prefix": "%", "translated_text": "Second paragraph."},
    ]
    images = [
        {"id": 1, "anchor_position": 1, "src_path": "img1.jpg", "data": b"JPEGDATA"},
    ]
    result = build_image_payload(lines, images)
    assert result == [
        {
            "position": 1,
            "filename": "img1.jpg",
            "mime": "image/jpeg",
            "data_base64": "SlBFR0RBVEE=",
        }
    ]

def test_build_image_payload_accounts_for_sentence_split():
    # One source paragraph split into two sentence lines (% + $) — an
    # image anchored after raw_lines[2] must land at paragraph position 1
    # (after the merged first <p>), not 2.
    lines = [
        {"prefix": "%", "translated_text": "Sentence one."},
        {"prefix": "$", "translated_text": "Sentence two, same paragraph."},
        {"prefix": "%", "translated_text": "Next paragraph."},
    ]
    images = [
        {"id": 5, "anchor_position": 2, "src_path": "img2.png", "data": b"PNGDATA"},
    ]
    result = build_image_payload(lines, images)
    assert result[0]["position"] == 1

def test_build_image_payload_before_first_and_after_last():
    lines = [
        {"prefix": "%", "translated_text": "Only paragraph."},
    ]
    images = [
        {"id": 2, "anchor_position": 1, "src_path": "after.jpg", "data": b"A"},
        {"id": 1, "anchor_position": 0, "src_path": "before.jpg", "data": b"B"},
    ]
    result = build_image_payload(lines, images)
    assert [im["filename"] for im in result] == ["before.jpg", "after.jpg"]
    assert result[0]["position"] == 0
    assert result[1]["position"] == 1

def test_build_image_payload_ties_break_on_id():
    lines = [{"prefix": "%", "translated_text": "Paragraph."}]
    images = [
        {"id": 9, "anchor_position": 1, "src_path": "second.jpg", "data": b"X"},
        {"id": 3, "anchor_position": 1, "src_path": "first.jpg", "data": b"Y"},
    ]
    result = build_image_payload(lines, images)
    assert [im["filename"] for im in result] == ["first.jpg", "second.jpg"]

def test_build_image_payload_empty_images():
    assert build_image_payload([{"translated_text": "x"}], []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_wp_publisher.py -k build_image_payload -v`
Expected: FAIL with `ImportError: cannot import name 'build_image_payload'`

- [ ] **Step 3: Implement `_encode_image()` and `build_image_payload()`**

Add near the top of `translation_assistant/wp_publisher.py` (after existing imports — add `import base64` and `import mimetypes` to the import block):

```python
import base64
import mimetypes
```

Add after `get_first_line()`:

```python
def _encode_image(row: dict) -> dict:
    mime = mimetypes.guess_type(row["src_path"])[0] or "application/octet-stream"
    return {
        "filename": row["src_path"],
        "mime": mime,
        "data_base64": base64.b64encode(row["data"]).decode("ascii"),
    }


def build_image_payload(lines: list[dict], images: list[dict]) -> list[dict]:
    """Map document_images rows (line-indexed anchor_position) onto the
    paragraph-indexed `position` the WP payload's `images` list uses.

    Mirrors build_chapter_body's grouping loop so `position` always lands
    on a paragraph boundary matching the <p> blocks that function emits.
    Relies on anchor_position always sitting at a paragraph-group boundary
    (never mid-$-continuation-run) — guaranteed by the EPUB importer.
    """
    if not images:
        return []

    sorted_images = sorted(images, key=lambda im: (im["anchor_position"], im["id"]))

    boundaries: dict[int, int] = {}
    emitted = 0
    i = 0
    n = len(lines)
    while i < n:
        boundaries[i] = emitted
        if lines[i].get("prefix") == "$":
            i += 1
            continue
        group = [lines[i]["translated_text"]]
        i += 1
        while i < n and lines[i].get("prefix") == "$":
            group.append(lines[i]["translated_text"])
            i += 1
        text = " ".join(t for t in group if t.strip())
        if text:
            emitted += 1
    boundaries[n] = emitted

    result = []
    for im in sorted_images:
        position = boundaries.get(im["anchor_position"], emitted)
        result.append({"position": position, **_encode_image(im)})
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_wp_publisher.py -k build_image_payload -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/wp_publisher.py tests/test_wp_publisher.py
git commit -m "feat(wp): add build_image_payload for anchor-to-paragraph mapping"
```

---

### Task 2: `build_payload()` gains `images`/`cover` params

**Files:**
- Modify: `translation_assistant/wp_publisher.py`
- Test: `tests/test_wp_publisher.py`

**Interfaces:**
- Consumes: `build_image_payload(lines, images) -> list[dict]` and `_encode_image(row) -> dict` from Task 1.
- Produces: `build_payload(doc_meta, series_meta, lines, api_key, password=None, unlock_chapter_index=None, scheduled_date=None, attribution=True, images=None, cover=None) -> dict`. `images` is a list of `document_images` rows (or `None`/`[]`); `cover` is a single `document_images` row or `None`. Used by Task 3.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_wp_publisher.py`:

```python
def test_build_payload_includes_images_when_present():
    doc_meta, series_meta, lines = _sample_meta()
    images = [{"id": 1, "anchor_position": 1, "src_path": "a.jpg", "data": b"X"}]
    payload = build_payload(doc_meta, series_meta, lines, api_key="key123", images=images)
    assert payload["images"] == [
        {"position": 1, "filename": "a.jpg", "mime": "image/jpeg", "data_base64": "WA=="}
    ]

def test_build_payload_omits_images_when_absent():
    doc_meta, series_meta, lines = _sample_meta()
    payload = build_payload(doc_meta, series_meta, lines, api_key="key123")
    assert "images" not in payload

def test_build_payload_includes_cover_when_present():
    doc_meta, series_meta, lines = _sample_meta()
    cover = {"src_path": "cover.png", "data": b"COVERBYTES"}
    payload = build_payload(doc_meta, series_meta, lines, api_key="key123", cover=cover)
    assert payload["cover"]["filename"] == "cover.png"
    assert payload["cover"]["mime"] == "image/png"

def test_build_payload_omits_cover_when_absent():
    doc_meta, series_meta, lines = _sample_meta()
    payload = build_payload(doc_meta, series_meta, lines, api_key="key123")
    assert "cover" not in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_wp_publisher.py -k "build_payload_includes_images or build_payload_omits_images or build_payload_includes_cover or build_payload_omits_cover" -v`
Expected: FAIL — `images`/`cover` keys never appear (current `build_payload` doesn't accept those params yet, so passing them raises `TypeError: unexpected keyword argument`).

- [ ] **Step 3: Implement**

In `translation_assistant/wp_publisher.py`, change `build_payload`'s signature and body:

```python
def build_payload(
    doc_meta: dict,
    series_meta: dict,
    lines: list[dict],
    api_key: str,
    password: str | None = None,
    unlock_chapter_index: int | None = None,
    scheduled_date: str | None = None,
    attribution: bool = True,
    images: list[dict] | None = None,
    cover: dict | None = None,
) -> dict:
    if not series_meta.get("series_slug"):
        raise ValueError("series_slug is required — set it in Series Manager")
    if not series_meta.get("series_title_short"):
        raise ValueError("series_title_short is required — set it in Series Manager")

    payload: dict = {
        "api_key":            api_key,
        "series_title":       doc_meta["series_title"],
        "series_slug":        series_meta["series_slug"],
        "series_title_short": series_meta["series_title_short"],
        "series_link":        series_meta["syosetu_url"],
        "chapter_index":      doc_meta["series_order"],
        "chapter_title":      f"{series_meta['series_title_short']} {doc_meta['chapter_title']}",
        "chapter_body":       build_chapter_body(lines),
    }
    if attribution and doc_meta["series_order"] != 0:
        payload["chapter_body"] += (
            '\n<hr />'
            '<p><em>This post is automatically published by '
            '<a href="https://github.com/Punllarena/Translation-Assistant">Translation Assistant</a>'
            ' and <a href="https://github.com/Punllarena/translation-assistant-publisher">Translation Assistant Publisher</a>.</em></p>'
        )
    if doc_meta["series_order"] != 0:
        payload["first_line"] = get_first_line(lines)
    if password is not None:
        payload["password"] = password
    if unlock_chapter_index is not None:
        payload["unlock_chapter_index"] = unlock_chapter_index
    if scheduled_date is not None:
        payload["publish_date"] = scheduled_date
    if images:
        payload["images"] = build_image_payload(lines, images)
    if cover is not None:
        payload["cover"] = _encode_image(cover)
    return payload
```

(Only the signature line and the final two `if` blocks before `return payload` are new — everything else is unchanged from the current implementation.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_wp_publisher.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones — confirms no regression)

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/wp_publisher.py tests/test_wp_publisher.py
git commit -m "feat(wp): build_payload accepts images/cover params"
```

---

### Task 3: Wire `_on_publish_wp()` to fetch and forward `document_images`

**Files:**
- Modify: `translation_assistant/ui/main_widget.py` (around line 1449 and line 1576)

**Interfaces:**
- Consumes: `db.get_document_images(document_id: int) -> list[dict]` (existing, rows have `id`, `anchor_position`, `is_cover`, `src_path`, `data` keys — `is_cover` is `0`/`1`). `build_payload(..., images=..., cover=...)` from Task 2.
- Produces: nothing new consumed elsewhere — this is the final UI wiring point.

**Context:** `_on_publish_wp()` fetches `lines = self._db.get_lines(self._doc_id)` at what is currently line 1449, then calls `build_payload(...)` at what is currently line 1576. No existing automated test exercises `_on_publish_wp()` (it's UI glue, like the rest of that method) — verify manually by running the app (see Step 3).

- [ ] **Step 1: Add the fetch-and-split logic**

In `translation_assistant/ui/main_widget.py`, immediately after the existing line:

```python
        lines = self._db.get_lines(self._doc_id)
```

add:

```python
        doc_images = self._db.get_document_images(self._doc_id)
        inline_images = [im for im in doc_images if not im["is_cover"]]
        cover_image = next((im for im in doc_images if im["is_cover"]), None)
```

- [ ] **Step 2: Pass them into `build_payload()`**

Change the existing `build_payload(...)` call (currently around line 1576):

```python
            payload = build_payload(
                doc_meta, series_meta, lines, api_key=api_key,
                password=self._last_pw,
                unlock_chapter_index=self._last_unlock_idx,
                scheduled_date=self._last_scheduled_date,
                attribution=self._settings.wp_attribution_enabled,
            )
```

to:

```python
            payload = build_payload(
                doc_meta, series_meta, lines, api_key=api_key,
                password=self._last_pw,
                unlock_chapter_index=self._last_unlock_idx,
                scheduled_date=self._last_scheduled_date,
                attribution=self._settings.wp_attribution_enabled,
                images=inline_images,
                cover=cover_image,
            )
```

- [ ] **Step 3: Run the full test suite, then manually verify no regression**

Run: `source .venv/bin/activate && pytest -q`
Expected: PASS, same count as before this task (no test exercises this wiring directly, so this step only confirms nothing else broke).

Manually: `python -m translation_assistant.main`, open a chapter document imported from an EPUB with illustrations (or any document — `document_images` will just be empty), trigger Publish to WordPress, confirm the confirm-dialog and publish flow behave exactly as before (this task doesn't change UI, only the payload contents, so there's nothing new to see yet — full verification happens after Task 6 against the local Docker WP).

- [ ] **Step 4: Commit**

```bash
git add translation_assistant/ui/main_widget.py
git commit -m "feat(wp): forward document_images into WP publish payload"
```

---

### Task 4: `attach_image()` — decode base64 and create a WP attachment

**Files:**
- Modify: `/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher/includes/class-publisher.php`

**Interfaces:**
- Consumes: nothing from other tasks (new method on `TAP_Publisher`).
- Produces: `attach_image(string $filename, string $mime, string $base64, int $post_id): int|WP_Error` — used by Task 5.

**Context:** No PHPUnit harness exists in this repo. Verify by calling the method through a temporary debug route (removed before the final commit) against the local Docker WP — see Step 2.

- [ ] **Step 1: Implement `attach_image()`**

Add to `TAP_Publisher` in `class-publisher.php` (after `unlock_chapter()`):

```php
    public function attach_image( string $filename, string $mime, string $base64, int $post_id ): int|WP_Error {
        $decoded = base64_decode( $base64, true );
        if ( $decoded === false ) {
            return new WP_Error( 'bad_image_data', "Could not decode image data for {$filename}" );
        }

        $tmp_file = wp_tempnam( $filename );
        if ( ! $tmp_file || file_put_contents( $tmp_file, $decoded ) === false ) {
            return new WP_Error( 'temp_write_failed', "Could not write temp file for {$filename}" );
        }

        require_once ABSPATH . 'wp-admin/includes/image.php';
        require_once ABSPATH . 'wp-admin/includes/file.php';
        require_once ABSPATH . 'wp-admin/includes/media.php';

        $file_array = [
            'name'     => sanitize_file_name( $filename ),
            'tmp_name' => $tmp_file,
        ];

        $attachment_id = media_handle_sideload( $file_array, $post_id );
        if ( is_wp_error( $attachment_id ) ) {
            if ( file_exists( $tmp_file ) ) {
                @unlink( $tmp_file );
            }
            return $attachment_id;
        }

        return $attachment_id;
    }
```

- [ ] **Step 2: Verify manually against the local Docker WP**

Bring up the stack if not already running:

```bash
cd /home/pun/workspace/wp-dev && docker compose up -d
```

Temporarily add a throwaway debug route to `translation-assistant-publisher.php` (inside the existing `rest_api_init` action, right after the `/status` route registration):

```php
    register_rest_route( 'ta-publisher/v1', '/debug-attach', [
        'methods'             => 'POST',
        'callback'            => function ( WP_REST_Request $r ) {
            $d = $r->get_json_params();
            $p = new TAP_Publisher();
            $id = $p->attach_image( $d['filename'], $d['mime'], $d['data_base64'], 0 );
            return new WP_REST_Response( is_wp_error( $id ) ? [ 'error' => $id->get_error_message() ] : [ 'attachment_id' => $id ], 200 );
        },
        'permission_callback' => '__return_true',
    ] );
```

Call it with a tiny real JPEG (any small local image, base64-encoded):

```bash
python3 -c "import base64; print(base64.b64encode(open('/path/to/small.jpg','rb').read()).decode())" > /tmp/img_b64.txt
curl -s -X POST http://localhost:8080/wp-json/ta-publisher/v1/debug-attach \
  -H 'Content-Type: application/json' \
  -d "{\"filename\":\"small.jpg\",\"mime\":\"image/jpeg\",\"data_base64\":\"$(cat /tmp/img_b64.txt)\"}"
```

Expected: `{"attachment_id": <int>}`. Confirm the attachment exists: WP admin → Media Library at `http://localhost:8080/wp-admin/upload.php`, or `curl http://localhost:8080/wp-json/wp/v2/media/<id>`.

Remove the throwaway `/debug-attach` route before committing.

- [ ] **Step 3: Commit**

```bash
git -C /home/pun/workspace/wp-dev add plugins/translation-assistant-publisher/includes/class-publisher.php
git -C /home/pun/workspace/wp-dev commit -m "feat(publisher): add attach_image() for base64 image uploads"
```

---

### Task 5: `convert_to_blocks()` splices `wp:image` blocks; `image_block()` helper

**Files:**
- Modify: `/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher/includes/class-publisher.php`

**Interfaces:**
- Consumes: `attach_image()` from Task 4.
- Produces: `convert_to_blocks(string $html, array $images = [], ?array $cover = null, int $post_id = 0): string` (replaces the current 1-arg signature), `image_block(int $attachment_id): string`. Used by Task 6.
- `$images` items: `['position' => int, 'filename' => string, 'mime' => string, 'data_base64' => string]` (matches the client's `images` payload key exactly). `$cover`: same shape as one `$images` item, or `null`.

- [ ] **Step 1: Implement**

Replace `convert_to_blocks()` in `class-publisher.php` with:

```php
    public function convert_to_blocks( string $html, array $images = [], ?array $cover = null, int $post_id = 0 ): string {
        $parts  = preg_split( '/(<p[^>]*>.*?<\/p>)/s', trim( $html ), -1, PREG_SPLIT_DELIM_CAPTURE );
        $blocks = [];

        foreach ( $parts as $part ) {
            $part = trim( $part );
            if ( $part === '' ) continue;

            if ( preg_match( '/^<p[^>]*>.*<\/p>$/s', $part ) ) {
                $blocks[] = "<!-- wp:paragraph -->\n{$part}\n<!-- /wp:paragraph -->";
            } else {
                $blocks[] = "<!-- wp:html -->\n{$part}\n<!-- /wp:html -->";
            }
        }

        $offset = 0;
        foreach ( $images as $image ) {
            $attachment_id = $this->attach_image( $image['filename'], $image['mime'], $image['data_base64'], $post_id );
            if ( is_wp_error( $attachment_id ) ) {
                error_log( 'TAP: attach_image failed for ' . $image['filename'] . ': ' . $attachment_id->get_error_message() );
                continue;
            }
            $idx = max( 0, min( (int) $image['position'] + $offset, count( $blocks ) ) );
            array_splice( $blocks, $idx, 0, [ $this->image_block( $attachment_id ) ] );
            $offset++;
        }

        $body = implode( "\n\n", $blocks );

        $cover_block = '';
        if ( $cover !== null ) {
            $cover_attachment_id = $this->attach_image( $cover['filename'], $cover['mime'], $cover['data_base64'], $post_id );
            if ( is_wp_error( $cover_attachment_id ) ) {
                error_log( 'TAP: attach_image (cover) failed for ' . $cover['filename'] . ': ' . $cover_attachment_id->get_error_message() );
            } else {
                $cover_block = $this->image_block( $cover_attachment_id ) . "\n\n";
            }
        }

        return $cover_block . self::NAV_BLOCK . "\n\n" . self::SEPARATOR . "\n\n" . $body . "\n\n" . self::SEPARATOR . "\n\n" . self::NAV_BLOCK;
    }

    private function image_block( int $attachment_id ): string {
        $url = esc_url( wp_get_attachment_url( $attachment_id ) );
        return "<!-- wp:image {\"id\":{$attachment_id}} -->\n"
            . "<figure class=\"wp-block-image\"><img src=\"{$url}\" class=\"wp-image-{$attachment_id}\" alt=\"\"/></figure>\n"
            . "<!-- /wp:image -->";
    }
```

- [ ] **Step 2: Verify manually**

`create_chapter_page()` still calls `convert_to_blocks( $data['chapter_body'] )` with the old 1-arg form at this point (Task 6 updates the caller) — confirm that call site still compiles/runs unchanged (all new params have defaults):

```bash
cd /home/pun/workspace/wp-dev && docker compose exec wordpress php -l /var/www/html/wp-content/plugins/translation-assistant-publisher/includes/class-publisher.php
```

Expected: `No syntax errors detected`.

- [ ] **Step 3: Commit**

```bash
git -C /home/pun/workspace/wp-dev add plugins/translation-assistant-publisher/includes/class-publisher.php
git -C /home/pun/workspace/wp-dev commit -m "feat(publisher): convert_to_blocks splices wp:image blocks at anchor positions"
```

---

### Task 6: Wire `create_chapter_page()` through; version bump; end-to-end verification

**Files:**
- Modify: `/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher/includes/class-publisher.php`
- Modify: `/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher/translation-assistant-publisher.php`

**Interfaces:**
- Consumes: `convert_to_blocks()` (Task 5), `attach_image()` (Task 4), the `images`/`cover` payload keys produced by client Tasks 1-3.
- Produces: nothing further — this is the last task.

**Context:** Attachments need a real `post_id` to parent to, but `create_chapter_page()` currently builds `$content` (which would need attachment IDs) *before* `wp_insert_post()` returns that ID. Fix: create the page first with empty content, then build the block content (now that a real page ID exists) and `wp_update_post()` it in.

- [ ] **Step 1: Restructure `create_chapter_page()`**

Replace the method in `class-publisher.php`:

```php
    public function create_chapter_page( array $data, int $index_id, int $user_id ): int|WP_Error {
        $series_slug = sanitize_title( $data['series_slug'] );
        $chapter_idx = (int) $data['chapter_index'];
        $slug        = "{$series_slug}-c{$chapter_idx}";

        $args = [
            'post_type'      => 'page',
            'post_status'    => 'publish',
            'post_title'     => $data['series_title_short'] . ' ' . $chapter_idx . ' - ' . $data['chapter_title'],
            'post_name'      => $slug,
            'post_parent'    => $index_id,
            'post_author'    => $user_id,
            'post_content'   => '',
            'comment_status' => 'open',
            'menu_order'     => $chapter_idx,
        ];

        if ( ! empty( $data['password'] ) ) {
            $args['post_password'] = sanitize_text_field( $data['password'] );
        }

        if ( ! empty( $data['publish_date'] ) ) {
            $dt = new DateTime( $data['publish_date'], new DateTimeZone( 'UTC' ) );
            $args['post_date_gmt'] = $dt->format( 'Y-m-d H:i:s' );
            $dt->setTimezone( wp_timezone() );
            $args['post_date']   = $dt->format( 'Y-m-d H:i:s' );
            $args['post_status'] = 'future';
        }

        $chapter_id = wp_insert_post( $args, true );
        if ( is_wp_error( $chapter_id ) ) return $chapter_id;

        $content = $this->convert_to_blocks(
            $data['chapter_body'],
            $data['images'] ?? [],
            $data['cover'] ?? null,
            $chapter_id
        );
        wp_update_post( [ 'ID' => $chapter_id, 'post_content' => $content ], true );

        return $chapter_id;
    }
```

- [ ] **Step 2: Bump the plugin version**

In `translation-assistant-publisher.php`, change:

```php
 * Version:     1.3.3
```

to:

```php
 * Version:     1.4.0
```

- [ ] **Step 3: End-to-end verification against the local Docker WP**

```bash
cd /home/pun/workspace/wp-dev && docker compose exec wordpress php -l /var/www/html/wp-content/plugins/translation-assistant-publisher/includes/class-publisher.php
```

Expected: `No syntax errors detected`.

In WP admin (`http://localhost:8080/wp-admin`), confirm an API key exists (Settings → TA Publisher) or generate one. Then, from a Python shell with the venv active, build and send a real payload with an inline image and a cover to a fresh (never-before-published) `chapter_index`:

```bash
source .venv/bin/activate
python3 - <<'EOF'
import json, urllib.request, base64

img = base64.b64encode(b"\xff\xd8\xff\xe0fakejpegbytesfakejpegbytes").decode()
payload = {
    "api_key": "<paste key from WP admin>",
    "series_title": "Illustration Test Series",
    "series_slug": "illustration-test-series",
    "series_title_short": "ITS",
    "series_link": "https://example.com/its",
    "chapter_index": 1,
    "chapter_title": "Chapter 1",
    "chapter_body": "<p>First paragraph.</p>\n<p>Second paragraph.</p>",
    "first_line": "First paragraph.",
    "images": [{"position": 1, "filename": "inline.jpg", "mime": "image/jpeg", "data_base64": img}],
    "cover": {"filename": "cover.jpg", "mime": "image/jpeg", "data_base64": img},
}
req = urllib.request.Request(
    "http://localhost:8080/wp-json/ta-publisher/v1/publish",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(req).read().decode())
EOF
```

Expected: JSON response with `"status": "ok"` and a `page_url`. Open that `page_url` in a browser — confirm the cover image renders at the top of the page (before the nav block) and the inline image renders between the first and second paragraph. Check WP admin Media Library — two new attachments, both parented to the chapter page (Attachment details → "Uploaded to").

Re-run the exact same `curl`/script a second time (same `chapter_index`) — expected: `"created": false`, no duplicate attachments created (idempotency short-circuit in `publish()` returns before `create_chapter_page()` runs).

- [ ] **Step 4: Commit**

```bash
git -C /home/pun/workspace/wp-dev add plugins/translation-assistant-publisher/includes/class-publisher.php plugins/translation-assistant-publisher/translation-assistant-publisher.php
git -C /home/pun/workspace/wp-dev commit -m "feat(publisher): wire images/cover through create_chapter_page, bump to 1.4.0"
```

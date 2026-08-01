# WordPress Republish Update — Design

## Problem

Republishing an already-published chapter to WordPress is currently a no-op on the server. `TAP_Publisher::publish()` (in the separate `translation-assistant-publisher` WP plugin, `includes/class-publisher.php`) checks `chapter_exists()` and, if the page already exists, returns `created: false` immediately — it never calls `create_chapter_page()` or `create_post()`, the only places that write `post_content` from the client's payload. A typo fix, body edit, or image swap made after first publish is silently dropped: the client shows "Already published," the local `wp_status` row is left untouched (`main_widget.py`, `_on_publish_done`), and the live WP page/post never changes.

This is inconsistent with the synopsis path (`chapter_idx === 0`), where `handle_synopsis()` always runs `wp_update_post` unconditionally — synopsis edits do take effect on every publish.

Three related gaps surfaced while investigating:

1. **Partial-failure lockout.** `create_chapter_page()` inserts the page and writes its content *before* `create_post()` runs. If `create_post()` fails afterward, the page now exists with content, so every future republish hits the early-return above — the teaser post is permanently `null` with no recovery path.
2. **Renumber orphaning.** The page slug is `{series_slug}-c{chapter_idx}`. Renumbering a chapter (editing `series_order`) and republishing looks up the *new* slug, finds nothing, and creates a brand-new page — the old page and its ToC entry are orphaned forever (`append_toc_entry` only appends, never removes/updates existing entries).
3. **Reschedule-via-republish.** `publish_date` is only honored in the initial-create branch; changing a scheduled chapter's date and republishing does nothing, since the early-return happens first.

## Scope

Covers two repos:
- `translation-assistant-publisher` WP plugin (`includes/class-publisher.php`)
- This repo (`translation_assistant/db.py`, `translation_assistant/wp_publisher.py`, `translation_assistant/ui/main_widget.py`)

Out of scope: concurrent-edit conflict resolution (single-user tool, not a real risk here); WP plugin automated test infrastructure (none exists today — verification here is a manual smoke-test checklist, matching this repo's existing convention for WP-touching changes).

## Chosen semantics: always-update

Republish always pushes the client's current state (body, images, schedule) to the live page/post, overwriting whatever is there. This matches how synopsis already behaves and avoids adding a second "Update" action the user would have to remember to use instead of "Publish." Trade-off accepted: any manual edits made directly in wp-admin get overwritten by the next republish — acceptable since this tool is the source of truth for chapter content.

## Data model changes

**Client (`db.py`):**
- New column `documents.wp_chapter_index INTEGER DEFAULT NULL`, added via the existing idempotent `PRAGMA table_info` / `ALTER TABLE` migration pattern in `_apply_schema`, alongside `wp_status`/`wp_post_url`/`wp_date` (currently lines 161-163). Stores the `series_order` value that was actually live on WP as of the last successful publish.
- `set_document_wp_status(doc_id, wp_status, wp_post_url, wp_date, wp_chapter_index)` and `get_document_wp_status(doc_id)` (currently lines 527-542) gain this field.

**Server (plugin):**
- `_tap_linked_post_id` post meta on the chapter page must be set unconditionally on creation (currently only `if (!empty($data['password']))`, lines 61-63). This is what lets the update path locate the teaser post reliably, and it's also the partial-failure fix: if the page exists but this meta is missing/dangling (post deleted or never created), that's the detectable signal to create the post now instead of losing it forever.

**Why the client needs `wp_chapter_index`:** the page slug encodes the chapter index. If a user renumbers and republishes, looking up by the new index finds nothing. The client must tell the server what index it last published at so the server can locate and rename the old page instead of creating a duplicate. Sent as `previous_chapter_index` in the payload, only when it differs from the current `series_order` and a prior publish exists.

## Server-side logic (`class-publisher.php`)

`publish()`, chapter branch (`chapter_idx > 0`):

```
existing = chapter_exists(series_slug, chapter_idx)
if !existing and previous_chapter_index given:
    existing = chapter_exists(series_slug, previous_chapter_index)   # renumber case
    renumbered = existing is truthy

if existing:
    old_url = get_permalink(existing.ID)                             # capture before any rename
    if renumbered:
        rename post_name -> "{series_slug}-c{chapter_idx}"
        update post_title, menu_order
    update_chapter_page(existing.ID, data)                           # rebuild content, see below
    update_toc_entry(index_id, old_url, new_title, new_permalink)    # fix stale anchor, not just append

    linked_post_id = get_post_meta(existing.ID, '_tap_linked_post_id')
    if linked_post_id and get_post(linked_post_id):
        update_post(linked_post_id, data, new_permalink)             # title + schedule only
    else:
        linked_post_id = create_post(data, new_permalink, user_id)   # partial-failure recovery
        update_post_meta(existing.ID, '_tap_linked_post_id', linked_post_id)

    return { status: ok, page_url, post_url, created: false, updated: true, scheduled: ... }

# else: unchanged create path, but now always writes _tap_linked_post_id (not just when password set)
```

**`update_chapter_page()` (new):**
1. Delete every attachment where `post_parent == chapter_id` (`get_posts(type=attachment, parent=chapter_id)` → `wp_delete_attachment($id, true)`) before rebuilding — `convert_to_blocks()` re-attaches everything fresh from the payload each call, so without this step every republish duplicates media in the library.
2. Rebuild `post_content` via the existing `convert_to_blocks()` and `wp_update_post`.
3. If `publish_date` is present, apply the same future/publish `post_status` + `post_date`/`post_date_gmt` logic `create_chapter_page` already uses for initial creation — this is what makes reschedule-via-republish work.

**`update_toc_entry()` (new):** locates the `<a href="$old_url">` anchor in the index page and replaces both href and text with the new permalink/title. Needed because `append_toc_entry` only appends — without this, a renumber leaves a dead link forever, and a title-only typo fix leaves stale ToC text.

**`update_post()` (new):** trimmed analogue of `create_post()` — updates `post_title` and re-applies the scheduling logic. Does not touch the teaser body beyond the chapter-link line if the URL changed.

## Client-side changes

**`wp_publisher.py`** `build_payload()` (currently lines 182-228): new optional `previous_chapter_index: int | None` param; included in the payload only when it differs from `doc_meta["series_order"]`.

**`main_widget.py`** `_on_publish_wp` (lines 1389-1596): read `get_document_wp_status(doc_id)` before building the payload, pass its `wp_chapter_index` through as `previous_chapter_index`.

**`main_widget.py`** `_on_publish_done` (lines 1598-1650): currently skips `set_document_wp_status` when `created` is `False` (lines 1608-1613). Change: call it whenever `created` **or** the new `updated` response key is truthy, refreshing `wp_status`/`wp_post_url`/`wp_date`/`wp_chapter_index` on every successful publish or update.

**Confirm-dialog copy:** when cached status shows "Published," append a short clause — e.g. "— republishing will overwrite the live chapter" — so always-update semantics aren't a silent surprise. String-only change, no new controls.

## Testing

- `tests/test_db.py`: round-trip test for `wp_chapter_index` through `set_document_wp_status`/`get_document_wp_status`.
- New or existing `test_wp_publisher.py`: `build_payload` includes `previous_chapter_index` only when it differs from `series_order`, omitted otherwise.
- `main_widget.py` tests: `_on_publish_done` updates local wp_status when `updated: true` even though `created: false`.
- Plugin (manual smoke test, no automated infra exists):
  1. Publish a chapter, edit its body/fix a typo, republish — confirm live page content changed and attachment count on the page did not grow.
  2. Renumber a published chapter and republish — confirm the old page was renamed (no orphan page) and the ToC entry now points at the new URL/title.
  3. Simulate partial failure (temporarily force `create_post` to fail after the page is created), then republish again — confirm the follow-up completes the missing post instead of looping forever with `post_url: null`.
  4. Reschedule a future chapter's `publish_date` and republish — confirm `post_date`/`post_status` updated on both the page and the linked post on WP.

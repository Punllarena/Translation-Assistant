# WordPress ToC Volume Separation — Design Spec

**Goal:** Show a visual break between volumes on the WordPress series ToC page, so a series with multiple imported volumes doesn't read as one undifferentiated chapter list.

**Background:** The ToC page is rendered entirely by a separate plugin repo, `translation-assistant-publisher` (`/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher`), not by this app. This app (`translation_assistant/wp_publisher.py`) only POSTs a per-chapter JSON payload to that plugin's REST endpoint (`build_payload()` in `wp_publisher.py`). The plugin's `TAP_Publisher::append_toc_entry()` (`includes/class-publisher.php`) appends one `<p><a>` link per chapter to the series' index page content, right before a `<!-- ta-toc-end -->` marker, in publish order. There is currently no heading or grouping in that content — this spec adds one.

This is a two-repo change: a small payload addition here, and the actual rendering logic in the WP plugin repo.

**Visual reference (chosen option):** a plain `<h3>{volume_title}</h3>` heading inserted before that volume's first chapter link — matching the ToC's existing plain-paragraph-link style. (Rejected alternative: heading + indented/grouped chapter links under it — bigger change to `append_toc_entry`'s string-splicing for a visual gain not asked for.)

**Out of scope:**
- No `volume_index` column or numeric ordering — volume boundaries are detected structurally (see below), not via an ordinal.
- Renaming a volume in TA (see the separate volume-rename-merge-guard spec) does not retroactively rewrite an already-published heading's text on the WP page. Known gap, not solved here.
- No changes to `update_toc_entry` (the republish/renumber path) — it only fixes an existing link's href/title, never touches headings.

## Design

### TA-side (`translation_assistant/wp_publisher.py`)

`build_payload()` gains one field, following the existing optional-field pattern already used for `unlock_chapter_index`/`previous_chapter_index`:

```python
if doc_meta.get("volume_title"):
    payload["volume_title"] = doc_meta["volume_title"]
```

`doc_meta` already carries `volume_title` (added to `list_documents()`/`get_document()` by the earlier edit-volume-metadata work) — no DB or UI change needed on this side.

### WP-side (`translation-assistant-publisher`, `includes/class-publisher.php`)

`append_toc_entry(int $index_id, string $chapter_title, string $chapter_url)` gains a 4th parameter: `string $volume_title = ''`.

Before splicing in the chapter's paragraph entry, check whether a heading for `$volume_title` already exists in the page content — a substring search for `<h3>` . esc_html($volume_title) . `</h3>`. If `$volume_title` is non-empty and no such heading is present yet, prepend a heading block immediately before the new paragraph entry:

```
<!-- wp:heading {"level":3} -->
<h3>{esc_html($volume_title)}</h3>
<!-- /wp:heading -->
```

then insert the paragraph entry exactly as today (same splice target: right before `<!-- ta-toc-end -->`, or the legacy `<ul class="ta-toc">` fallback path, unchanged).

The one call site, `publish()` (~line 122):
```php
$this->append_toc_entry( $index_id, $data['chapter_title'], $chapter_url );
```
becomes:
```php
$this->append_toc_entry( $index_id, $data['chapter_title'], $chapter_url, $data['volume_title'] ?? '' );
```

**Why a substring check, not stateful/ordering logic:** it's naturally idempotent (calling it twice for the same volume never duplicates the heading), doesn't depend on publish order being tracked anywhere, and needs no new state — the ToC page's existing content is already the source of truth for "has this volume's heading been written yet."

## Edge Cases

- **Legacy/non-EPUB chapters** (`volume_title == ""` or key absent): no heading logic runs at all; the ToC entry looks exactly as it does today.
- **Chapter 0 (synopsis):** untouched — the synopsis path (`handle_synopsis`) never calls `append_toc_entry`.
- **Republish/renumber** (`update_toc_entry`): untouched — it only fixes an existing anchor's href/title text, so no risk of a duplicate heading on an update.
- **Publish-order dependency:** a volume's heading lands correctly only if that volume's first chapter is the first of that volume to be published — consistent with this codebase's existing sequential-publish assumption (e.g. the `previous_chapter_index` renumber-detection logic already relies on the same ordering).
- **Coincidentally identical volume titles across different (unrelated) series:** not a concern — the heading substring check runs against one series' index page content only, never across series.

## Testing

- **TA-side** (`tests/test_wp_publisher.py`):
  - `test_build_payload_includes_volume_title` — `doc_meta` with a non-empty `volume_title` produces a payload containing it.
  - `test_build_payload_omits_blank_volume_title` — `doc_meta` with `volume_title=""` (or missing key) produces a payload with no `volume_title` key at all.
- **WP-side:** no existing test harness in the plugin repo (no PHPUnit setup found). Verification is manual for this spec: publish two volumes to a test series via the TA app, inspect the resulting ToC page's rendered HTML for one heading per volume with no duplicates on a second publish to the same volume. Adding PHPUnit coverage to the plugin is a separate, larger undertaking not folded into this spec.

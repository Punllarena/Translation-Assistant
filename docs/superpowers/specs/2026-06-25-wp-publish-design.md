# WordPress Publish — Design Spec (Translation Assistant Side)

**Date:** 2026-06-25  
**Status:** Draft  
**Companion:** [Translation Assistant Publisher WP plugin](https://github.com/Punllarena/translation-assistant-publisher)

---

## Overview

Add "Publish to WordPress" capability to Translation Assistant. The user opens a document, selects **File → Publish to WordPress**, and the app builds the REST payload from existing DB data and posts it to the companion WP plugin endpoint.

---

## What Already Exists (reused as-is)

| Data needed by WP payload | Source in TA |
|---|---|
| `series_title` | `documents.series_title` |
| `series_link` | `series_profiles.syosetu_url` |
| `chapter_index` | `documents.series_order` |
| `chapter_title` | `documents.chapter_title` |
| Translated lines | `db.get_lines(doc_id)` → `translated_text` per row |

---

## What Needs Adding

### 1. New DB fields (`series_profiles` table)

Two new columns, added via idempotent migration (existing pattern in `db.py`):

| Column | Type | Purpose |
|---|---|---|
| `series_slug` | `TEXT NOT NULL DEFAULT ''` | URL-safe series identifier (e.g. `sword-of-the-wanderer`) |
| `series_title_short` | `TEXT NOT NULL DEFAULT ''` | Short title for post title (e.g. `SotW`) |

### 2. New `AppSettings` fields

| Key | Type | Purpose |
|---|---|---|
| `wp_endpoint_url` | `str` | Full URL to WP REST endpoint (e.g. `https://mysite.com/wp-json/ta-publisher/v1/publish`) |
| `wp_api_key` | `str` | API key generated from WP Admin → Settings → TA Publisher |

Stored via existing `AppSettings` pattern (`QSettings("joeglens", "TranslationAssistant")`). Global — one key per TA install, one WP author.

### 3. New module: `translation_assistant/wp_publisher.py`

Pure Python (no Qt). Contains:

- `build_chapter_body(lines: list[dict]) -> str`  
  Iterates lines in order, wraps each non-empty `translated_text` in `<p>...</p>`. Returns HTML string.

- `get_first_line(lines: list[dict]) -> str`  
  Returns first non-empty `translated_text` as plain text (no HTML tags).

- `build_payload(doc_meta: dict, series_meta: dict, lines: list[dict]) -> dict`  
  Assembles the full JSON payload dict from DB data. Raises `ValueError` if required fields are missing.

- `publish(endpoint_url: str, payload: dict, timeout: int = 15) -> dict`  
  Sends `POST` request via `urllib.request` (stdlib, no new dependencies). Returns parsed JSON response. Raises `WPPublishError` on HTTP error or connection failure.

- `class WPPublishError(Exception)` — carries `status_code: int | None` and `message: str`.

### 4. UI changes

#### A. Series Manager dialog (`dlg_series.py`)

Add two fields to the existing Series Manager:
- **Series Slug** — text input, auto-populates from series title on first open (slugified), user can override
- **Short Title** — text input

Saved to `series_profiles` on dialog accept.

#### B. Settings dialog (`dlg_wp_settings.py`)

New dialog under Preferences menu — **WordPress Settings**:
- **Endpoint URL** — text input, saved to `AppSettings.wp_endpoint_url`
- **API Key** — text input (masked, `QLineEdit.EchoMode.Password`), saved to `AppSettings.wp_api_key`
- **Test Connection** button — sends `POST` with empty body, expects a 400 response (confirms endpoint reachable)

#### C. Menu action

`CombinedMainWindow._setup_menubar()` — add **Publish to WordPress** under the File menu (after existing Export actions).  
`TranslationAssistantWidget._build_actions()` — add `action_publish_wp`:
- Enabled only when a document is open (`_doc_id is not None`)
- Triggers `_on_publish_wp()`

#### D. `_on_publish_wp()` in `main_widget.py`

Flow:
1. Check `AppSettings.wp_endpoint_url` and `wp_api_key` set — if not, open WP Settings dialog
2. Load series meta from `series_profiles` for the current document's series
3. Check `series_slug`, `series_title_short` set — if missing, open Series Manager to fill them
4. Load lines via `db.get_lines(self._doc_id)`
5. Check at least one non-empty `translated_text` exists — if not, show error "No translated lines to publish"
6. Build payload via `wp_publisher.build_payload()`
7. Show confirmation dialog: "Publish **{chapter_title}** (Chapter {chapter_index}) to WordPress?" with summary of what will be created
8. On confirm: run `wp_publisher.publish()` in a `QThread` worker (non-blocking)
9. On success: show result notice with clickable `page_url` and `post_url`
10. On error: show `WPPublishError.message` in a warning dialog

---

## Payload Assembly

From `build_payload(doc_meta, series_meta, lines)`:

```python
{
    "api_key":            api_key,          # from AppSettings.wp_api_key
    "series_title":       doc_meta["series_title"],
    "series_slug":        series_meta["series_slug"],
    "series_title_short": series_meta["series_title_short"],
    "series_link":        series_meta["syosetu_url"],
    "chapter_index":      doc_meta["series_order"],     # 0 = synopsis, 1+ = chapters
    "chapter_title":      doc_meta["chapter_title"],
    "chapter_body":       build_chapter_body(lines),
    "first_line":         get_first_line(lines),        # omitted/empty when chapter_index == 0
}
```

**chapter_index = 0 (synopsis):** `first_line` is omitted from the payload (WP plugin doesn't require it for index=0).

---

## Slugify Helper

`series_slug` auto-populated from `series_title` using:

```python
import re, unicodedata

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")
```

Placed in `wp_publisher.py`. User can override in Series Manager.

---

## No New Dependencies

- HTTP: `urllib.request` (stdlib)
- JSON: `json` (stdlib)
- No `requests`, no `httpx`

---

## Error Handling

| Condition | Behaviour |
|---|---|
| Endpoint URL not set | Prompt to open WP Settings |
| Series fields incomplete | Prompt to open Series Manager |
| No translated lines | Warning dialog, no request sent |
| HTTP 401 | "Invalid API key — check WordPress Settings" |
| HTTP 400 | Show WP error message |
| HTTP 409 / `created: false` | "Chapter already published. Page: {url}" (not an error) |
| Connection timeout / error | "Could not reach {url}. Check endpoint setting." |
| HTTP 500 | "WordPress reported an error: {message}" |

---

## Files Changed

| File | Change |
|---|---|
| `translation_assistant/db.py` | Add `series_slug`, `series_title_short` columns to `series_profiles` via idempotent migration |
| `translation_assistant/settings.py` | Add `wp_endpoint_url`, `wp_api_key` getter/setter |
| `translation_assistant/wp_publisher.py` | New module: payload builder, HTTP publish, WPPublishError |
| `translation_assistant/ui/dlg_series.py` | Add slug and short title fields |
| `translation_assistant/ui/main_widget.py` | Add `action_publish_wp`, `_on_publish_wp()`, QThread worker |
| `translation_assistant/ui/combined_window.py` | Wire menu action + WP Settings entry |
| `translation_assistant/ui/dlg_wp_settings.py` | New dialog for endpoint URL + test connection |
| `tests/test_wp_publisher.py` | Unit tests for `build_chapter_body`, `get_first_line`, `build_payload`, `slugify` |

---

## Out of Scope

- Bulk/batch publish (all chapters in a series at once) — add later if needed
- Publish status tracking in DB (already-published flag) — `created: false` from WP is sufficient
- Rich text / ruby annotation export to WP — plain `<p>` tags only
- OAuth / WP Application Passwords auth — API key is sufficient for this use case

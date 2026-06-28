# WP Publish Status, Safeguard & Default Schedule Time — Design Spec

**Date:** 2026-06-28

## Overview

Three related features around WordPress publishing:

1. **Status check** — query WP to see if a chapter is published, scheduled (future), or unpublished; cache result in app DB; surface it in status bar, publish dialog, and doc list.
2. **Schedule safeguard** — block (with override) publishing chapter N if chapter N−1 is still scheduled (future) on WP.
3. **Default schedule time** — store a preferred HH:MM time in settings so the schedule picker pre-fills to the next future occurrence of that time rather than now+1h.

---

## 1. WP Plugin — New Status Endpoint

**File:** `/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher/translation-assistant-publisher.php`

Add a new REST route:

```
GET /wp-json/ta-publisher/v1/status
    ?api_key=<key>
    &series_slug=<slug>
    &chapter=<N>
```

**Auth:** same `api_key` validation as `/publish`.

**Logic:**
- For `chapter > 0`: reuse existing `chapter_exists($series_slug, $chapter_idx)` — looks up page by slug `{series_slug}/{series_slug}-c{N}`.
- For `chapter=0` (synopsis): `get_page_by_path($series_slug)` — the index page.
- Return the page's `post_status`.

**Response:**
```json
{ "status": "publish" | "future" | "draft" | "not_found", "post_url": "<permalink or null>" }
```

**Implementation in `class-publisher.php`:** add `get_chapter_status(string $series_slug, int $chapter_idx): array` method.

---

## 2. App DB — `documents` Table Columns

**File:** `translation_assistant/db.py`

Two new columns added via idempotent `ALTER TABLE` in `_apply_schema()`:

```sql
ALTER TABLE documents ADD COLUMN wp_status   TEXT;   -- "publish"|"future"|"draft"|"not_found"|NULL
ALTER TABLE documents ADD COLUMN wp_post_url TEXT;   -- post permalink, NULL until published
```

New methods:

```python
def set_document_wp_status(self, doc_id: int, status: str, post_url: str | None) -> None
def get_document_wp_status(self, doc_id: int) -> dict  # {"wp_status": ..., "wp_post_url": ...}
```

Status is written in two places:
- After successful `publish()` call: map `scheduled=true` → `"future"`, `scheduled=false` → `"publish"`.
- After explicit status refresh (triggered from publish dialog).

---

## 3. `wp_publisher.py` — `check_status` Function

```python
def check_status(
    endpoint_url: str,
    api_key: str,
    series_slug: str,
    chapter: int,
    timeout: int = 10,
) -> dict:
    ...
```

- Derives base URL from `endpoint_url` by stripping `/publish` and appending `/status`.
- Sends `GET` with query params.
- Returns `{"status": "...", "post_url": "..."}`.
- Raises `WPPublishError` on network/auth failure.

No new settings needed — reuses `wp_endpoint_url`.

---

## 4. Settings — `wp_default_schedule_time`

**File:** `translation_assistant/settings.py`

```python
@property
def wp_default_schedule_time(self) -> str:  # "HH:MM" or ""
    return self._qs.value("wp_default_schedule_time", "")

@wp_default_schedule_time.setter
def wp_default_schedule_time(self, value: str) -> None:
    self._qs.setValue("wp_default_schedule_time", value)
```

**WP Settings dialog** (`dlg_wp_settings.py`): new row "Default schedule time" with a `QTimeEdit`. Empty/cleared = no default (picker falls back to now+1h).

**Pre-fill logic** in `_on_publish_wp`:
```
if wp_default_schedule_time is set:
    parse HH:MM
    candidate = today at HH:MM (local)
    if candidate <= now: candidate += 1 day
    set QDateTimeEdit initial value to candidate
else:
    use now + 1h (current behaviour)
```

---

## 5. UI Changes

### 5a. Status Bar

**File:** `translation_assistant/ui/main_widget.py`

New `QLabel` (`_wp_status_label`) added in `_setup_statusbar()`.

- Text: `WP: Published` / `WP: Scheduled` / `WP: Draft` / `WP: —`
- Updated on doc load by reading cached `wp_status` from DB.
- Clicking opens `wp_post_url` in browser (`QDesktopServices.openUrl`) if URL is available.

### 5b. Publish Dialog

**File:** `translation_assistant/ui/main_widget.py` — `_on_publish_wp`

Additions to the confirm dialog:

1. **Status line** at top: "Last known status: Published / Scheduled / Not published / Unknown". Reads from DB cache initially.

2. **Async refresh**: when dialog opens, a `_StatusCheckWorker(QThread)` fires `check_status()` for the current doc. On success: updates dialog label + writes new status to DB. On failure: shows "(could not reach WP)" next to cached status.

3. **Safeguard**: before the dialog is shown, check if `series_order > 0`. If so, look up the previous chapter doc (`series_order - 1`) and its `wp_status`. If `wp_status == "future"`:
   - Show warning banner in dialog: "Chapter N−1 is still scheduled and hasn't gone live yet."
   - Replace OK button with two buttons: **Cancel** (default) and **Publish Anyway**.
   - If user picks Cancel, abort. If Publish Anyway, proceed normally.
   - Previous chapter lookup uses cached DB value; no extra WP request.

### 5c. Doc List (`dlg_open.py`)

New column in the document table: `WP` with text badge:
- `pub` — `wp_status == "publish"`
- `sched` — `wp_status == "future"`
- blank — NULL or other

Reads cached DB only. No live fetch on list open.

---

## 6. Data Flow

```
Publish success
  → _on_publish_done reads result["scheduled"]
  → maps to "future" or "publish"
  → db.set_document_wp_status(doc_id, status, post_url)
  → status bar label updates

Publish dialog open
  → read cached status from DB → show in dialog
  → _StatusCheckWorker fires check_status()
  → on result: db.set_document_wp_status() + update dialog label

Doc load
  → db.get_document_wp_status(doc_id) → update status bar label

Safeguard check
  → get prev doc id from series_order - 1
  → db.get_document_wp_status(prev_doc_id)
  → if "future" → show warning in dialog
```

---

## 7. Error Handling

- `check_status()` raises `WPPublishError` on failure → dialog shows stale cached status with "(could not reach WP)" note. Publish is not blocked by a failed status check.
- Safeguard uses cached status only. If cache is NULL (never published or never checked), no safeguard fires — user can publish freely.
- `set_document_wp_status` is write-through: failure logs silently, does not interrupt publish flow.

---

## 8. Testing

- `test_wp_publisher.py`: add `test_check_status_*` cases (success, 401, network error).
- `test_db.py`: add `test_set_get_document_wp_status` and schema migration test.
- `test_settings.py`: add `test_wp_default_schedule_time`.
- `test_main_window.py` / `test_combined_window.py`: safeguard dialog path (mock `get_document_wp_status` returning `"future"`).
- WP plugin: manual test via `curl` against local wp-dev instance.

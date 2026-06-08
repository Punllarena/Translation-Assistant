# Syosetu Series Scraping — Design Spec

**Date:** 2026-06-08

## Overview

Allow a syosetu series URL (e.g. `https://novel18.syosetu.com/n7696mg/`) to be linked to a series in the app. From that link, the user can fetch all chapters in bulk at a rate-limited pace, and later check for and fetch new chapters. Chapter titles use the JP title from syosetu temporarily. The user no longer needs to paste a chapter URL for each document.

---

## Data Layer (`db.py`)

### Schema migration

`series_profiles` gains a new nullable column:

```sql
ALTER TABLE series_profiles ADD COLUMN syosetu_url TEXT NOT NULL DEFAULT '';
```

Applied idempotently in `_apply_schema` using the existing `PRAGMA table_info` pattern.

### New methods

| Method | Signature | Purpose |
|---|---|---|
| `get_series_url` | `(series_title: str) -> str` | Returns stored URL or `""` |
| `set_series_url` | `(series_title: str, url: str) -> None` | Upserts into `series_profiles`; empty string clears URL |
| `get_series_chapters` | `(series_title: str) -> list[int]` | Returns existing `series_order` values (detects already-fetched chapters) |
| `get_series_list_full` | `() -> list[dict]` | Returns `{title, url, chapter_count, profile_name}` for all series |

---

## Scraper (`scraper.py`)

### `fetch_series_index(url: str) -> list[dict]`

- Validates URL is a syosetu.com series root (no trailing chapter number)
- Fetches index page with `over18=yes` cookie
- Parses `dl.novel_sublist2 dd.subtitle` entries
- Returns `[{num: int, title: str, url: str}, ...]` ordered by chapter number

### `fetch_chapter(url: str) -> tuple[str, str]`

Thin alias for existing `fetch_syosetu()`. No behaviour change.

### `SeriesFetchWorker(QThread)`

```python
SeriesFetchWorker(
    chapters_to_fetch: list[dict],  # [{num, title, url}, ...]
)
```

Signals:
- `chapter_done(num: int, title: str, content: str)` — emitted after each successful fetch
- `progress(current: int, total: int)` — emitted after each fetch attempt
- `error(chapter_num: int, msg: str)` — non-fatal; worker continues to next chapter
- `finished()` — emitted when all chapters processed or worker stopped

Rate limit: 5-second sleep *after* each fetch before the next. First chapter fetches immediately. `QThread.sleep(5)` used; sleep is skipped after the last chapter.

Cancellation: caller calls `worker.requestInterruption()`; worker checks `isInterruptionRequested()` at the top of each loop iteration.

---

## UI

### `dlg_series.py` — Series Manager (new file)

A `QDialog` showing all series in a `QTableWidget` with columns:

| Series Title | Syosetu URL | Chapters | Profile |

Buttons (right-aligned, operate on selected row):
- **Set URL…** — `QInputDialog` pre-filled with current URL; empty submission clears URL
- **Fetch new chapters…** — disabled when selected series has no URL; opens `dlg_fetch_series.py`
- **Close**

Access points:
- File menu → "Manage Series…"
- Right-click on any document row in `dlg_open.py` where `series_title` is non-empty → "Manage Series…"

### `dlg_fetch_series.py` — Chapter Picker + Fetch Progress (new file)

Single dialog with two sequential phases:

**Phase 1 — Pick**

- On open, fires `fetch_series_index()` in a `QThread`; shows "Loading chapter list…" spinner
- On success, populates `QListWidget` with checkboxes
  - Already-fetched chapters (matched by `series_order` against `get_series_chapters()`) — greyed, unchecked, labelled "(already fetched)"
  - New chapters — pre-checked
- "Fetch Selected (N)" button; disabled if nothing checked

**Phase 2 — Fetch**

- "Fetch Selected" starts `SeriesFetchWorker` with checked chapters
- Shows `QProgressBar` + label "Fetching chapter N of M…"
- `chapter_done` signal → `db.create_document()` then `db.save_lines()` called immediately (no batching)
- `error` signal → appends warning line "Chapter N: {msg}" below progress bar (fetch continues)
- **Cancel** button → calls `worker.requestInterruption()`; already-fetched chapters are kept
- On `finished` → progress bar fills, label shows "Done — N chapters added.", Cancel becomes Close

### `dlg_new.py` — Series URL field (modification)

- Add optional "Series URL:" `QLineEdit` row in the form, below "Series Title:"
- Row hidden/disabled when Series Title is empty; shown when title is non-empty
- On create, if URL is non-empty, calls `db.set_series_url(series_title, url)`
- Pre-populates from `db.get_series_url(series_title)` when series autocomplete fires

### `dlg_open.py` — Right-click context menu (modification)

- Install `customContextMenuRequested` on the documents table
- If selected row has non-empty `series_title` → show context menu with "Manage Series…" action
- Action opens `dlg_series.py`

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| URL is not a syosetu.com series root | `fetch_series_index` raises `ValueError`; shown in dlg_fetch_series Phase 1 error label |
| Index page fetch fails (network) | Same as above |
| Individual chapter fetch fails | `error` signal emitted; warning shown; fetch continues |
| Worker cancelled mid-run | Already-committed documents kept; partial batch is fine |
| Series URL cleared by user | `set_series_url` with `""` clears it; "Fetch new chapters…" button disables |

---

## Testing

**`test_scraper.py`** (additions):
- `fetch_series_index` with mocked `requests.get` returning sample TOC HTML — verify chapter list parsed correctly, chapter numbers and titles extracted
- `fetch_series_index` with non-series URL — verify `ValueError` raised
- `SeriesFetchWorker` with patched `fetch_syosetu` — verify `chapter_done` emitted correct N times, `QThread.sleep` called N-1 times (not after last chapter)
- Worker cancellation — verify loop exits early, partial `chapter_done` emissions match

**`test_db.py`** (additions):
- `get_series_url` / `set_series_url` round-trip
- `get_series_chapters` returns correct `series_order` set
- `get_series_list_full` returns expected shape

---

## Out of Scope

- Resuming interrupted fetches across app restarts (already-fetched chapters are skipped by design)
- Syosetu pagination (series index loads all chapters on one page)
- Editing/renaming series title from Series Manager
- Non-syosetu series sources

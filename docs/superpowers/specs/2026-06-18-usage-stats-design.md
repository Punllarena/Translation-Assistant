# Usage Statistics — Design Spec

**Date:** 2026-06-18
**Status:** Approved

## Goal

Personal productivity tracking — paragraphs and source characters translated per day, visible in-app with daily history and a GitHub-style heatmap.

## Data Layer

### Schema migration

Add `translated_at TEXT DEFAULT NULL` to `lines` via idempotent migration in `Database._apply_schema()`:

```sql
ALTER TABLE lines ADD COLUMN translated_at TEXT DEFAULT NULL;
```

Existing lines remain NULL (correctly represent no known translation date).

### `save_translation` change

Set `translated_at = datetime('now')` when `text` is non-empty; set to `NULL` when text is cleared.

### New DB methods

**`get_today_stats() -> dict`**
```python
{"paragraphs": int, "chars": int}
```
Query: lines where `date(translated_at) = date('now')`.  
`chars` = `SUM(LENGTH(raw_text))` of matching lines (source JP characters).

**`get_daily_stats(days: int = 30) -> list[dict]`**
```python
[{"date": "YYYY-MM-DD", "paragraphs": int, "chars": int}, ...]
```
Query: group by `date(translated_at)` over last N days, newest first.  
Used for both the table (30 days) and the heatmap (365 days).

## UI

### Status bar label

- Added in `_setup_statusbar()`, right-aligned
- Format: `Today: 12 ¶ / 847 chars`
- Updates after every `_save_to_db()` call
- Click opens the stats dialog
- DB query failure: silently hide label (no crash)

### `Help → Statistics` menu item

Opens same stats dialog.

### Stats dialog (`translation_assistant/ui/dlg_stats.py`)

Layout (top to bottom):

1. **Heatmap widget** — custom `QWidget` subclass using `paintEvent` + `QPainter`
   - 52 columns × 7 rows, one cell per calendar day, last 52 weeks
   - Sunday = row 0, columns = weeks (oldest left, newest right)
   - 5 intensity levels (0–4): gray → green, auto-scaled to user's personal max paragraphs/day
   - Scale: level 0 = 0 paragraphs; levels 1–4 = quartiles of the non-zero max (i.e. max/4, max/2, 3*max/4, max)
   - Intensity keyed on **paragraphs** count
   - Hover tooltip: `"2026-06-15: 23 ¶ / 1,204 chars"`
   - Empty grid rendered gracefully when no data

2. **Today summary line** — bold, e.g. `Today: 23 paragraphs · 1,204 source chars`

3. **Toggle button** — `Last 7 days` / `Last 30 days` (switches table scope only; heatmap always shows 52 weeks)

4. **`QTableWidget`** — read-only, 3 columns: Date / Paragraphs / Chars
   - Newest row first
   - No editing

5. **Close button**

## Error handling

- Stats query failure → status bar label hidden, dialog shows empty state
- `translated_at IS NULL` rows excluded from all queries
- Pre-migration lines appear as no activity (correct)
- Heatmap renders empty grid with no data

## Testing

New tests in `test_db.py` (existing pattern — in-memory DB via `_conn` injection):

- `test_stats_empty` — fresh DB → `get_today_stats()` returns `{"paragraphs": 0, "chars": 0}`
- `test_stats_accumulate` — save 3 translations → today count = 3, chars = sum of raw lengths
- `test_stats_cleared` — save then clear translation → count decreases
- `test_daily_stats_multi_day` — mock `datetime('now')` via inserted rows with explicit dates → verify grouping

Heatmap widget: no unit test (pure paint code, no extractable logic).

## Files changed

| File | Change |
|------|--------|
| `translation_assistant/db.py` | Migration + `save_translation` + 2 new methods |
| `translation_assistant/ui/main_window.py` | Status bar label + menu item + refresh hook |
| `translation_assistant/ui/dlg_stats.py` | New dialog (heatmap widget + table) |
| `tests/test_db.py` | 4 new tests |

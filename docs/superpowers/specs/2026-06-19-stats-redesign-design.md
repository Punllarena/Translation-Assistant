# Stats Dialog Redesign

**Date:** 2026-06-19  
**Files touched:** `translation_assistant/db.py`, `translation_assistant/ui/dlg_stats.py`

## Goals

- Date display: friendly format ("June 19, 2026") instead of ISO ("2026-06-10")
- Count English words written (from `translated_text`)
- Summary covers Today / 7-day / 30-day / All-time (not just today)
- Stats per series in a separate tab
- Remove paragraph symbol (¶); use "paras"
- Add current streak, longest streak, best day stats

## Architecture

Two-tab `QTabWidget` inside `StatsDialog`:
- **Overview** — heatmap, summary table, streak line, daily detail table
- **By Series** — per-series aggregates

## Data Layer (`db.py`)

### English word count (SQL)

Approximate word count by counting spaces + 1 in `translated_text`:

```sql
COALESCE(SUM(
    CASE WHEN TRIM(translated_text) != ''
    THEN LENGTH(TRIM(translated_text)) - LENGTH(REPLACE(TRIM(translated_text), ' ', '')) + 1
    ELSE 0 END
), 0) AS en_words
```

### Modified methods

**`get_today_stats()`** — add `en_words` to SELECT.  
Returns: `{"paragraphs": int, "chars": int, "en_words": int}`

**`get_daily_stats(days)`** — add `en_words` to SELECT.  
Returns: `[{"date": str, "paragraphs": int, "chars": int, "en_words": int}, ...]`

### New methods

**`get_summary_stats()`**  
Four separate queries (today / 7-day / 30-day / all-time). Returns:
```python
{
  "today":   {"paragraphs": int, "chars": int, "en_words": int},
  "week":    {"paragraphs": int, "chars": int, "en_words": int},
  "month":   {"paragraphs": int, "chars": int, "en_words": int},
  "alltime": {"paragraphs": int, "chars": int, "en_words": int},
}
```

**`get_series_stats()`**  
JOIN `lines` + `documents`, GROUP BY `series_title`, exclude blank series, sort by paragraphs DESC.  
Returns:
```python
[{"series": str, "paragraphs": int, "chars": int, "en_words": int, "chapters": int}, ...]
```
`chapters` = `COUNT(DISTINCT document_id)`.

**`get_all_daily_stats()`**  
Same query as `get_daily_stats` but no day filter. Used for streak + best-day computation in the dialog.  
Returns: same shape as `get_daily_stats`.

## Dialog (`dlg_stats.py`)

### Overview tab (top to bottom)

1. **HeatmapWidget** — unchanged except tooltip: replace `¶ /` with `paras /`
2. **Summary QTableWidget** — 4 rows × 4 cols, no edit, no selection, fixed height:

   | Period | Paragraphs | Source Chars | EN Words |
   |---|---|---|---|
   | Today (June 19, 2026) | … | … | … |
   | Last 7 days | … | … | … |
   | Last 30 days | … | … | … |
   | All time | … | … | … |

   "Today" row label includes today's date: `date.today().strftime("%B %-d, %Y")`.

3. **Streak + best day QLabel** — single line below summary table:
   `Current streak: N days  ·  Longest streak: N days  ·  Best day: Month D, YYYY (N paras)`

4. **Toggle button** — existing 7/30 toggle, unchanged label logic
5. **Daily detail QTableWidget** — 4 cols: Date | Paragraphs | Source Chars | EN Words.  
   Date column: formatted `"June 19, 2026"` (strftime `"%B %-d, %Y"`).

### By Series tab

Single `QTableWidget`, 5 cols, no edit, sorted by paragraphs DESC:

| Series | Paragraphs | Source Chars | EN Words | Chapters |
|---|---|---|---|---|

If `get_series_stats()` returns empty list: show `QLabel("No series data yet.")` instead of table.

### Streak computation (Python, in `StatsDialog._compute_streaks`)

Input: all daily stats sorted by date ascending.

```
current_streak:
  walk backward from today; count consecutive days with paragraphs > 0
  if today has no entry, allow starting from yesterday

longest_streak:
  walk forward through full history; track max run of consecutive calendar days
```

Returns `(current_streak: int, longest_streak: int, best_day_date: str, best_day_paras: int)`.

## Testing

- `test_db.py`: add tests for `get_summary_stats`, `get_series_stats`, `get_all_daily_stats` with in-memory DB
- `test_dialogs.py`: smoke-test `StatsDialog` renders without crash with mock data (existing pattern)
- Streak computation: unit test in `test_db.py` or `test_core.py` via a helper function extracted from dialog

## Out of scope

- Estimated session time (needs gap-threshold tuning; follow-up)
- Revision rate (needs schema change; follow-up)
- Series drilldown in daily table (follow-up)

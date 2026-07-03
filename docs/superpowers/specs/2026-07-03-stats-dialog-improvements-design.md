# Stats Dialog Improvements — Design

**Date:** 2026-07-03
**Scope:** `translation_assistant/ui/dlg_stats.py`, `translation_assistant/core.py`, `translation_assistant/settings.py`

Three improvements to the Usage Statistics dialog: a dialog-wide metric switch, heatmap polish (labels, legend, click-to-select), and trend info (per-period comparison column + daily average line).

## 1. Metric switch

A `QComboBox` with entries **Paragraphs**, **Source Chars**, **EN Words** at the top of the Overview tab, in a row with the heatmap area.

The chosen metric drives:

- Heatmap cell intensity and thresholds (currently hardcoded to `paragraphs`).
- Heatmap tooltip leads with the chosen metric (still shows the others).
- "Best day" stat in the streak line (date + value of chosen metric).
- The "vs prev" comparison column (section 3).
- The daily-average line (section 3).

The summary table and daily table keep all three metric columns — they already show everything, no change needed there.

Selection persists across sessions via a new `AppSettings` key `stats_metric` (string: `"paragraphs" | "chars" | "en_words"`, default `"paragraphs"`), with typed getter/setter following the existing `AppSettings` pattern.

Switching metric re-renders the heatmap, streak line, comparison column, and daily-average line in place (no dialog reopen).

## 2. Heatmap polish

All rendered inside/around the existing custom-painted `HeatmapWidget`:

- **Month labels** along the top edge: month abbreviation ("Jan", "Feb", …) painted above the first week-column whose Sunday falls in a new month. Adds ~15 px to widget height.
- **Weekday labels** at the left edge: "Mon", "Wed", "Fri" painted next to rows 1, 3, 5. Adds ~28 px to widget width.
- **Color legend** below the heatmap: "Less ▢▢▢▢▢ More" — a small widget or label row using the same 5 `_COLORS`.
- **Cell click**: clicking a day cell scrolls the daily table to that date's row and selects it, if the date is within the currently shown 7/30-day window. Outside the window: no-op (tooltip already covers old dates). Implemented as a signal on `HeatmapWidget` (e.g. `day_clicked = Signal(str)` with ISO date) connected by `StatsDialog`.

Cell geometry math (`_cell_to_date`, `mouseMoveEvent` hit-testing) shifts by the new left/top label margins.

## 3. Trend info

### Comparison column

The summary table gains a 5th column **"vs prev"**:

| Row | Compares |
|---|---|
| Today | vs yesterday |
| Last 7 days | vs prior 7 days (days 8–14 back) |
| Last 30 days | vs prior 30 days (days 31–60 back) |
| All time | — (no prior period) |

Format: `+23%` / `−8%` / `0%`. When the previous period total is 0, show `—`. Values follow the chosen metric.

### Daily average line

A label under the summary table: `Daily avg (30d): 38 paragraphs` — total of chosen metric over the last 30 days divided by 30, rounded to nearest integer (1 decimal if < 10).

### Computation

New pure function in `core.py`:

```python
def compute_period_comparisons(history: list[dict], metric: str, today: date) -> dict
```

Takes the already-loaded `get_all_daily_stats()` rows, returns current and previous totals plus percent change for each period, and the 30-day daily average. No new SQL, no Qt imports — unit-testable like the rest of `core.py`.

## Error handling

- Empty history: comparisons all show `—`, daily avg 0, heatmap empty — same graceful-empty behavior the dialog has today.
- The existing `try/except` guards around DB calls stay.

## Testing

- **core** (`test_core.py`): `compute_period_comparisons` — normal case, zero previous period, empty history, period boundary dates (today excluded from "prior" windows).
- **UI** (`test_dialogs.py` or wherever StatsDialog tests live): metric switch updates heatmap thresholds and comparison column; `stats_metric` persists via `AppSettings`; cell click emits `day_clicked` and selects the matching daily-table row; no-op for out-of-window dates; existing StatsDialog tests updated for the new column/controls.

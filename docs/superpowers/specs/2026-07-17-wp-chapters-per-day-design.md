# WP Chapters-Per-Day Auto-Schedule — Design

Date: 2026-07-17

## Goal

When publishing a chapter whose immediate predecessor in the series is still
scheduled (`wp_status == "future"`), pre-check "Schedule for later" and
pre-fill the date/time automatically based on a new chapters-per-day setting,
so consecutive publishes stack onto the same day until it is full, then roll
to the next day.

## Settings

Two new `AppSettings` properties (with typed getters/setters, same pattern as
existing WP settings):

| Property | QSettings key | Type | Default |
|---|---|---|---|
| `wp_chapters_per_day` | `WPChaptersPerDay` | int | 1 |
| `wp_schedule_scope_global` | `WPScheduleScopeGlobal` | bool | False |

UI in `WPSettingsDialog` (`ui/dlg_wp_settings.py`):

- Spinbox "Chapters per day:" (min 1), next to the existing default
  schedule-time row.
- Checkbox "Count chapters/day across all series" (scope toggle;
  unchecked = per-series).

## Pure logic

New framework-agnostic function in `wp_publisher.py`:

```python
def compute_auto_schedule(
    prev_wp_date: str,            # predecessor's wp_date, UTC "%Y-%m-%dT%H:%M:%SZ"
    wp_dates: list[str],          # wp_dates of scope (series or global), same format
    chapters_per_day: int,
    default_time: str,            # "HH:mm" or "" (wp_default_schedule_time)
) -> datetime:                    # naive local datetime for the QDateTimeEdit
```

Rules (all date comparisons in **local time**):

1. Target date = local date of `prev_wp_date`.
2. Count entries of `wp_dates` whose local date == target date.
3. Count < `chapters_per_day` → **same date**; time = latest `wp_date` on the
   target date (within scope) + 1 hour.
4. Count ≥ `chapters_per_day` → **target date + 1 day**; time =
   `default_time` if set, else the predecessor's local time.

Notes:

- Rule 3's +1 h may roll past midnight into the next day; accepted (rare —
  requires a chapter scheduled at 23:00+).
- Chaining needs no lookahead: each publish consults only its immediate
  predecessor, so a full day naturally pushes successors forward one day at
  a time.

## Database

`db.py`:

- `get_wp_status_by_series_position` — add `wp_date` to the SELECT.
- New `get_wp_dates(series_title: str | None) -> list[str]` — `wp_date`
  values of documents with `wp_status IN ('publish', 'future')` and
  `wp_date IS NOT NULL`; filtered to the series when `series_title` given,
  all documents when `None`.

## UI wiring

In `TranslationAssistantWidget._on_publish_wp` (`ui/main_widget.py`, in the
existing `prev_scheduled` branch):

- When `prev_scheduled` and the predecessor row has a `wp_date`:
  - `schedule_cb.setChecked(True)` (enables the `QDateTimeEdit` via the
    existing toggle connection).
  - Set the `QDateTimeEdit` to `compute_auto_schedule(...)`, scope chosen by
    `wp_schedule_scope_global`.
- User can still edit the datetime or uncheck the box; nothing is forced.
- When `prev_scheduled` but predecessor has no `wp_date`: pre-check the box,
  keep the current default pre-fill.
- Predecessor not scheduled: behavior unchanged.

## Testing

- `compute_auto_schedule` unit tests (no Qt): same-day join, overflow to next
  day, default-time fallback, empty `wp_dates`, latest-slot stagger,
  boundary count == setting.
- DB test for `get_wp_dates` (per-series filter and global).
- Settings round-trip tests for the two new properties.
- Dialog test: `prev_scheduled` with `wp_date` pre-checks the box and
  pre-fills the computed datetime.

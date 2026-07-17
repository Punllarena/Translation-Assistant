# WP Chapters-Per-Day Auto-Schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the previous chapter in a series is still scheduled, pre-check "Schedule for later" in the WP publish dialog and auto-fill the date based on a chapters-per-day setting — same day while capacity remains, next day when full.

**Architecture:** Pure scheduling function in `wp_publisher.py` (no Qt), two new `AppSettings` properties, one new `Database` query plus one extended query, thin wiring in the existing publish confirm dialog. Spec: `docs/superpowers/specs/2026-07-17-wp-chapters-per-day-design.md`.

**Tech Stack:** Python 3, PySide6, SQLite (via `db.py` only), pytest.

## Global Constraints

- Activate venv before any command: `source .venv/bin/activate`.
- `wp_publisher.py` must stay Qt-free.
- All SQLite access via `Database` class in `db.py`; never import `sqlite3` elsewhere.
- All QSettings access via `AppSettings` properties.
- `wp_date` values are UTC strings, format `%Y-%m-%dT%H:%M:%SZ`; "same day" comparisons happen in local time (tests inject `tz=timezone.utc` for determinism).
- Setting keys/defaults, verbatim from spec: `WPChaptersPerDay` int default 1; `WPScheduleScopeGlobal` bool default False.

---

### Task 1: Settings properties

**Files:**
- Modify: `translation_assistant/settings.py` (after `wp_default_schedule_time` setter, ~line 219)
- Test: `tests/test_settings.py` (append after `test_wp_default_schedule_time_roundtrip`, ~line 204)

**Interfaces:**
- Produces: `AppSettings.wp_chapters_per_day: int` (default 1), `AppSettings.wp_schedule_scope_global: bool` (default False). Tasks 4 and 5 read these.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
def test_wp_chapters_per_day_default(tmp_settings):
    assert tmp_settings.wp_chapters_per_day == 1


def test_wp_chapters_per_day_roundtrip(tmp_settings):
    tmp_settings.wp_chapters_per_day = 3
    assert tmp_settings.wp_chapters_per_day == 3


def test_wp_schedule_scope_global_default(tmp_settings):
    assert tmp_settings.wp_schedule_scope_global is False


def test_wp_schedule_scope_global_roundtrip(tmp_settings):
    tmp_settings.wp_schedule_scope_global = True
    assert tmp_settings.wp_schedule_scope_global is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings.py -q -k "chapters_per_day or scope_global"`
Expected: 4 FAIL with `AttributeError: 'AppSettings' object has no attribute ...`

- [ ] **Step 3: Implement properties**

In `translation_assistant/settings.py`, insert after the `wp_default_schedule_time` setter (line 219), before the `wp_attribution_enabled` property:

```python
    @property
    def wp_chapters_per_day(self) -> int:
        return self._qs.value("WPChaptersPerDay", 1, type=int)

    @wp_chapters_per_day.setter
    def wp_chapters_per_day(self, value: int) -> None:
        self._qs.setValue("WPChaptersPerDay", value)

    @property
    def wp_schedule_scope_global(self) -> bool:
        return self._qs.value("WPScheduleScopeGlobal", False, type=bool)

    @wp_schedule_scope_global.setter
    def wp_schedule_scope_global(self, value: bool) -> None:
        self._qs.setValue("WPScheduleScopeGlobal", value)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/settings.py tests/test_settings.py
git commit -m "feat(settings): wp_chapters_per_day and wp_schedule_scope_global"
```

---

### Task 2: Database queries

**Files:**
- Modify: `translation_assistant/db.py:486-494` (`get_wp_status_by_series_position`), new method after it
- Test: `tests/test_db.py` (WP status section, ~line 1090; also update `test_get_wp_status_by_series_position_found` at line 1082)

**Interfaces:**
- Consumes: existing `create_document`, `set_document_wp_status(doc_id, status, post_url, date=None)`.
- Produces: `get_wp_status_by_series_position(series_title, series_order) -> dict | None` now includes key `wp_date`; new `get_wp_dates(series_title: str | None = None) -> list[str]` returning `wp_date` of documents with `wp_status IN ('publish','future') AND wp_date IS NOT NULL`, filtered to series unless `None`. Task 5 calls both.

- [ ] **Step 1: Write the failing tests**

In `tests/test_db.py`, update the existing test at line 1082 (SELECT gains `wp_date`):

```python
def test_get_wp_status_by_series_position_found(db):
    doc_id = db.create_document("Ch 1", series_title="MySeries", series_order=1)
    db.set_document_wp_status(doc_id, "future", "https://ex.com/ch1/")
    result = db.get_wp_status_by_series_position("MySeries", 1)
    assert result == {"wp_status": "future", "wp_post_url": "https://ex.com/ch1/", "wp_date": None}
```

Append after `test_get_wp_status_by_series_position_not_found`:

```python
def test_get_wp_status_by_series_position_includes_wp_date(db):
    doc_id = db.create_document("Ch 1", series_title="MySeries", series_order=1)
    db.set_document_wp_status(doc_id, "future", None, "2026-07-20T12:00:00Z")
    result = db.get_wp_status_by_series_position("MySeries", 1)
    assert result["wp_date"] == "2026-07-20T12:00:00Z"


def test_get_wp_dates_per_series(db):
    a = db.create_document("Ch 1", series_title="A", series_order=1)
    b = db.create_document("Ch 1", series_title="B", series_order=1)
    c = db.create_document("Ch 2", series_title="A", series_order=2)
    d = db.create_document("Ch 3", series_title="A", series_order=3)
    db.set_document_wp_status(a, "publish", None, "2026-07-20T10:00:00Z")
    db.set_document_wp_status(b, "future", None, "2026-07-20T11:00:00Z")
    db.set_document_wp_status(c, "future", None, "2026-07-21T10:00:00Z")
    db.set_document_wp_status(d, "draft", None, "2026-07-22T10:00:00Z")
    assert sorted(db.get_wp_dates("A")) == ["2026-07-20T10:00:00Z", "2026-07-21T10:00:00Z"]


def test_get_wp_dates_global(db):
    a = db.create_document("Ch 1", series_title="A", series_order=1)
    b = db.create_document("Ch 1", series_title="B", series_order=1)
    db.set_document_wp_status(a, "publish", None, "2026-07-20T10:00:00Z")
    db.set_document_wp_status(b, "future", None, "2026-07-20T11:00:00Z")
    assert sorted(db.get_wp_dates(None)) == ["2026-07-20T10:00:00Z", "2026-07-20T11:00:00Z"]


def test_get_wp_dates_skips_null_dates(db):
    a = db.create_document("Ch 1", series_title="A", series_order=1)
    db.set_document_wp_status(a, "publish", None, None)
    assert db.get_wp_dates("A") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -q -k "wp_dates or series_position"`
Expected: `get_wp_dates` tests FAIL with `AttributeError`; `..._found` FAILS on missing `wp_date` key; `..._includes_wp_date` FAILS with `KeyError`.

- [ ] **Step 3: Implement**

In `translation_assistant/db.py`, change `get_wp_status_by_series_position` (line 486) SELECT:

```python
    def get_wp_status_by_series_position(
        self, series_title: str, series_order: int
    ) -> dict | None:
        row = self._conn.execute(
            "SELECT wp_status, wp_post_url, wp_date FROM documents "
            "WHERE series_title = ? AND series_order = ?",
            (series_title, series_order),
        ).fetchone()
        return dict(row) if row else None
```

Add new method directly after it:

```python
    def get_wp_dates(self, series_title: str | None = None) -> list[str]:
        """wp_date of published/scheduled documents; all series when None."""
        sql = (
            "SELECT wp_date FROM documents "
            "WHERE wp_status IN ('publish', 'future') AND wp_date IS NOT NULL"
        )
        params: tuple = ()
        if series_title is not None:
            sql += " AND series_title = ?"
            params = (series_title,)
        return [r[0] for r in self._conn.execute(sql, params).fetchall()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): get_wp_dates query; wp_date in series-position status"
```

---

### Task 3: compute_auto_schedule pure function

**Files:**
- Modify: `translation_assistant/wp_publisher.py` (after `compute_password_fields`, ~line 77)
- Test: `tests/test_wp_publisher.py` (append)

**Interfaces:**
- Produces:

```python
compute_auto_schedule(
    prev_wp_date: str,          # predecessor wp_date, UTC "%Y-%m-%dT%H:%M:%SZ"
    wp_dates: list[str],        # scope's wp_dates, same format (from Database.get_wp_dates)
    chapters_per_day: int,
    default_time: str,          # "HH:mm" or "" (AppSettings.wp_default_schedule_time)
    tz: tzinfo | None = None,   # None = system local; tests pass timezone.utc
) -> datetime                   # naive, in tz — feed to QDateTime()
```

Raises `ValueError` if `prev_wp_date` is malformed (from `strptime`). Task 5 calls it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_publisher.py`:

```python
# ---------------------------------------------------------------------------
# compute_auto_schedule
# ---------------------------------------------------------------------------
from datetime import datetime, timezone

from translation_assistant.wp_publisher import compute_auto_schedule

UTC = timezone.utc


def test_auto_schedule_joins_same_day_when_capacity_left():
    dt = compute_auto_schedule(
        "2026-07-20T12:00:00Z", ["2026-07-20T12:00:00Z"], 2, "20:00", tz=UTC
    )
    assert dt == datetime(2026, 7, 20, 13, 0)


def test_auto_schedule_staggers_from_latest_same_day_slot():
    dt = compute_auto_schedule(
        "2026-07-20T12:00:00Z",
        ["2026-07-20T12:00:00Z", "2026-07-20T15:00:00Z"],
        3, "20:00", tz=UTC,
    )
    assert dt == datetime(2026, 7, 20, 16, 0)


def test_auto_schedule_overflows_to_next_day_at_default_time():
    dt = compute_auto_schedule(
        "2026-07-20T12:00:00Z",
        ["2026-07-20T10:00:00Z", "2026-07-20T12:00:00Z"],
        2, "20:00", tz=UTC,
    )
    assert dt == datetime(2026, 7, 21, 20, 0)


def test_auto_schedule_overflow_falls_back_to_prev_time_without_default():
    dt = compute_auto_schedule(
        "2026-07-20T12:30:00Z", ["2026-07-20T12:30:00Z"], 1, "", tz=UTC
    )
    assert dt == datetime(2026, 7, 21, 12, 30)


def test_auto_schedule_bad_default_time_falls_back_to_prev_time():
    dt = compute_auto_schedule(
        "2026-07-20T12:30:00Z", ["2026-07-20T12:30:00Z"], 1, "bogus", tz=UTC
    )
    assert dt == datetime(2026, 7, 21, 12, 30)


def test_auto_schedule_empty_dates_uses_prev_plus_hour():
    dt = compute_auto_schedule("2026-07-20T12:00:00Z", [], 1, "20:00", tz=UTC)
    assert dt == datetime(2026, 7, 20, 13, 0)


def test_auto_schedule_ignores_other_days_in_count():
    dt = compute_auto_schedule(
        "2026-07-20T12:00:00Z",
        ["2026-07-19T12:00:00Z", "2026-07-20T12:00:00Z", "2026-07-21T12:00:00Z"],
        2, "20:00", tz=UTC,
    )
    assert dt == datetime(2026, 7, 20, 13, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wp_publisher.py -q -k auto_schedule`
Expected: collection error / FAIL with `ImportError: cannot import name 'compute_auto_schedule'`

- [ ] **Step 3: Implement**

In `translation_assistant/wp_publisher.py`, extend the imports at the top (file currently has no `datetime` import):

```python
from datetime import datetime, time, timedelta, timezone, tzinfo
```

Insert after `compute_password_fields` (line 77):

```python
_WP_DATE_FMT = "%Y-%m-%dT%H:%M:%SZ"


def compute_auto_schedule(
    prev_wp_date: str,
    wp_dates: list[str],
    chapters_per_day: int,
    default_time: str,
    tz: tzinfo | None = None,
) -> datetime:
    """Pick the schedule slot for the next chapter after a scheduled one.

    Dates are UTC strings in WP format; "same day" is judged in ``tz``
    (system local when None).  Returns a naive datetime in ``tz``: while the
    predecessor's day holds fewer than ``chapters_per_day`` entries of
    ``wp_dates``, one hour after that day's latest slot; otherwise the next
    day at ``default_time`` (falling back to the predecessor's time).
    """
    def to_local(s: str) -> datetime:
        return (
            datetime.strptime(s, _WP_DATE_FMT)
            .replace(tzinfo=timezone.utc)
            .astimezone(tz)
        )

    prev_local = to_local(prev_wp_date)
    target = prev_local.date()
    same_day = [d for d in map(to_local, wp_dates) if d.date() == target]
    if len(same_day) < chapters_per_day:
        latest = max(same_day, default=prev_local)
        return (latest + timedelta(hours=1)).replace(
            tzinfo=None, second=0, microsecond=0
        )
    next_day = target + timedelta(days=1)
    if default_time:
        try:
            h, m = map(int, default_time.split(":"))
            return datetime.combine(next_day, time(h, m))
        except ValueError:
            pass
    return datetime.combine(
        next_day, prev_local.time().replace(second=0, microsecond=0)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wp_publisher.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/wp_publisher.py tests/test_wp_publisher.py
git commit -m "feat(wp): compute_auto_schedule for chapters-per-day stacking"
```

---

### Task 4: WP Settings dialog controls

**Files:**
- Modify: `translation_assistant/ui/dlg_wp_settings.py` (`_setup_ui` after schedule-time row line 72; `_on_save` line 85)
- Test: `tests/test_dialogs.py` (append to WPSettingsDialog section, after line ~870)

**Interfaces:**
- Consumes: Task 1's `wp_chapters_per_day`, `wp_schedule_scope_global`.
- Produces: dialog widgets `self._chapters_spin` (QSpinBox), `self._scope_global_cb` (QCheckBox); `_on_save` persists both.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dialogs.py` (WPSettingsDialog section):

```python
def test_wp_settings_dialog_saves_chapters_per_day_and_scope(qapp, tmp_settings):
    from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog
    dlg = WPSettingsDialog(tmp_settings)
    dlg._chapters_spin.setValue(3)
    dlg._scope_global_cb.setChecked(True)
    dlg._on_save()
    assert tmp_settings.wp_chapters_per_day == 3
    assert tmp_settings.wp_schedule_scope_global is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dialogs.py -q -k chapters_per_day`
Expected: FAIL with `AttributeError: 'WPSettingsDialog' object has no attribute '_chapters_spin'`

- [ ] **Step 3: Implement**

In `_setup_ui`, after `form.addRow("Time:", self._schedule_time_edit)` (line 72):

```python
        self._chapters_spin = QSpinBox()
        self._chapters_spin.setRange(1, 99)
        self._chapters_spin.setValue(self._settings.wp_chapters_per_day)
        form.addRow("Chapters per day:", self._chapters_spin)

        self._scope_global_cb = QCheckBox("Count chapters/day across all series")
        self._scope_global_cb.setChecked(self._settings.wp_schedule_scope_global)
        form.addRow("", self._scope_global_cb)
```

In `_on_save`, after the `wp_default_schedule_time` if/else (line 94), before `self.accept()`:

```python
        self._settings.wp_chapters_per_day = self._chapters_spin.value()
        self._settings.wp_schedule_scope_global = self._scope_global_cb.isChecked()
```

(`QSpinBox`, `QCheckBox` already imported at top of file.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dialogs.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/dlg_wp_settings.py tests/test_dialogs.py
git commit -m "feat(ui): chapters-per-day and scope controls in WP settings"
```

---

### Task 5: Publish-dialog wiring + docs

**Files:**
- Modify: `translation_assistant/ui/main_widget.py` (`_on_publish_wp`: import line 1271, `prev_status` init line 1288, insert after `_cl.addWidget(dte)` line 1380)
- Modify: `CLAUDE.md` (test count line)

No new automated test: the confirm dialog is built inline and `exec()`ed inside `_on_publish_wp`; all decision logic is covered by Tasks 1–3. Verification is the full suite plus code review of the wiring.

**Interfaces:**
- Consumes: `compute_auto_schedule` (Task 3), `Database.get_wp_dates` / `wp_date` key (Task 2), settings (Task 1).

- [ ] **Step 1: Extend import**

Line 1271, change:

```python
        from translation_assistant.wp_publisher import build_payload, WPPublishError
```

to:

```python
        from translation_assistant.wp_publisher import (
            build_payload, compute_auto_schedule, WPPublishError,
        )
```

- [ ] **Step 2: Initialize prev_status**

Line 1288, change:

```python
        prev_scheduled = False
```

to:

```python
        prev_status = None
        prev_scheduled = False
```

(Without this, `prev_status` is unbound when `series_order == 0`.)

- [ ] **Step 3: Pre-check and pre-fill**

Insert after `_cl.addWidget(dte)` (line 1380), before the existing `if prev_scheduled:` button-box block:

```python
        if prev_scheduled:
            schedule_cb.setChecked(True)
            _prev_date = prev_status.get("wp_date") if prev_status else None
            if _prev_date:
                _scope_series = (
                    None if self._settings.wp_schedule_scope_global else series_title
                )
                try:
                    _auto = compute_auto_schedule(
                        _prev_date,
                        self._db.get_wp_dates(_scope_series),
                        self._settings.wp_chapters_per_day,
                        self._settings.wp_default_schedule_time,
                    )
                    dte.setDateTime(QDateTime(_auto))
                except ValueError:
                    pass  # malformed stored wp_date — keep the default pre-fill
```

(`QDateTime` is already imported in this method, line 1334; PySide6 `QDateTime` accepts a Python `datetime`.)

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: all PASS. Note the total collected count.

- [ ] **Step 5: Update CLAUDE.md test count**

In `CLAUDE.md`, Testing section, replace `Total: 902 tests.` with the actual new total from Step 4 (expected 902 + 16 = 918, but use the real number).

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/main_widget.py CLAUDE.md
git commit -m "feat(wp): auto-schedule next chapter when predecessor is scheduled"
```

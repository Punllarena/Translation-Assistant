# Stats Dialog Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dialog-wide metric switch, heatmap polish (month/weekday labels, legend, click-to-select), and trend info (per-period ±% column + daily average) to the Usage Statistics dialog.

**Architecture:** A new pure function `compute_period_comparisons` in `core.py` does all trend math from the already-loaded daily history (no new SQL). `HeatmapWidget` becomes metric-aware and gains label margins plus a `day_clicked` signal. `StatsDialog` gains a `QComboBox` metric switch persisted via a new `AppSettings.stats_metric` property, a "vs prev" summary column, and a daily-average line.

**Tech Stack:** PySide6, sqlite3 (existing), pytest.

**Spec:** `docs/superpowers/specs/2026-07-03-stats-dialog-improvements-design.md`

## Global Constraints

- Activate venv before any command: `source .venv/bin/activate`
- `core.py` must stay Qt-free (plain Python types only).
- Never write to `QSettings` directly — always via `AppSettings`.
- Metric keys are exactly `"paragraphs" | "chars" | "en_words"` (match `get_all_daily_stats()` row keys). Default `"paragraphs"`.
- Percent format: `f"{pct:+.0f}%"` (e.g. `+23%`, `-8%`); `—` when previous period total is 0 or period is all-time.
- Streaks (current/longest) remain paragraph-based; only best-day, heatmap, vs-prev, and daily-avg follow the chosen metric.

---

### Task 1: `compute_period_comparisons` in core.py

**Files:**
- Modify: `translation_assistant/core.py` (append after `compute_streaks`, ~line 637)
- Test: `tests/test_core.py` (append at end)

**Interfaces:**
- Consumes: nothing new; history rows are dicts shaped like `Database.get_all_daily_stats()` output: `{"date": "YYYY-MM-DD", "paragraphs": int, "chars": int, "en_words": int}`.
- Produces: `compute_period_comparisons(history: list[dict], metric: str, today: date) -> dict` returning:
  ```python
  {
      "periods": {
          "today": {"current": int, "previous": int, "pct_change": float | None},
          "week":  {"current": int, "previous": int, "pct_change": float | None},
          "month": {"current": int, "previous": int, "pct_change": float | None},
      },
      "daily_avg_30": float,
  }
  ```
  `pct_change` is `None` when the previous period total is 0. Periods: today (1 day) vs yesterday; week = last 7 days (today inclusive) vs the 7 days before that; month = last 30 days vs the 30 before that. `daily_avg_30` = last-30-day total / 30.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_core.py` (it already imports from `translation_assistant.core` — add `compute_period_comparisons` to whatever import style the file uses; check its head, it may use `from translation_assistant.core import ...` or module import):

```python
# ---------------------------------------------------------------------------
# compute_period_comparisons
# ---------------------------------------------------------------------------

def _row(iso, paras=0, chars=0, en=0):
    return {"date": iso, "paragraphs": paras, "chars": chars, "en_words": en}


def test_period_comparisons_today_vs_yesterday():
    today = date(2026, 7, 3)
    history = [_row("2026-07-03", paras=10), _row("2026-07-02", paras=5)]
    result = compute_period_comparisons(history, "paragraphs", today)
    t = result["periods"]["today"]
    assert t["current"] == 10
    assert t["previous"] == 5
    assert t["pct_change"] == 100.0


def test_period_comparisons_week_boundary():
    today = date(2026, 7, 3)
    # 2026-06-27 is day 7 back -> inside current week; 2026-06-26 is day 8 -> previous week
    history = [_row("2026-06-27", paras=3), _row("2026-06-26", paras=7)]
    result = compute_period_comparisons(history, "paragraphs", today)
    w = result["periods"]["week"]
    assert w["current"] == 3
    assert w["previous"] == 7


def test_period_comparisons_zero_previous_gives_none():
    today = date(2026, 7, 3)
    history = [_row("2026-07-03", paras=10)]
    result = compute_period_comparisons(history, "paragraphs", today)
    assert result["periods"]["today"]["pct_change"] is None


def test_period_comparisons_negative_change():
    today = date(2026, 7, 3)
    history = [_row("2026-07-03", paras=4), _row("2026-07-02", paras=8)]
    result = compute_period_comparisons(history, "paragraphs", today)
    assert result["periods"]["today"]["pct_change"] == -50.0


def test_period_comparisons_empty_history():
    result = compute_period_comparisons([], "paragraphs", date(2026, 7, 3))
    for key in ("today", "week", "month"):
        p = result["periods"][key]
        assert p["current"] == 0
        assert p["previous"] == 0
        assert p["pct_change"] is None
    assert result["daily_avg_30"] == 0


def test_period_comparisons_respects_metric():
    today = date(2026, 7, 3)
    history = [_row("2026-07-03", paras=1, chars=500), _row("2026-07-02", paras=1, chars=100)]
    result = compute_period_comparisons(history, "chars", today)
    assert result["periods"]["today"]["current"] == 500
    assert result["periods"]["today"]["pct_change"] == 400.0


def test_period_comparisons_daily_avg_30():
    today = date(2026, 7, 3)
    # 60 paras within last 30 days, plus old data that must not count
    history = [_row("2026-07-01", paras=45), _row("2026-06-10", paras=15),
               _row("2026-01-01", paras=999)]
    result = compute_period_comparisons(history, "paragraphs", today)
    assert result["daily_avg_30"] == 2.0  # 60 / 30
```

If `test_core.py` imports names explicitly, add `compute_period_comparisons` and `date` imports as needed (`from datetime import date` may already exist).

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_core.py -k period_comparisons -q`
Expected: FAIL / ERROR with `ImportError` or `NameError: compute_period_comparisons`

- [ ] **Step 3: Implement**

Append to `translation_assistant/core.py` after `compute_streaks` (file already imports `date` and `timedelta` from `datetime`):

```python
def compute_period_comparisons(history: list[dict], metric: str, today: date) -> dict:
    """
    Compare current vs previous periods for one metric from daily stats history.

    Args:
        history: rows shaped like Database.get_all_daily_stats() output —
                 dicts with "date" (ISO string) and per-metric int values.
        metric: "paragraphs" | "chars" | "en_words".
        today: reference date for period windows.

    Returns:
        dict with:
        - periods: {"today"|"week"|"month": {"current", "previous", "pct_change"}}
          where pct_change is a float percentage or None if previous == 0.
          today = 1-day window vs yesterday; week = last 7 days vs prior 7;
          month = last 30 days vs prior 30 (all windows include their end day).
        - daily_avg_30: float, last-30-day total divided by 30.
    """
    by_date = {date.fromisoformat(r["date"]): r.get(metric, 0) for r in history}

    def _total(start: date, end: date) -> int:
        return sum(v for d, v in by_date.items() if start <= d <= end)

    periods = {}
    for key, days in (("today", 1), ("week", 7), ("month", 30)):
        cur_start = today - timedelta(days=days - 1)
        current = _total(cur_start, today)
        prev_end = cur_start - timedelta(days=1)
        previous = _total(prev_end - timedelta(days=days - 1), prev_end)
        pct = None if previous == 0 else (current - previous) / previous * 100
        periods[key] = {"current": current, "previous": previous, "pct_change": pct}

    daily_avg_30 = _total(today - timedelta(days=29), today) / 30
    return {"periods": periods, "daily_avg_30": daily_avg_30}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core.py -k period_comparisons -q`
Expected: 7 passed

- [ ] **Step 5: Run full core suite, then commit**

Run: `pytest tests/test_core.py -q`
Expected: all pass

```bash
git add translation_assistant/core.py tests/test_core.py
git commit -m "feat(core): add compute_period_comparisons for stats trends"
```

---

### Task 2: `AppSettings.stats_metric`

**Files:**
- Modify: `translation_assistant/settings.py` (add property following the existing getter/setter pattern, e.g. after `last_doc_id`)
- Test: `tests/test_settings.py` (append)

**Interfaces:**
- Produces: `AppSettings.stats_metric` property — getter returns `str` (default `"paragraphs"`), setter stores under QSettings key `"StatsMetric"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
def test_default_stats_metric(tmp_settings):
    assert tmp_settings.stats_metric == "paragraphs"


def test_stats_metric_roundtrip(tmp_settings):
    tmp_settings.stats_metric = "chars"
    assert tmp_settings.stats_metric == "chars"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings.py -k stats_metric -q`
Expected: FAIL with `AttributeError: 'AppSettings' object has no attribute 'stats_metric'`

- [ ] **Step 3: Implement**

Add to `translation_assistant/settings.py`, following the surrounding property style (section comment included if neighbors have them):

```python
    # StatsMetric — which metric the stats dialog highlights
    @property
    def stats_metric(self) -> str:
        return self._qs.value("StatsMetric", "paragraphs")

    @stats_metric.setter
    def stats_metric(self, value: str) -> None:
        self._qs.setValue("StatsMetric", value)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/settings.py tests/test_settings.py
git commit -m "feat(settings): add stats_metric preference"
```

---

### Task 3: HeatmapWidget — metric awareness, labels, click signal

**Files:**
- Modify: `translation_assistant/ui/dlg_stats.py` (module constants + `HeatmapWidget` only; `StatsDialog` untouched in this task)
- Test: `tests/test_dialogs.py` (append to the StatsDialog section)

**Interfaces:**
- Consumes: nothing from Tasks 1–2.
- Produces (used by Task 4):
  - `HeatmapWidget(data: dict, metric: str = "paragraphs", parent=None)`
  - `HeatmapWidget.set_metric(metric: str) -> None` — recomputes thresholds, repaints
  - `HeatmapWidget.day_clicked: Signal(str)` — emits ISO date on cell click (past/today cells only)
  - Module constants `_LEFT = 30`, `_TOP = 16` (label margins), `_EMPTY_ENTRY`, `_METRIC_LABELS`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dialogs.py` in the StatsDialog section:

```python
def test_heatmap_metric_thresholds_follow_metric(qapp):
    from translation_assistant.ui.dlg_stats import HeatmapWidget
    data = {"2026-07-01": {"paragraphs": 4, "chars": 400, "en_words": 40}}
    w = HeatmapWidget(data, metric="chars")
    assert w._thresholds[4] == 400
    w.set_metric("paragraphs")
    assert w._thresholds[4] == 4


def test_heatmap_day_clicked_signal(qapp):
    from datetime import date
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from translation_assistant.ui.dlg_stats import HeatmapWidget, _LEFT, _TOP, _GAP
    w = HeatmapWidget({})
    received = []
    w.day_clicked.connect(received.append)
    # click the first cell (col 0, row 0) — 51 weeks ago Sunday, always in the past
    pos = QPointF(_LEFT + _GAP + 2, _TOP + _GAP + 2)
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mousePressEvent(event)
    assert received == [w._start.isoformat()]


def test_heatmap_click_outside_grid_no_signal(qapp):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from translation_assistant.ui.dlg_stats import HeatmapWidget
    w = HeatmapWidget({})
    received = []
    w.day_clicked.connect(received.append)
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(1.0, 1.0),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mousePressEvent(event)
    assert received == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dialogs.py -k heatmap -q`
Expected: FAIL (`TypeError: unexpected keyword argument 'metric'` / `ImportError: cannot import name '_LEFT'`)

- [ ] **Step 3: Implement**

In `translation_assistant/ui/dlg_stats.py`:

Add `Signal` to the QtCore import: `from PySide6.QtCore import Qt, Signal`.

Replace the module constants block (after `_STEP`) and the entire `HeatmapWidget` class with:

```python
_LEFT = 30   # left margin for weekday labels
_TOP = 16    # top margin for month labels

_EMPTY_ENTRY = {"paragraphs": 0, "chars": 0, "en_words": 0}
_METRIC_LABELS = {"paragraphs": "paras", "chars": "chars", "en_words": "EN words"}
```

(keep the existing `_COLORS` list)

```python
class HeatmapWidget(QWidget):
    """52-week activity heatmap, GitHub style. data keyed by ISO date string."""

    day_clicked = Signal(str)  # ISO date of the clicked cell

    def __init__(self, data: dict, metric: str = "paragraphs", parent=None):
        super().__init__(parent)
        self._data = data
        self._metric = metric
        self.setMouseTracking(True)

        today = date.today()
        days_since_sunday = (today.weekday() + 1) % 7
        this_week_sunday = today - timedelta(days=days_since_sunday)
        self._start = this_week_sunday - timedelta(weeks=51)
        self._today = today

        self._compute_thresholds()
        self.setFixedSize(_LEFT + 52 * _STEP + _GAP, _TOP + 7 * _STEP + _GAP)

    def set_metric(self, metric: str) -> None:
        self._metric = metric
        self._compute_thresholds()
        self.update()

    def _compute_thresholds(self) -> None:
        max_v = max((v[self._metric] for v in self._data.values()), default=0)
        if max_v > 0:
            q = max_v / 4
            self._thresholds = [0, q, q * 2, q * 3, max_v]
        else:
            self._thresholds = [0, 1, 2, 3, 4]

    def _cell_to_date(self, col: int, row: int) -> date:
        return self._start + timedelta(days=col * 7 + row)

    def _pos_to_cell(self, x: float, y: float) -> tuple[int, int] | None:
        if x < _LEFT + _GAP or y < _TOP + _GAP:
            return None
        col = int((x - _LEFT - _GAP) / _STEP)
        row = int((y - _TOP - _GAP) / _STEP)
        if 0 <= col < 52 and 0 <= row < 7:
            return col, row
        return None

    def _intensity(self, value: int) -> int:
        if value == 0:
            return 0
        for level in range(4, 0, -1):
            if value >= self._thresholds[level]:
                return level
        return 1

    def paintEvent(self, _event):
        painter = QPainter(self)
        font = self.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor("#767676"))

        # weekday labels — row 0 is Sunday, so Mon/Wed/Fri = rows 1/3/5
        for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
            painter.drawText(
                0, _TOP + row * _STEP + _GAP, _LEFT - 4, _CELL,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                name,
            )

        # month labels — at each week-column whose Sunday starts a new month
        prev_month = None
        for col in range(52):
            d = self._cell_to_date(col, 0)
            if prev_month is not None and d.month != prev_month:
                painter.drawText(_LEFT + col * _STEP + _GAP, _TOP - 4, d.strftime("%b"))
            prev_month = d.month

        for col in range(52):
            for row in range(7):
                d = self._cell_to_date(col, row)
                if d > self._today:
                    continue
                entry = self._data.get(d.isoformat(), _EMPTY_ENTRY)
                painter.fillRect(
                    _LEFT + col * _STEP + _GAP,
                    _TOP + row * _STEP + _GAP,
                    _CELL,
                    _CELL,
                    _COLORS[self._intensity(entry[self._metric])],
                )
        painter.end()

    def mouseMoveEvent(self, event):
        cell = self._pos_to_cell(event.position().x(), event.position().y())
        if cell is not None:
            d = self._cell_to_date(*cell)
            if d <= self._today:
                entry = self._data.get(d.isoformat(), _EMPTY_ENTRY)
                ordered = [self._metric] + [m for m in _METRIC_LABELS if m != self._metric]
                stats = " · ".join(f"{entry[m]:,} {_METRIC_LABELS[m]}" for m in ordered)
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{_fmt_date(d.isoformat())}: {stats}",
                    self,
                )
                return
        QToolTip.hideText()

    def mousePressEvent(self, event):
        cell = self._pos_to_cell(event.position().x(), event.position().y())
        if cell is not None:
            d = self._cell_to_date(*cell)
            if d <= self._today:
                self.day_clicked.emit(d.isoformat())
```

Note: `StatsDialog._build_overview_tab` still calls `HeatmapWidget(heatmap_data, widget)` positionally — the second positional is now `metric`, so update that call to `HeatmapWidget(heatmap_data, parent=widget)` in this task to keep the dialog working (full metric wiring comes in Task 4).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dialogs.py -k "heatmap or stats" -q`
Expected: all pass (new heatmap tests + the two existing stats dialog render tests)

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/dlg_stats.py tests/test_dialogs.py
git commit -m "feat(stats): heatmap metric awareness, month/weekday labels, day_clicked signal"
```

---

### Task 4: StatsDialog — metric switch, trend column, daily avg, legend, click wiring

**Files:**
- Modify: `translation_assistant/ui/dlg_stats.py` (`StatsDialog` class)
- Modify: `translation_assistant/ui/main_widget.py:1915` (call site)
- Test: `tests/test_dialogs.py` (append)

**Interfaces:**
- Consumes: `compute_period_comparisons` (Task 1), `AppSettings.stats_metric` (Task 2), `HeatmapWidget.set_metric` / `day_clicked` / `metric=` kwarg (Task 3).
- Produces: `StatsDialog(db, settings=None, parent=None)` — `settings` is an `AppSettings` or `None` (None = default metric, no persistence; keeps existing `StatsDialog(db)` test calls working).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dialogs.py` StatsDialog section:

```python
def _stats_db():
    import sqlite3
    from translation_assistant.db import Database
    conn = sqlite3.connect(":memory:")
    return Database(":memory:", _conn=conn)


def test_stats_dialog_metric_switch_updates_heatmap_and_persists(qapp, tmp_settings):
    from PySide6.QtWidgets import QComboBox
    from translation_assistant.ui.dlg_stats import StatsDialog
    dlg = StatsDialog(_stats_db(), tmp_settings)
    combo = dlg.findChild(QComboBox)
    assert combo is not None
    combo.setCurrentIndex(1)  # "Source Chars"
    assert dlg._metric == "chars"
    assert dlg._heatmap._metric == "chars"
    assert tmp_settings.stats_metric == "chars"
    dlg.close()


def test_stats_dialog_restores_saved_metric(qapp, tmp_settings):
    from translation_assistant.ui.dlg_stats import StatsDialog
    tmp_settings.stats_metric = "en_words"
    dlg = StatsDialog(_stats_db(), tmp_settings)
    assert dlg._metric == "en_words"
    assert dlg._metric_combo.currentData() == "en_words"
    dlg.close()


def test_stats_dialog_summary_has_vs_prev_column(qapp):
    from translation_assistant.ui.dlg_stats import StatsDialog
    dlg = StatsDialog(_stats_db())
    assert dlg._summary_table.columnCount() == 5
    assert dlg._summary_table.horizontalHeaderItem(4).text() == "vs prev"
    # empty db -> every comparison is em-dash
    for row in range(4):
        assert dlg._summary_table.item(row, 4).text() == "—"
    dlg.close()


def test_stats_dialog_daily_avg_label(qapp):
    from translation_assistant.ui.dlg_stats import StatsDialog
    dlg = StatsDialog(_stats_db())
    assert dlg._avg_label.text() == "Daily avg (30d): 0.0 paragraphs"
    dlg.close()


def test_stats_dialog_day_click_selects_table_row(qapp):
    from datetime import date
    from PySide6.QtCore import Qt
    from translation_assistant.ui.dlg_stats import StatsDialog
    db = _stats_db()
    doc_id = db.create_document("Ch1", series_title="S")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "hello")
    dlg = StatsDialog(db)
    today_iso = date.today().isoformat()
    dlg._on_day_clicked(today_iso)
    sel = dlg._table.selectedItems()
    assert sel and sel[0].data(Qt.ItemDataRole.UserRole) == today_iso
    dlg.close()


def test_stats_dialog_day_click_out_of_window_noop(qapp):
    from translation_assistant.ui.dlg_stats import StatsDialog
    dlg = StatsDialog(_stats_db())
    dlg._on_day_clicked("2020-01-01")  # must not raise
    assert dlg._table.selectedItems() == []
    dlg.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dialogs.py -k stats_dialog -q`
Expected: new tests FAIL (`AttributeError: _summary_table` / no QComboBox); the two pre-existing render tests still pass.

- [ ] **Step 3: Implement**

In `translation_assistant/ui/dlg_stats.py`:

Add `QComboBox` to the QtWidgets import. Add to the core import: `from translation_assistant.core import compute_period_comparisons, compute_streaks`.

Add module-level helpers after `_fmt_date`:

```python
_METRIC_CHOICES = [("Paragraphs", "paragraphs"), ("Source Chars", "chars"), ("EN Words", "en_words")]
_METRIC_UNITS = {"paragraphs": "paragraphs", "chars": "source chars", "en_words": "EN words"}


def _fmt_pct(pct: float | None) -> str:
    return "—" if pct is None else f"{pct:+.0f}%"
```

Replace `StatsDialog.__init__`:

```python
    def __init__(self, db, settings=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._settings = settings
        self._show_days = 30
        self._metric = settings.stats_metric if settings is not None else "paragraphs"
        if self._metric not in _METRIC_UNITS:
            self._metric = "paragraphs"
        self._setup_ui()
```

Rework `_build_overview_tab` — full replacement:

```python
    def _build_overview_tab(self, summary: dict) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        metric_row = QHBoxLayout()
        metric_row.addWidget(QLabel("Metric:"))
        self._metric_combo = QComboBox()
        for label, key in _METRIC_CHOICES:
            self._metric_combo.addItem(label, key)
        self._metric_combo.setCurrentIndex(
            next(i for i, (_, k) in enumerate(_METRIC_CHOICES) if k == self._metric)
        )
        self._metric_combo.currentIndexChanged.connect(self._on_metric_changed)
        metric_row.addWidget(self._metric_combo)
        metric_row.addStretch()
        layout.addLayout(metric_row)

        heatmap_data = {r["date"]: r for r in self._all_history}
        self._heatmap = HeatmapWidget(heatmap_data, metric=self._metric, parent=widget)
        self._heatmap.day_clicked.connect(self._on_day_clicked)
        layout.addWidget(self._heatmap)

        legend_row = QHBoxLayout()
        legend_row.addStretch()
        legend_row.addWidget(QLabel("Less"))
        for color in _COLORS:
            swatch = QLabel()
            swatch.setFixedSize(_CELL, _CELL)
            swatch.setStyleSheet(f"background-color: {color.name()};")
            legend_row.addWidget(swatch)
        legend_row.addWidget(QLabel("More"))
        layout.addLayout(legend_row)

        today_label = f"Today ({_fmt_date(date.today().isoformat())})"
        periods = [
            (today_label, summary["today"]),
            ("Last 7 days",  summary["week"]),
            ("Last 30 days", summary["month"]),
            ("All time",     summary["alltime"]),
        ]
        self._summary_table = QTableWidget(4, 5)
        self._summary_table.setHorizontalHeaderLabels(
            ["Period", "Paragraphs", "Source Chars", "EN Words", "vs prev"]
        )
        self._summary_table.horizontalHeader().setStretchLastSection(True)
        self._summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._summary_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._summary_table.verticalHeader().setVisible(False)
        bold_font = QFont()
        bold_font.setBold(True)
        for i, (label, data) in enumerate(periods):
            period_item = QTableWidgetItem(label)
            if i == 0:
                period_item.setFont(bold_font)
            self._summary_table.setItem(i, 0, period_item)
            self._summary_table.setItem(i, 1, QTableWidgetItem(f"{data['paragraphs']:,}"))
            self._summary_table.setItem(i, 2, QTableWidgetItem(f"{data['chars']:,}"))
            self._summary_table.setItem(i, 3, QTableWidgetItem(f"{data['en_words']:,}"))
        self._summary_table.resizeColumnsToContents()
        self._summary_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        row_h = self._summary_table.rowHeight(0) if self._summary_table.rowCount() > 0 else 22
        self._summary_table.setFixedHeight(
            self._summary_table.horizontalHeader().height() + 4 * row_h + 4
        )
        layout.addWidget(self._summary_table)

        self._streak_label = QLabel()
        layout.addWidget(self._streak_label)
        self._avg_label = QLabel()
        layout.addWidget(self._avg_label)

        toggle_row = QHBoxLayout()
        self._toggle_btn = QPushButton("Show Last 7 Days")
        self._toggle_btn.clicked.connect(self._on_toggle)
        toggle_row.addWidget(self._toggle_btn)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Date", "Paragraphs", "Source Chars", "EN Words"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        self._refresh_table()
        self._refresh_metric_views()
        return widget
```

(The old standalone streak-label block is replaced by `self._streak_label` + `_refresh_metric_views`.)

Add new methods to `StatsDialog`:

```python
    def _on_metric_changed(self, index: int) -> None:
        self._metric = self._metric_combo.itemData(index)
        if self._settings is not None:
            self._settings.stats_metric = self._metric
        self._heatmap.set_metric(self._metric)
        self._refresh_metric_views()

    def _refresh_metric_views(self) -> None:
        comp = compute_period_comparisons(self._all_history, self._metric, date.today())
        for row, key in enumerate(("today", "week", "month")):
            self._summary_table.setItem(
                row, 4, QTableWidgetItem(_fmt_pct(comp["periods"][key]["pct_change"]))
            )
        self._summary_table.setItem(3, 4, QTableWidgetItem("—"))

        streaks = compute_streaks(self._all_history)
        parts = [
            f"Current streak: {streaks['current_streak']} days",
            f"Longest streak: {streaks['longest_streak']} days",
        ]
        if self._all_history:
            best = max(self._all_history, key=lambda r: r[self._metric])
            if best[self._metric] > 0:
                parts.append(
                    f"Best day: {_fmt_date(best['date'])} "
                    f"({best[self._metric]:,} {_METRIC_UNITS[self._metric]})"
                )
        self._streak_label.setText("  ·  ".join(parts))

        avg = comp["daily_avg_30"]
        avg_str = f"{avg:.1f}" if avg < 10 else f"{avg:,.0f}"
        self._avg_label.setText(f"Daily avg (30d): {avg_str} {_METRIC_UNITS[self._metric]}")

    def _on_day_clicked(self, iso: str) -> None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == iso:
                self._table.selectRow(row)
                self._table.scrollToItem(item)
                return
```

In `_refresh_table`, store the ISO date on the date item:

```python
            date_item = QTableWidgetItem(_fmt_date(row["date"]))
            date_item.setData(Qt.ItemDataRole.UserRole, row["date"])
            self._table.setItem(i, 0, date_item)
```

(replacing the current `self._table.setItem(i, 0, QTableWidgetItem(_fmt_date(row["date"])))` line).

Update the call site in `translation_assistant/ui/main_widget.py` (`_on_stats`, ~line 1915):

```python
            StatsDialog(self._db, self._settings, self).exec()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dialogs.py -k "stats or heatmap" -q`
Expected: all pass

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: all pass (535 + new)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/dlg_stats.py translation_assistant/ui/main_widget.py tests/test_dialogs.py
git commit -m "feat(stats): metric switch, vs-prev trend column, daily avg, legend, heatmap click-to-select"
```

---

### Task 5: Manual smoke check

**Files:** none (verification only)

- [ ] **Step 1: Launch app, open Usage Statistics**

Run: `source .venv/bin/activate && python -m translation_assistant.main`

Verify:
- Month labels along heatmap top, Mon/Wed/Fri at left, Less→More legend below.
- Metric combo switches heatmap colors, best-day, vs-prev column, daily avg — and choice survives closing/reopening the dialog.
- Clicking a recent heatmap cell selects that date's row in the daily table; clicking an old cell does nothing.
- "vs prev" shows sensible percentages with real data.

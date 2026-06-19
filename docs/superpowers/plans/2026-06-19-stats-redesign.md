# Stats Dialog Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the stats dialog with English word counts, multi-period summary, per-series breakdown, streak tracking, friendly date formatting, and removal of the ¶ symbol.

**Architecture:** Three-task sequence — DB layer first (new/updated queries), then pure-Python streak logic in `core.py`, then dialog rewrite in `dlg_stats.py`. Dialog consumes both; nothing touches the dialog until the data layer is complete and tested.

**Tech Stack:** PySide6, SQLite (via existing `Database` class), pytest, Python 3.10+

## Global Constraints

- `%-d` in `strftime` (non-zero-padded day) is Linux-only — acceptable, app is Linux-only per CLAUDE.md
- All SQLite access goes through `db.py`; never import `sqlite3` elsewhere
- Tests use `Database(":memory:", _conn=conn)` with `sqlite3.connect(":memory:")` — no disk I/O
- `core.py` has no Qt imports — keep `compute_streaks` Qt-free
- Run tests with `source .venv/bin/activate && pytest` before committing

---

## Task 1: Update DB stats methods

**Files:**
- Modify: `translation_assistant/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `Database.get_today_stats() -> dict` — keys: `paragraphs`, `chars`, `en_words`
  - `Database.get_daily_stats(days) -> list[dict]` — each dict: `date`, `paragraphs`, `chars`, `en_words`
  - `Database.get_all_daily_stats() -> list[dict]` — same shape, no day filter, ordered `date ASC`
  - `Database.get_summary_stats() -> dict` — keys: `today`, `week`, `month`, `alltime`, each a `{"paragraphs", "chars", "en_words"}` dict
  - `Database.get_series_stats() -> list[dict]` — keys: `series`, `paragraphs`, `chars`, `en_words`, `chapters`; ordered `paragraphs DESC`

- [ ] **Step 1: Write failing tests for updated `get_today_stats` (adds `en_words`)**

In `tests/test_db.py`, update the three existing stats tests and add one new one. Replace the entire "Usage statistics" section (lines starting at `# Usage statistics`) with:

```python
# ---------------------------------------------------------------------------
# Usage statistics
# ---------------------------------------------------------------------------

def test_stats_empty(db):
    stats = db.get_today_stats()
    assert stats == {"paragraphs": 0, "chars": 0, "en_words": 0}


def test_stats_accumulate(db):
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "こんにちは", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "さようなら", "translated_text": ""},
        {"line_number": 2, "prefix": "%", "raw_text": "ありがとう", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "Hello")
    db.save_translation(doc_id, 1, "Goodbye")
    db.save_translation(doc_id, 2, "Thank you")
    stats = db.get_today_stats()
    assert stats["paragraphs"] == 3
    assert stats["chars"] == 15       # 5 chars each
    assert stats["en_words"] == 4     # "Hello"(1) + "Goodbye"(1) + "Thank you"(2)


def test_stats_cleared(db):
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "こんにちは", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "さようなら", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "Hello")
    db.save_translation(doc_id, 1, "Goodbye")
    db.save_translation(doc_id, 1, "")  # clear
    stats = db.get_today_stats()
    assert stats["paragraphs"] == 1
    assert stats["chars"] == 5       # only "こんにちは"
    assert stats["en_words"] == 1    # only "Hello"


def test_daily_stats_multi_day(db):
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "い", "translated_text": ""},
        {"line_number": 2, "prefix": "%", "raw_text": "う", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "a b")
    db._conn.execute(
        "UPDATE lines SET translated_at = '2026-06-01 10:00:00' "
        "WHERE document_id = ? AND line_number = 0", (doc_id,),
    )
    db.save_translation(doc_id, 1, "i")
    db._conn.execute(
        "UPDATE lines SET translated_at = '2026-06-01 11:00:00' "
        "WHERE document_id = ? AND line_number = 1", (doc_id,),
    )
    db.save_translation(doc_id, 2, "u v w")
    db._conn.execute(
        "UPDATE lines SET translated_at = '2026-06-02 10:00:00' "
        "WHERE document_id = ? AND line_number = 2", (doc_id,),
    )
    db._conn.commit()
    rows = db.get_daily_stats(days=365)
    by_date = {r["date"]: r for r in rows}
    assert by_date["2026-06-01"]["paragraphs"] == 2
    assert by_date["2026-06-01"]["chars"] == 2      # "あ"(1) + "い"(1)
    assert by_date["2026-06-01"]["en_words"] == 3   # "a b"(2) + "i"(1)
    assert by_date["2026-06-02"]["paragraphs"] == 1
    assert by_date["2026-06-02"]["chars"] == 1      # "う"(1)
    assert by_date["2026-06-02"]["en_words"] == 3   # "u v w"(3)


def test_get_all_daily_stats_ordered_asc(db):
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "い", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "a")
    db._conn.execute(
        "UPDATE lines SET translated_at = '2026-06-02 10:00:00' "
        "WHERE document_id = ? AND line_number = 0", (doc_id,),
    )
    db.save_translation(doc_id, 1, "i")
    db._conn.execute(
        "UPDATE lines SET translated_at = '2026-06-01 10:00:00' "
        "WHERE document_id = ? AND line_number = 1", (doc_id,),
    )
    db._conn.commit()
    rows = db.get_all_daily_stats()
    assert rows[0]["date"] == "2026-06-01"
    assert rows[1]["date"] == "2026-06-02"


def test_get_summary_stats_alltime(db):
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "い", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "hello world")
    db.save_translation(doc_id, 1, "bye")
    summary = db.get_summary_stats()
    assert summary["alltime"]["paragraphs"] == 2
    assert summary["alltime"]["en_words"] == 3   # "hello world"(2) + "bye"(1)
    assert set(summary.keys()) == {"today", "week", "month", "alltime"}
    for key in ("today", "week", "month", "alltime"):
        assert set(summary[key].keys()) == {"paragraphs", "chars", "en_words"}


def test_get_series_stats(db):
    doc1 = db.create_document("Ch1", series_title="Isekai")
    doc2 = db.create_document("Ch2", series_title="Isekai")
    doc3 = db.create_document("StandAlone")  # no series — excluded
    db.save_lines(doc1, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
    ])
    db.save_lines(doc2, [
        {"line_number": 0, "prefix": "%", "raw_text": "い", "translated_text": ""},
    ])
    db.save_lines(doc3, [
        {"line_number": 0, "prefix": "%", "raw_text": "う", "translated_text": ""},
    ])
    db.save_translation(doc1, 0, "hello world")
    db.save_translation(doc2, 0, "bye")
    db.save_translation(doc3, 0, "ignored")
    rows = db.get_series_stats()
    assert len(rows) == 1
    assert rows[0]["series"] == "Isekai"
    assert rows[0]["paragraphs"] == 2
    assert rows[0]["en_words"] == 3    # "hello world"(2) + "bye"(1)
    assert rows[0]["chapters"] == 2    # doc1 and doc2


def test_get_series_stats_sorted_by_paragraphs_desc(db):
    doc_a = db.create_document("A1", series_title="AAA")
    doc_b = db.create_document("B1", series_title="BBB")
    db.save_lines(doc_a, [
        {"line_number": 0, "prefix": "%", "raw_text": "x", "translated_text": ""},
    ])
    db.save_lines(doc_b, [
        {"line_number": 0, "prefix": "%", "raw_text": "y", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "z", "translated_text": ""},
    ])
    db.save_translation(doc_a, 0, "one")
    db.save_translation(doc_b, 0, "two")
    db.save_translation(doc_b, 1, "three")
    rows = db.get_series_stats()
    assert rows[0]["series"] == "BBB"   # 2 paragraphs > 1
    assert rows[1]["series"] == "AAA"


def test_save_lines_preserves_translated_at(db):
    """Ctrl+S / autosave must not wipe translated_at timestamps."""
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "a")
    current_lines = db.get_lines(doc_id)
    db.save_lines(doc_id, current_lines)
    stats = db.get_today_stats()
    assert stats["paragraphs"] == 1
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
source .venv/bin/activate && pytest tests/test_db.py -k "stats" -v 2>&1 | tail -30
```

Expected: several FAILED (old tests expect no `en_words` key; new tests call non-existent methods).

- [ ] **Step 3: Add `_EN_WORDS` SQL constant and update `get_today_stats` in `db.py`**

At the top of `db.py`, after imports, add the module-level constant:

```python
_EN_WORDS = (
    "COALESCE(SUM(CASE WHEN TRIM(translated_text) != '' "
    "THEN LENGTH(TRIM(translated_text)) - LENGTH(REPLACE(TRIM(translated_text), ' ', '')) + 1 "
    "ELSE 0 END), 0)"
)
```

Replace `get_today_stats`:

```python
def get_today_stats(self) -> dict:
    row = self._conn.execute(
        f"SELECT COUNT(*) AS paragraphs, "
        f"COALESCE(SUM(LENGTH(raw_text)), 0) AS chars, "
        f"{_EN_WORDS} AS en_words "
        f"FROM lines "
        f"WHERE translated_at IS NOT NULL AND date(translated_at) = date('now')"
    ).fetchone()
    return {"paragraphs": row[0], "chars": row[1], "en_words": row[2]}
```

- [ ] **Step 4: Update `get_daily_stats` in `db.py`**

Replace `get_daily_stats`:

```python
def get_daily_stats(self, days: int = 30) -> list[dict]:
    rows = self._conn.execute(
        f"SELECT date(translated_at) AS date, "
        f"COUNT(*) AS paragraphs, "
        f"COALESCE(SUM(LENGTH(raw_text)), 0) AS chars, "
        f"{_EN_WORDS} AS en_words "
        f"FROM lines "
        f"WHERE translated_at IS NOT NULL "
        f"AND date(translated_at) >= date('now', ? || ' days') "
        f"GROUP BY date(translated_at) "
        f"ORDER BY date DESC",
        (f"-{days}",),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: Add `get_all_daily_stats`, `get_summary_stats`, `get_series_stats` to `db.py`**

After `get_daily_stats`, add:

```python
def get_all_daily_stats(self) -> list[dict]:
    rows = self._conn.execute(
        f"SELECT date(translated_at) AS date, "
        f"COUNT(*) AS paragraphs, "
        f"COALESCE(SUM(LENGTH(raw_text)), 0) AS chars, "
        f"{_EN_WORDS} AS en_words "
        f"FROM lines "
        f"WHERE translated_at IS NOT NULL "
        f"GROUP BY date(translated_at) "
        f"ORDER BY date ASC"
    ).fetchall()
    return [dict(r) for r in rows]

def get_summary_stats(self) -> dict:
    def _q(where: str) -> dict:
        row = self._conn.execute(
            f"SELECT COUNT(*) AS paragraphs, "
            f"COALESCE(SUM(LENGTH(raw_text)), 0) AS chars, "
            f"{_EN_WORDS} AS en_words "
            f"FROM lines WHERE translated_at IS NOT NULL {where}"
        ).fetchone()
        return {"paragraphs": row[0], "chars": row[1], "en_words": row[2]}

    return {
        "today":   _q("AND date(translated_at) = date('now')"),
        "week":    _q("AND date(translated_at) >= date('now', '-7 days')"),
        "month":   _q("AND date(translated_at) >= date('now', '-30 days')"),
        "alltime": _q(""),
    }

def get_series_stats(self) -> list[dict]:
    rows = self._conn.execute(
        f"SELECT d.series_title AS series, "
        f"COUNT(l.id) AS paragraphs, "
        f"COALESCE(SUM(LENGTH(l.raw_text)), 0) AS chars, "
        f"COALESCE(SUM(CASE WHEN TRIM(l.translated_text) != '' "
        f"THEN LENGTH(TRIM(l.translated_text)) - LENGTH(REPLACE(TRIM(l.translated_text), ' ', '')) + 1 "
        f"ELSE 0 END), 0) AS en_words, "
        f"COUNT(DISTINCT l.document_id) AS chapters "
        f"FROM lines l "
        f"JOIN documents d ON d.id = l.document_id "
        f"WHERE l.translated_at IS NOT NULL AND d.series_title != '' "
        f"GROUP BY d.series_title "
        f"ORDER BY paragraphs DESC"
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 6: Run stats tests to verify all pass**

```bash
source .venv/bin/activate && pytest tests/test_db.py -k "stats" -v 2>&1 | tail -30
```

Expected: all PASSED.

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
source .venv/bin/activate && pytest -q 2>&1 | tail -10
```

Expected: all passing (same count as before plus new tests).

- [ ] **Step 8: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add en_words to stats queries; add summary, series, all-history methods"
```

---

## Task 2: Add `compute_streaks` to `core.py`

**Files:**
- Modify: `translation_assistant/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `list[dict]` with keys `"date"` (ISO string `"YYYY-MM-DD"`) and `"paragraphs"` (int) — same shape as `Database.get_all_daily_stats()`
- Produces: `compute_streaks(history: list[dict]) -> dict` with keys:
  - `current_streak: int`
  - `longest_streak: int`
  - `best_day_date: str` (ISO string, empty if no data)
  - `best_day_paras: int`

- [ ] **Step 1: Write failing tests for `compute_streaks`**

In `tests/test_core.py`, add at the end:

```python
# ---------------------------------------------------------------------------
# compute_streaks
# ---------------------------------------------------------------------------
from datetime import date, timedelta
from translation_assistant.core import compute_streaks


def _h(*entries):
    """Build history list from (iso_date, paragraphs) pairs."""
    return [{"date": d, "paragraphs": p} for d, p in entries]


def _today():
    return date.today().isoformat()


def _days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def test_compute_streaks_empty():
    result = compute_streaks([])
    assert result == {"current_streak": 0, "longest_streak": 0, "best_day_date": "", "best_day_paras": 0}


def test_compute_streaks_single_day_today():
    today = _today()
    result = compute_streaks(_h((today, 5)))
    assert result["current_streak"] == 1
    assert result["longest_streak"] == 1
    assert result["best_day_date"] == today
    assert result["best_day_paras"] == 5


def test_compute_streaks_consecutive_days():
    history = _h(
        (_days_ago(2), 3),
        (_days_ago(1), 5),
        (_today(), 2),
    )
    result = compute_streaks(history)
    assert result["current_streak"] == 3
    assert result["longest_streak"] == 3
    assert result["best_day_paras"] == 5


def test_compute_streaks_gap_breaks_current():
    # days_ago(3), days_ago(2) consecutive; days_ago(1) missing; today present
    history = _h(
        (_days_ago(3), 4),
        (_days_ago(2), 4),
        (_today(), 2),
    )
    result = compute_streaks(history)
    assert result["current_streak"] == 1   # gap on days_ago(1)
    assert result["longest_streak"] == 2   # days_ago(3)+days_ago(2)


def test_compute_streaks_today_no_entry_yesterday_yes():
    history = _h((_days_ago(1), 5))
    result = compute_streaks(history)
    assert result["current_streak"] == 1   # yesterday counts when today absent


def test_compute_streaks_longest_not_current():
    # 3-day run long ago, gap, single day today
    history = _h(
        (_days_ago(18), 10),
        (_days_ago(17), 10),
        (_days_ago(16), 10),
        (_today(), 1),
    )
    result = compute_streaks(history)
    assert result["longest_streak"] == 3
    assert result["current_streak"] == 1   # gap between days_ago(16) and today
    assert result["best_day_paras"] == 10
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
source .venv/bin/activate && pytest tests/test_core.py -k "streak" -v 2>&1 | tail -20
```

Expected: FAILED with `ImportError` or `AttributeError` (function doesn't exist yet).

- [ ] **Step 3: Add `compute_streaks` to `core.py`**

At the end of `translation_assistant/core.py`, add:

```python
def compute_streaks(history: list[dict]) -> dict:
    from datetime import date, timedelta
    active_set = {r["date"] for r in history if r["paragraphs"] > 0}
    active = sorted(active_set)

    if not active:
        return {"current_streak": 0, "longest_streak": 0, "best_day_date": "", "best_day_paras": 0}

    longest = 1
    run = 1
    for i in range(1, len(active)):
        prev = date.fromisoformat(active[i - 1])
        curr = date.fromisoformat(active[i])
        if (curr - prev).days == 1:
            run += 1
            if run > longest:
                longest = run
        else:
            run = 1

    today = date.today()
    check = today if today.isoformat() in active_set else today - timedelta(days=1)
    current = 0
    while check.isoformat() in active_set:
        current += 1
        check -= timedelta(days=1)

    best = max(history, key=lambda r: r["paragraphs"])
    return {
        "current_streak": current,
        "longest_streak": longest,
        "best_day_date": best["date"],
        "best_day_paras": best["paragraphs"],
    }
```

- [ ] **Step 4: Run streak tests**

```bash
source .venv/bin/activate && pytest tests/test_core.py -k "streak" -v 2>&1 | tail -20
```

Expected: all PASSED.

- [ ] **Step 5: Run full suite**

```bash
source .venv/bin/activate && pytest -q 2>&1 | tail -10
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/core.py tests/test_core.py
git commit -m "feat(core): add compute_streaks for current/longest streak and best day"
```

---

## Task 3: Rewrite `dlg_stats.py`

**Files:**
- Modify: `translation_assistant/ui/dlg_stats.py`
- Test: `tests/test_dialogs.py` (smoke test — existing pattern)

**Interfaces:**
- Consumes:
  - `Database.get_all_daily_stats() -> list[dict]` (keys: `date`, `paragraphs`, `chars`, `en_words`)
  - `Database.get_summary_stats() -> dict` (keys: `today`, `week`, `month`, `alltime`)
  - `Database.get_series_stats() -> list[dict]` (keys: `series`, `paragraphs`, `chars`, `en_words`, `chapters`)
  - `compute_streaks(history: list[dict]) -> dict` (keys: `current_streak`, `longest_streak`, `best_day_date`, `best_day_paras`)

- [ ] **Step 1: Write smoke test for new `StatsDialog`**

In `tests/test_dialogs.py`, add:

```python
def test_stats_dialog_renders(qapp):
    import sqlite3
    from translation_assistant.db import Database
    from translation_assistant.ui.dlg_stats import StatsDialog
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    dlg = StatsDialog(db)
    assert dlg.windowTitle() == "Usage Statistics"
    dlg.close()


def test_stats_dialog_renders_with_data(qapp):
    import sqlite3
    from translation_assistant.db import Database
    from translation_assistant.ui.dlg_stats import StatsDialog
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    doc_id = db.create_document("Ch1", series_title="Isekai")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "hello world")
    dlg = StatsDialog(db)
    assert dlg.windowTitle() == "Usage Statistics"
    dlg.close()
```

- [ ] **Step 2: Run smoke tests to confirm failure**

```bash
source .venv/bin/activate && pytest tests/test_dialogs.py -k "stats_dialog" -v 2>&1 | tail -20
```

Expected: FAILED (old dialog structure, missing methods called).

- [ ] **Step 3: Replace `dlg_stats.py` entirely**

Write the full file:

```python
"""
Usage statistics dialog — heatmap + summary + per-series breakdown.
"""
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget,
    QToolTip, QVBoxLayout, QWidget,
)

from translation_assistant.core import compute_streaks

_CELL = 13
_GAP = 2
_STEP = _CELL + _GAP

_COLORS = [
    QColor("#ebedf0"),
    QColor("#9be9a8"),
    QColor("#40c463"),
    QColor("#30a14e"),
    QColor("#216e39"),
]


def _fmt_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%B %-d, %Y")


class HeatmapWidget(QWidget):
    """52-week activity heatmap, GitHub style. data keyed by ISO date string."""

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self.setMouseTracking(True)

        today = date.today()
        days_since_sunday = (today.weekday() + 1) % 7
        this_week_sunday = today - timedelta(days=days_since_sunday)
        self._start = this_week_sunday - timedelta(weeks=51)
        self._today = today

        max_p = max((v["paragraphs"] for v in data.values()), default=0)
        if max_p > 0:
            q = max_p / 4
            self._thresholds = [0, q, q * 2, q * 3, max_p]
        else:
            self._thresholds = [0, 1, 2, 3, 4]

        self.setFixedSize(52 * _STEP + _GAP, 7 * _STEP + _GAP)

    def _cell_to_date(self, col: int, row: int) -> date:
        return self._start + timedelta(days=col * 7 + row)

    def _intensity(self, paragraphs: int) -> int:
        if paragraphs == 0:
            return 0
        for level in range(4, 0, -1):
            if paragraphs >= self._thresholds[level]:
                return level
        return 1

    def paintEvent(self, _event):
        painter = QPainter(self)
        for col in range(52):
            for row in range(7):
                d = self._cell_to_date(col, row)
                if d > self._today:
                    continue
                entry = self._data.get(d.isoformat(), {"paragraphs": 0, "chars": 0})
                painter.fillRect(
                    col * _STEP + _GAP,
                    row * _STEP + _GAP,
                    _CELL,
                    _CELL,
                    _COLORS[self._intensity(entry["paragraphs"])],
                )
        painter.end()

    def mouseMoveEvent(self, event):
        col = int((event.position().x() - _GAP) / _STEP)
        row = int((event.position().y() - _GAP) / _STEP)
        if 0 <= col < 52 and 0 <= row < 7:
            d = self._cell_to_date(col, row)
            if d <= self._today:
                entry = self._data.get(d.isoformat(), {"paragraphs": 0, "chars": 0})
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{_fmt_date(d.isoformat())}: {entry['paragraphs']} paras / {entry['chars']:,} chars",
                    self,
                )
                return
        QToolTip.hideText()


class StatsDialog(QDialog):
    """Shows a 52-week heatmap + multi-period summary + per-series breakdown."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self._show_days = 30
        self._all_history: list[dict] = []
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Usage Statistics")
        self.setMinimumWidth(620)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        try:
            self._all_history = self._db.get_all_daily_stats()
        except Exception:
            self._all_history = []

        try:
            summary = self._db.get_summary_stats()
        except Exception:
            _empty = {"paragraphs": 0, "chars": 0, "en_words": 0}
            summary = {"today": _empty, "week": _empty, "month": _empty, "alltime": _empty}

        try:
            series_data = self._db.get_series_stats()
        except Exception:
            series_data = []

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        tabs = QTabWidget()
        tabs.addTab(self._build_overview_tab(summary), "Overview")
        tabs.addTab(self._build_series_tab(series_data), "By Series")
        layout.addWidget(tabs)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

    def _build_overview_tab(self, summary: dict) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        heatmap_data = {r["date"]: r for r in self._all_history}
        layout.addWidget(HeatmapWidget(heatmap_data, widget))

        today_label = f"Today ({date.today().strftime('%B %-d, %Y')})"
        periods = [
            (today_label, summary["today"]),
            ("Last 7 days",  summary["week"]),
            ("Last 30 days", summary["month"]),
            ("All time",     summary["alltime"]),
        ]
        summary_table = QTableWidget(4, 4)
        summary_table.setHorizontalHeaderLabels(["Period", "Paragraphs", "Source Chars", "EN Words"])
        summary_table.horizontalHeader().setStretchLastSection(True)
        summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        summary_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        summary_table.verticalHeader().setVisible(False)
        bold_font = QFont()
        bold_font.setBold(True)
        for i, (label, data) in enumerate(periods):
            period_item = QTableWidgetItem(label)
            if i == 0:
                period_item.setFont(bold_font)
            summary_table.setItem(i, 0, period_item)
            summary_table.setItem(i, 1, QTableWidgetItem(f"{data['paragraphs']:,}"))
            summary_table.setItem(i, 2, QTableWidgetItem(f"{data['chars']:,}"))
            summary_table.setItem(i, 3, QTableWidgetItem(f"{data['en_words']:,}"))
        summary_table.resizeColumnsToContents()
        row_h = summary_table.rowHeight(0) if summary_table.rowCount() > 0 else 22
        summary_table.setFixedHeight(
            summary_table.horizontalHeader().height() + 4 * row_h + 4
        )
        layout.addWidget(summary_table)

        streaks = compute_streaks(self._all_history)
        parts = [
            f"Current streak: {streaks['current_streak']} days",
            f"Longest streak: {streaks['longest_streak']} days",
        ]
        if streaks["best_day_date"]:
            parts.append(
                f"Best day: {_fmt_date(streaks['best_day_date'])} ({streaks['best_day_paras']:,} paras)"
            )
        layout.addWidget(QLabel("  ·  ".join(parts)))

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
        layout.addWidget(self._table)

        self._refresh_table()
        return widget

    def _build_series_tab(self, series_data: list) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        if not series_data:
            layout.addWidget(
                QLabel("No series data yet."),
                alignment=Qt.AlignmentFlag.AlignCenter,
            )
            return widget

        table = QTableWidget(len(series_data), 5)
        table.setHorizontalHeaderLabels(["Series", "Paragraphs", "Source Chars", "EN Words", "Chapters"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        for i, row in enumerate(series_data):
            table.setItem(i, 0, QTableWidgetItem(row["series"]))
            table.setItem(i, 1, QTableWidgetItem(f"{row['paragraphs']:,}"))
            table.setItem(i, 2, QTableWidgetItem(f"{row['chars']:,}"))
            table.setItem(i, 3, QTableWidgetItem(f"{row['en_words']:,}"))
            table.setItem(i, 4, QTableWidgetItem(str(row["chapters"])))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        return widget

    def _on_toggle(self):
        if self._show_days == 30:
            self._show_days = 7
            self._toggle_btn.setText("Show Last 30 Days")
        else:
            self._show_days = 30
            self._toggle_btn.setText("Show Last 7 Days")
        self._refresh_table()

    def _refresh_table(self):
        cutoff = (date.today() - timedelta(days=self._show_days)).isoformat()
        rows = sorted(
            [r for r in self._all_history if r["date"] >= cutoff],
            key=lambda r: r["date"],
            reverse=True,
        )
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(_fmt_date(row["date"])))
            self._table.setItem(i, 1, QTableWidgetItem(f"{row['paragraphs']:,}"))
            self._table.setItem(i, 2, QTableWidgetItem(f"{row['chars']:,}"))
            self._table.setItem(i, 3, QTableWidgetItem(f"{row['en_words']:,}"))
```

- [ ] **Step 4: Run smoke tests**

```bash
source .venv/bin/activate && pytest tests/test_dialogs.py -k "stats_dialog" -v 2>&1 | tail -20
```

Expected: both PASSED.

- [ ] **Step 5: Run full suite**

```bash
source .venv/bin/activate && pytest -q 2>&1 | tail -10
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/dlg_stats.py tests/test_dialogs.py
git commit -m "feat(ui): redesign stats dialog with tabs, EN words, streaks, series breakdown"
```

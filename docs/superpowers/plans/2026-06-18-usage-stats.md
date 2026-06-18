# Usage Statistics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track paragraphs and source characters translated per day, display a GitHub-style heatmap and daily table inside a stats dialog, with a status bar label showing today's totals.

**Architecture:** Add `translated_at TEXT DEFAULT NULL` to `lines` via idempotent migration; update `save_translation` to stamp it; expose two query methods. Wire a clickable status bar label and a `Help → Statistics` menu item that open `StatsDialog` (heatmap + table). No new dependency — pure PySide6 + stdlib.

**Tech Stack:** Python 3.11+, PySide6, SQLite (already in use), pytest

## Global Constraints

- All DB access through `Database` class in `translation_assistant/db.py` — no raw sqlite3 elsewhere
- In-memory DB via `_conn` injection seam in tests (see existing `test_db.py` pattern)
- No new pip dependencies
- Run `pytest` from repo root with `.venv` activated (`source .venv/bin/activate`)
- All file paths relative to repo root: `/home/pun/workspace/TranslationAssistant-PySide6-Port/`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `translation_assistant/db.py` | Modify | Migration + `save_translation` update + 2 new query methods |
| `tests/test_db.py` | Modify | 4 new stats tests |
| `translation_assistant/ui/dlg_stats.py` | Create | `HeatmapWidget` + `StatsDialog` |
| `translation_assistant/ui/main_window.py` | Modify | Clickable status bar label + Help menu + refresh hook |

---

## Task 1: DB layer — migration, save_translation, query methods, tests

**Files:**
- Modify: `translation_assistant/db.py`
- Modify: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `Database.get_today_stats() -> dict` — `{"paragraphs": int, "chars": int}`
  - `Database.get_daily_stats(days: int = 30) -> list[dict]` — `[{"date": "YYYY-MM-DD", "paragraphs": int, "chars": int}, ...]`, newest first
  - `Database.save_translation(doc_id, line_number, text)` — now stamps `translated_at`
  - `Database.save_lines(doc_id, lines)` — preserves existing `translated_at` across bulk-save (⚠️ autosave calls this; without the fix, Ctrl+S wipes all timestamps)

---

- [ ] **Step 1: Write the 4 failing tests**

Append to `tests/test_db.py`:

```python
# ---------------------------------------------------------------------------
# Usage statistics
# ---------------------------------------------------------------------------

def test_stats_empty(db):
    stats = db.get_today_stats()
    assert stats == {"paragraphs": 0, "chars": 0}


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
    assert stats["chars"] == 15  # 5 chars each


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
    assert stats["chars"] == 5  # only "こんにちは"


def test_daily_stats_multi_day(db):
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "い", "translated_text": ""},
        {"line_number": 2, "prefix": "%", "raw_text": "う", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "a")
    db._conn.execute(
        "UPDATE lines SET translated_at = '2026-06-01 10:00:00' "
        "WHERE document_id = ? AND line_number = 0",
        (doc_id,),
    )
    db.save_translation(doc_id, 1, "i")
    db._conn.execute(
        "UPDATE lines SET translated_at = '2026-06-01 11:00:00' "
        "WHERE document_id = ? AND line_number = 1",
        (doc_id,),
    )
    db.save_translation(doc_id, 2, "u")
    db._conn.execute(
        "UPDATE lines SET translated_at = '2026-06-02 10:00:00' "
        "WHERE document_id = ? AND line_number = 2",
        (doc_id,),
    )
    db._conn.commit()
    rows = db.get_daily_stats(days=365)
    by_date = {r["date"]: r for r in rows}
    assert by_date["2026-06-01"]["paragraphs"] == 2
    assert by_date["2026-06-01"]["chars"] == 2   # "あ" + "い"
    assert by_date["2026-06-02"]["paragraphs"] == 1
    assert by_date["2026-06-02"]["chars"] == 1   # "う"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_db.py::test_stats_empty tests/test_db.py::test_stats_accumulate tests/test_db.py::test_stats_cleared tests/test_db.py::test_daily_stats_multi_day -v
```

Expected: 4 FAILs — `Database` has no `get_today_stats` or `get_daily_stats`.

- [ ] **Step 3: Add idempotent migration for `translated_at`**

In `translation_assistant/db.py`, inside `_apply_schema()`, append after the existing `source_url` migration block (after line 115, before `def close`):

```python
        # Idempotent column migration for translated_at on lines
        lines_existing = {r[1] for r in self._conn.execute("PRAGMA table_info(lines)").fetchall()}
        if "translated_at" not in lines_existing:
            self._conn.execute(
                "ALTER TABLE lines ADD COLUMN translated_at TEXT DEFAULT NULL"
            )
        self._conn.commit()
```

- [ ] **Step 3b: Add test to verify `save_lines` preserves timestamps (failing)**

Append to the stats tests block in `tests/test_db.py`:

```python
def test_save_lines_preserves_translated_at(db):
    """Ctrl+S / autosave must not wipe translated_at timestamps."""
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "a")
    # simulate autosave: re-save all lines
    current_lines = db.get_lines(doc_id)
    db.save_lines(doc_id, current_lines)
    stats = db.get_today_stats()
    assert stats["paragraphs"] == 1  # timestamp must survive the bulk-save
```

Run to confirm it fails:

```bash
source .venv/bin/activate && pytest tests/test_db.py::test_save_lines_preserves_translated_at -v
```

Expected: FAIL — `assert 1 == 1` → actually `stats["paragraphs"]` is 0 because `translated_at` was wiped.

- [ ] **Step 3c: Fix `save_lines` to preserve `translated_at`**

Replace the `save_lines` method in `translation_assistant/db.py`:

```python
    def save_lines(self, doc_id: int, lines: list[dict]) -> None:
        # Read existing translated_at before deleting — autosave must not wipe them
        existing_ts = {
            r[0]: r[1]
            for r in self._conn.execute(
                "SELECT line_number, translated_at FROM lines WHERE document_id = ?", (doc_id,)
            ).fetchall()
        }
        with self._conn:
            self._conn.execute("DELETE FROM lines WHERE document_id = ?", (doc_id,))
            self._conn.executemany(
                "INSERT INTO lines "
                "(document_id, line_number, prefix, raw_text, translated_text, translated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        doc_id,
                        ln["line_number"],
                        ln["prefix"],
                        ln["raw_text"],
                        ln.get("translated_text", ""),
                        existing_ts.get(ln["line_number"]),
                    )
                    for ln in lines
                ],
            )
            self._conn.execute(
                "UPDATE documents SET updated_at = datetime('now') WHERE id = ?", (doc_id,)
            )
```

Run to confirm the new test passes:

```bash
source .venv/bin/activate && pytest tests/test_db.py::test_save_lines_preserves_translated_at -v
```

Expected: PASS.

- [ ] **Step 4: Update `save_translation` to stamp `translated_at`**

Replace the existing `save_translation` method (around line 425):

```python
    def save_translation(self, doc_id: int, line_number: int, text: str) -> None:
        self._conn.execute(
            "UPDATE lines SET translated_text = ?, "
            "translated_at = CASE WHEN ? != '' THEN datetime('now') ELSE NULL END "
            "WHERE document_id = ? AND line_number = ?",
            (text, text, doc_id, line_number),
        )
        self._conn.commit()
```

- [ ] **Step 5: Add `get_today_stats` and `get_daily_stats` methods**

Append before the `find_tm_matches` method (around line 433):

```python
    def get_today_stats(self) -> dict:
        row = self._conn.execute(
            "SELECT COUNT(*) AS paragraphs, COALESCE(SUM(LENGTH(raw_text)), 0) AS chars "
            "FROM lines "
            "WHERE translated_at IS NOT NULL AND date(translated_at) = date('now')"
        ).fetchone()
        return {"paragraphs": row[0], "chars": row[1]}

    def get_daily_stats(self, days: int = 30) -> list[dict]:
        rows = self._conn.execute(
            "SELECT date(translated_at) AS date, "
            "COUNT(*) AS paragraphs, "
            "COALESCE(SUM(LENGTH(raw_text)), 0) AS chars "
            "FROM lines "
            "WHERE translated_at IS NOT NULL "
            "AND date(translated_at) >= date('now', ? || ' days') "
            "GROUP BY date(translated_at) "
            "ORDER BY date DESC",
            (f"-{days}",),
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_db.py::test_stats_empty tests/test_db.py::test_stats_accumulate tests/test_db.py::test_stats_cleared tests/test_db.py::test_daily_stats_multi_day -v
```

Expected: 4 PASSes.

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all existing tests still pass.

- [ ] **Step 8: Run all original stats tests together**

```bash
source .venv/bin/activate && pytest tests/test_db.py::test_stats_empty tests/test_db.py::test_stats_accumulate tests/test_db.py::test_stats_cleared tests/test_db.py::test_daily_stats_multi_day tests/test_db.py::test_save_lines_preserves_translated_at -v
```

Expected: 5 PASSes.

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(stats): add translated_at column and daily stats query methods"
```

---

## Task 2: Stats dialog — HeatmapWidget + StatsDialog

**Files:**
- Create: `translation_assistant/ui/dlg_stats.py`

**Interfaces:**
- Consumes: `Database.get_today_stats() -> dict`, `Database.get_daily_stats(days=365) -> list[dict]`
- Produces: `StatsDialog(db, parent=None)` — a `QDialog` subclass, call `.exec()` to show

---

- [ ] **Step 1: Create `translation_assistant/ui/dlg_stats.py`**

```python
"""
Usage statistics dialog — heatmap + daily table.
"""
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

_CELL = 13
_GAP = 2
_STEP = _CELL + _GAP

_COLORS = [
    QColor("#ebedf0"),  # level 0 — no activity
    QColor("#9be9a8"),  # level 1
    QColor("#40c463"),  # level 2
    QColor("#30a14e"),  # level 3
    QColor("#216e39"),  # level 4
]


class HeatmapWidget(QWidget):
    """52-week activity heatmap, GitHub style. data keyed by ISO date string."""

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data  # {"YYYY-MM-DD": {"paragraphs": int, "chars": int}}
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
                    f"{d.isoformat()}: {entry['paragraphs']} ¶ / {entry['chars']:,} chars",
                    self,
                )
                return
        QToolTip.hideText()


class StatsDialog(QDialog):
    """Shows a 52-week heatmap + per-day table of translation activity."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self._show_days = 30
        self._all_history: list[dict] = []
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Usage Statistics")
        self.setMinimumWidth(500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Load data
        try:
            today = self._db.get_today_stats()
        except Exception:
            today = {"paragraphs": 0, "chars": 0}

        try:
            self._all_history = self._db.get_daily_stats(days=365)
        except Exception:
            self._all_history = []

        # Heatmap
        heatmap_data = {r["date"]: r for r in self._all_history}
        layout.addWidget(HeatmapWidget(heatmap_data, self))

        # Today summary
        bold_font = QFont()
        bold_font.setBold(True)
        today_label = QLabel(
            f"Today: {today['paragraphs']} paragraphs · {today['chars']:,} source chars"
        )
        today_label.setFont(bold_font)
        layout.addWidget(today_label)

        # Toggle button
        toggle_row = QHBoxLayout()
        self._toggle_btn = QPushButton("Show Last 7 Days")
        self._toggle_btn.clicked.connect(self._on_toggle)
        toggle_row.addWidget(self._toggle_btn)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        # Table
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Date", "Paragraphs", "Source Chars"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self._table)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._refresh_table()

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
        rows = [r for r in self._all_history if r["date"] >= cutoff]
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(row["date"]))
            self._table.setItem(i, 1, QTableWidgetItem(str(row["paragraphs"])))
            self._table.setItem(i, 2, QTableWidgetItem(f"{row['chars']:,}"))
```

- [ ] **Step 2: Verify the file is importable**

```bash
source .venv/bin/activate && python -c "from translation_assistant.ui.dlg_stats import StatsDialog; print('OK')"
```

Expected output: `OK`

- [ ] **Step 3: Run full test suite (no regressions from new file)**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add translation_assistant/ui/dlg_stats.py
git commit -m "feat(stats): add HeatmapWidget and StatsDialog"
```

---

## Task 3: MainWindow wiring — status bar label, Help menu, refresh hook

**Files:**
- Modify: `translation_assistant/ui/main_window.py`

**Interfaces:**
- Consumes: `StatsDialog(db, parent)` from `translation_assistant.ui.dlg_stats`
- Consumes: `Database.get_today_stats() -> dict`
- Produces: status bar label showing today's totals; clicking it or using Help → Statistics opens `StatsDialog`

---

- [ ] **Step 1: Add `_ClickableLabel` class to `main_window.py`**

After the `ReviewTextEdit` class (around line 87), insert:

```python
class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)
```

- [ ] **Step 2: Add stats label to `_setup_statusbar`**

Current `_setup_statusbar` (line 302):
```python
    def _setup_statusbar(self) -> None:
        sb = self.statusBar()
        self._completion_label = QLabel("0% Complete")
        self._line_label = QLabel("Line: xxxx/xxxx")
        self._word_label = QLabel("xxxx Words")
        self._filesaved_label = QLabel("")
        sb.addWidget(self._completion_label)
        sb.addWidget(self._line_label)
        sb.addWidget(self._word_label)
        sb.addPermanentWidget(self._filesaved_label)
        self._update_progress_visibility()
```

Replace with:
```python
    def _setup_statusbar(self) -> None:
        sb = self.statusBar()
        self._completion_label = QLabel("0% Complete")
        self._line_label = QLabel("Line: xxxx/xxxx")
        self._word_label = QLabel("xxxx Words")
        self._filesaved_label = QLabel("")
        self._stats_label = _ClickableLabel("")
        self._stats_label.clicked.connect(self._on_stats)
        sb.addWidget(self._completion_label)
        sb.addWidget(self._line_label)
        sb.addWidget(self._word_label)
        sb.addPermanentWidget(self._stats_label)
        sb.addPermanentWidget(self._filesaved_label)
        self._update_progress_visibility()
```

- [ ] **Step 3: Add `Help → Statistics` menu item to `_setup_menubar`**

In `_setup_menubar`, find the standalone About action at the end (around line 231):
```python
        # About
        mb.addAction("About").triggered.connect(self._on_about)
```

Replace with:
```python
        # Help
        help_menu = mb.addMenu("Help")
        help_menu.addAction("Statistics…").triggered.connect(self._on_stats)
        help_menu.addSeparator()
        help_menu.addAction("About").triggered.connect(self._on_about)
```

- [ ] **Step 4: Add `_update_stats_label` and `_on_stats` methods**

Append before `closeEvent` (around line 1154):

```python
    def _update_stats_label(self) -> None:
        try:
            stats = self._db.get_today_stats()
            self._stats_label.setText(
                f"Today: {stats['paragraphs']} ¶ / {stats['chars']:,} chars"
            )
            self._stats_label.setVisible(True)
        except Exception:
            self._stats_label.setVisible(False)

    def _on_stats(self) -> None:
        from translation_assistant.ui.dlg_stats import StatsDialog
        with self._topmost_suspended():
            StatsDialog(self._db, self).exec()
```

- [ ] **Step 5: Call `_update_stats_label` after each paragraph save**

In `_save_current_translation` (around line 548), update to:
```python
    def _save_current_translation(self) -> None:
        if not self._raw_lines:
            return
        text = self._translated_line.toPlainText()
        self._translated_lines[self._array_pointer] = text
        if self._doc_id is not None:
            self._db.save_translation(self._doc_id, self._array_pointer, text)
            self._update_stats_label()
```

- [ ] **Step 6: Call `_update_stats_label` on document load**

In `_finish_load` (around line 433), append `self._update_stats_label()` as the last line before the method ends:

After the line `self._restart_autosave_timer()` (around line 480), append:
```python
        self._update_stats_label()
```

- [ ] **Step 7: Run full test suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all tests pass.

- [ ] **Step 8: Smoke-test the UI manually**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

1. Open or create a document
2. Verify status bar shows `Today: N ¶ / N chars`
3. Translate a paragraph (press Enter to advance) — verify count increments
4. Click the stats label — verify dialog opens with heatmap + table
5. Click `Help → Statistics` — same dialog opens
6. Toggle `Last 7 Days` / `Last 30 Days` — table updates

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/main_window.py
git commit -m "feat(stats): wire status bar label, Help menu, and refresh hook"
```

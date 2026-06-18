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

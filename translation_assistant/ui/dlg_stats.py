"""
Usage statistics dialog — heatmap + summary + per-series breakdown.
"""
from datetime import date, timedelta

from PySide6.QtCore import Qt, Signal
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
_LEFT = 30   # left margin for weekday labels
_TOP = 16    # top margin for month labels

_EMPTY_ENTRY = {"paragraphs": 0, "chars": 0, "en_words": 0}
_METRIC_LABELS = {"paragraphs": "paras", "chars": "chars", "en_words": "EN words"}

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


class StatsDialog(QDialog):
    """Shows a 52-week heatmap + multi-period summary + per-series breakdown."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self._show_days = 30
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
        layout.addWidget(HeatmapWidget(heatmap_data, parent=widget))

        today_label = f"Today ({_fmt_date(date.today().isoformat())})"
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
        summary_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
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
        cutoff = (date.today() - timedelta(days=self._show_days - 1)).isoformat()
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

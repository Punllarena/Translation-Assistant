"""
Series Manager dialog — view all series, set syosetu URL, open chapter fetcher.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QInputDialog, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from translation_assistant.db import Database


class SeriesManagerDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._setup_ui()
        self._load()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Manage Series")
        self.setMinimumSize(700, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Series Title", "Syosetu URL", "Chapters", "Profile"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.currentCellChanged.connect(lambda row, *_: self._on_row_changed(row))
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._set_url_btn = QPushButton("Set URL…")
        self._set_url_btn.setEnabled(False)
        self._set_url_btn.clicked.connect(self._on_set_url)
        self._fetch_btn = QPushButton("Fetch new chapters…")
        self._fetch_btn.setEnabled(False)
        self._fetch_btn.clicked.connect(self._on_fetch)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._set_url_btn)
        btn_row.addWidget(self._fetch_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _load(self) -> None:
        series = self._db.get_series_list_full()
        self._table.setRowCount(len(series))
        for row, s in enumerate(series):
            self._table.setItem(row, 0, QTableWidgetItem(s["title"]))
            self._table.setItem(row, 1, QTableWidgetItem(s["url"]))
            self._table.setItem(row, 2, QTableWidgetItem(str(s["chapter_count"])))
            self._table.setItem(row, 3, QTableWidgetItem(s["profile_name"]))
        self._on_row_changed(self._table.currentRow())

    def _current_series(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        return {
            "title": self._table.item(row, 0).text(),
            "url": self._table.item(row, 1).text(),
        }

    def _on_row_changed(self, row: int) -> None:
        s = self._current_series()
        self._set_url_btn.setEnabled(s is not None)
        self._fetch_btn.setEnabled(s is not None and bool(s["url"]))

    def _on_set_url(self) -> None:
        s = self._current_series()
        if s is None:
            return
        url, ok = QInputDialog.getText(
            self,
            "Set Series URL",
            f"Syosetu URL for \"{s['title']}\":",
            text=s["url"],
        )
        if not ok:
            return
        self._db.set_series_url(s["title"], url.strip())
        self._load()

    def _on_fetch(self) -> None:
        s = self._current_series()
        if s is None or not s["url"]:
            return
        from translation_assistant.ui.dlg_fetch_series import FetchSeriesDialog
        dlg = FetchSeriesDialog(self._db, s["title"], s["url"], parent=self)
        dlg.exec()
        self._load()

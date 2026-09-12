"""Find & Replace across all translated lines in a series."""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from translation_assistant.db import Database


class FindReplaceDialog(QDialog):
    def __init__(
        self,
        db: Database,
        series_title: str,
        on_replaced: Callable[[int], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._series_title = series_title
        self._on_replaced = on_replaced
        self._matches: list[dict] = []
        self.setWindowTitle(f"Find & Replace in Series — {series_title}")
        self.setMinimumSize(640, 420)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        find_row = QHBoxLayout()
        find_row.addWidget(QLabel("Find:"))
        self._find_edit = QLineEdit()
        self._find_edit.returnPressed.connect(self._on_search)
        find_row.addWidget(self._find_edit)
        layout.addLayout(find_row)

        replace_row = QHBoxLayout()
        replace_row.addWidget(QLabel("Replace with:"))
        self._replace_edit = QLineEdit()
        replace_row.addWidget(self._replace_edit)
        layout.addLayout(replace_row)

        options_row = QHBoxLayout()
        self._case_check = QCheckBox("Case sensitive")
        options_row.addWidget(self._case_check)
        options_row.addStretch(1)
        self._search_btn = QPushButton("Search")
        self._search_btn.clicked.connect(self._on_search)
        options_row.addWidget(self._search_btn)
        layout.addLayout(options_row)

        self._status_label = QLabel("")
        layout.addWidget(self._status_label)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Chapter", "Line", "Translated text"])
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        action_row = QHBoxLayout()
        self._replace_btn = QPushButton("Replace Selected")
        self._replace_btn.clicked.connect(self._on_replace_selected)
        action_row.addWidget(self._replace_btn)
        self._replace_all_btn = QPushButton("Replace All")
        self._replace_all_btn.clicked.connect(self._on_replace_all)
        action_row.addWidget(self._replace_all_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        close_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btns.rejected.connect(self.reject)
        layout.addWidget(close_btns)

    def _needle(self) -> str:
        return self._find_edit.text()

    def _on_search(self) -> None:
        needle = self._needle()
        if not needle:
            self._matches = []
            self._refresh_table()
            return
        self._matches = self._db.find_in_series(
            self._series_title, needle, case_sensitive=self._case_check.isChecked()
        )
        self._refresh_table()

    def _refresh_table(self) -> None:
        self._table.setRowCount(0)
        for m in self._matches:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(m["chapter_title"]))
            self._table.setItem(row, 1, QTableWidgetItem(str(m["line_number"])))
            self._table.setItem(row, 2, QTableWidgetItem(m["translated_text"]))
        self._status_label.setText(f"{len(self._matches)} match(es)")

    def _replaced_text(self, original: str) -> str:
        needle = self._needle()
        replacement = self._replace_edit.text()
        if self._case_check.isChecked():
            return original.replace(needle, replacement)
        # case-insensitive substring replace
        result = []
        i = 0
        lower_orig = original.lower()
        lower_needle = needle.lower()
        while True:
            idx = lower_orig.find(lower_needle, i)
            if idx == -1:
                result.append(original[i:])
                break
            result.append(original[i:idx])
            result.append(replacement)
            i = idx + len(needle)
        return "".join(result)

    def _apply_replace(self, match: dict) -> None:
        new_text = self._replaced_text(match["translated_text"])
        self._db.save_translation(match["doc_id"], match["line_number"], new_text)
        if self._on_replaced is not None:
            self._on_replaced(match["doc_id"])

    def _on_replace_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._matches):
            return
        self._apply_replace(self._matches[row])
        del self._matches[row]
        self._refresh_table()

    def _on_replace_all(self) -> None:
        if not self._matches:
            return
        if QMessageBox.question(
            self, "Replace All",
            f"Replace {len(self._matches)} match(es) across the series?",
        ) != QMessageBox.StandardButton.Yes:
            return
        for match in self._matches:
            self._apply_replace(match)
        self._matches = []
        self._refresh_table()

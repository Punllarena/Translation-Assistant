"""
Document picker dialog — shows all documents in the DB and lets the user
open or delete one.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from translation_assistant.db import Database


class OpenDocumentDialog(QDialog):
    """
    Lists documents from the DB.  User selects one and clicks Open (or
    double-clicks) to open it.  selected_doc_id is set on accept.
    """

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._selected_doc_id: int | None = None
        self._setup_ui()
        self._load_documents()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Open Document")
        self.setMinimumSize(480, 320)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Title", "Last Modified"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        self._open_btn = QPushButton("Open")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._on_open)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(self._open_btn)
        btn_row.addWidget(self._delete_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _load_documents(self) -> None:
        self._table.setRowCount(0)
        self._doc_ids: list[int] = []
        for doc in self._db.list_documents():
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(doc["title"]))
            self._table.setItem(row, 1, QTableWidgetItem(str(doc["updated_at"])))
            self._doc_ids.append(doc["id"])

    def _on_selection_changed(self) -> None:
        has_sel = bool(self._table.selectedItems())
        self._open_btn.setEnabled(has_sel)
        self._delete_btn.setEnabled(has_sel)

    def _on_open(self) -> None:
        rows = self._table.selectedItems()
        if not rows:
            return
        row = self._table.currentRow()
        self._selected_doc_id = self._doc_ids[row]
        self.accept()

    def _on_delete(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        doc_id = self._doc_ids[row]
        self._db.delete_document(doc_id)
        self._table.removeRow(row)
        self._doc_ids.pop(row)
        self._on_selection_changed()

    def _on_row_double_clicked(self, row: int, _col: int) -> None:
        self._selected_doc_id = self._doc_ids[row]
        self.accept()

    @property
    def selected_doc_id(self) -> int | None:
        return self._selected_doc_id

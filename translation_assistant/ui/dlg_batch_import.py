"""
Batch Import Dialog — imports a folder of TXT files into the DB.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from translation_assistant.db import Database
from translation_assistant.settings import AppSettings


class BatchImportDialog(QDialog):

    def __init__(self, db: Database, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._settings = settings  # reserved: last-used folder path
        self._folder: Path | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Import Folder")
        self.setMinimumWidth(480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)
        self._stack.addWidget(self._build_input_page())
        self._stack.addWidget(self._build_summary_page())

    def _build_input_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        folder_row = QHBoxLayout()
        self._folder_label = QLabel("No folder selected.")
        self._folder_label.setWordWrap(True)
        folder_row.addWidget(self._folder_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        series_row = QHBoxLayout()
        series_row.addWidget(QLabel("Series name:"))
        self._series_edit = QLineEdit()
        self._series_edit.setPlaceholderText("(leave blank for ungrouped)")
        series_row.addWidget(self._series_edit, 1)
        layout.addLayout(series_row)

        self._import_btn = QPushButton("Import")
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._on_import)
        layout.addWidget(self._import_btn)

        return page

    def _build_summary_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._summary_header = QLabel()
        layout.addWidget(self._summary_header)

        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._summary_label)
        scroll.setMinimumHeight(120)
        layout.addWidget(scroll, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        return page

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Import")
        if not folder:
            return
        self._folder = Path(folder)
        self._folder_label.setText(str(self._folder))
        self._series_edit.setText(self._folder.name)
        self._import_btn.setEnabled(True)

    def _on_import(self) -> None:
        from translation_assistant.core import batch_import_folder
        if self._folder is None:
            return
        series_title = self._series_edit.text().strip()
        result = batch_import_folder(self._folder, self._db, series_title=series_title)

        n_imported = len(result["imported"])
        n_skipped = len(result["skipped"])
        n_errors = len(result["errors"])
        if n_imported > 0:
            self._summary_header.setText("<b>Import complete.</b>")
        else:
            self._summary_header.setText("<b>Import finished — nothing new imported.</b>")

        lines = [
            f"Imported:  {n_imported}",
            f"Skipped:   {n_skipped}  (already exist)",
            f"Errors:    {n_errors}",
        ]
        if result["warnings"]:
            lines.append("")
            lines.extend(f"Warning: {w}" for w in result["warnings"])
        if result["skipped"]:
            lines.append("")
            lines.append("Skipped: " + ", ".join(result["skipped"]))
        if result["errors"]:
            lines.append("")
            for stem, msg in result["errors"]:
                lines.append(f"Error: {stem} — {msg}")

        self._summary_label.setText("\n".join(lines))
        self._stack.setCurrentIndex(1)

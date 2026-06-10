"""
New Series dialog — registers a series (title, URL, optional profile) without requiring a document.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from translation_assistant.db import Database


class NewSeriesDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._series_title = ""
        self._created_profile = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("New Series")
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setSpacing(4)

        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Required")
        form.addRow("Series Title:", self._title_edit)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("e.g. https://ncode.syosetu.com/n1234ab/")
        form.addRow("Syosetu URL:", self._url_edit)

        layout.addLayout(form)

        self._profile_check = QCheckBox("Create new profile for this series")
        layout.addWidget(self._profile_check)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        create_btn = QPushButton("Create")
        create_btn.setDefault(True)
        create_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(create_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._title_edit.setFocus()

    def _on_accept(self) -> None:
        title = self._title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "New Series", "Series title is required.")
            return
        url = self._url_edit.text().strip()
        self._db.set_series_url(title, url)
        if self._profile_check.isChecked():
            if self._db.get_profile_id(title) is None:
                self._db.create_profile(title)
            self._db.set_series_profile(title, title)
            self._created_profile = title
        self._series_title = title
        self.accept()

    @property
    def series_title(self) -> str:
        return self._series_title

    @property
    def created_profile(self) -> str:
        return self._created_profile

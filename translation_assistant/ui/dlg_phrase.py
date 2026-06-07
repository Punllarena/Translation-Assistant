"""
Quick add-phrase dialog — equivalent to frmPhrase.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QVBoxLayout,
)

from translation_assistant.db import Database


class PhraseDialog(QDialog):
    """
    Appends a single phrase + translation pair to the active profile via the DB.
    """

    def __init__(self, db: Database, profile_name: str, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._profile_name = profile_name
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Enter New Profile Name")  # matches original title
        self.setFixedSize(415, 125)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        form = QFormLayout()
        form.setContentsMargins(10, 10, 10, 4)
        self._phrase_edit = QLineEdit()
        self._translation_edit = QLineEdit()
        form.addRow("Raw Phrase:", self._phrase_edit)
        form.addRow("Translated Phrase:", self._translation_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setEnabled(False)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._translation_edit.textChanged.connect(
            lambda text: self._ok_btn.setEnabled(len(text) > 0)
        )

    def _on_accept(self) -> None:
        phrase = self._phrase_edit.text()
        translation = self._translation_edit.text().replace(" ", "_")
        self._db.add_phrase(self._profile_name, phrase, translation)
        self.accept()

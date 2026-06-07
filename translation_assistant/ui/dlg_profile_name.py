"""
Profile name input dialog — equivalent to frmProfileName.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QVBoxLayout,
)

_FORBIDDEN = '\\/*:?"<>|'


class ProfileNameDialog(QDialog):
    """Prompts for a new profile name and sanitises forbidden filename characters."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._filename = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Enter New Profile Name")
        self.setFixedSize(390, 100)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        row = QHBoxLayout()
        row.addWidget(QLabel("Profile Name:"))
        self._name_edit = QLineEdit()
        row.addWidget(self._name_edit)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setEnabled(False)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._name_edit.textChanged.connect(
            lambda text: self._ok_btn.setEnabled(len(text) > 0)
        )
        self._name_edit.setFocus()

    def _on_accept(self) -> None:
        name = self._name_edit.text()
        for ch in _FORBIDDEN:
            name = name.replace(ch, "_")
        self._filename = name
        self.accept()

    @property
    def filename(self) -> str:
        """Sanitised profile name entered by the user."""
        return self._filename

"""
New-file creation dialog — equivalent to frmNew.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from translation_assistant.core import build_new_file

_CJK_FAMILIES = ["Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "sans-serif"]


class NewFileDialog(QDialog):
    """
    Accepts raw source text, formats it into the ---SEPERATOR--- structure,
    and saves it to a user-chosen path.

    After accept(), raw_output_text and filepath are populated.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._raw_output_text = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Create New File")
        self.setFixedSize(440, 530)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        font = QFont()
        font.setFamilies(_CJK_FAMILIES)
        font.setPointSize(11)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._entry_box = QPlainTextEdit()
        self._entry_box.setFont(font)
        self._entry_box.setMinimumHeight(450)
        layout.addWidget(self._entry_box)

        self._create_btn = QPushButton("Create")
        self._create_btn.setFixedHeight(25)
        self._create_btn.setDefault(True)
        self._create_btn.clicked.connect(self._on_create)
        layout.addWidget(self._create_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._entry_box.setFocus()

    def _on_create(self) -> None:
        self._raw_output_text = build_new_file(self._entry_box.toPlainText())
        self.accept()

    @property
    def raw_output_text(self) -> str:
        return self._raw_output_text

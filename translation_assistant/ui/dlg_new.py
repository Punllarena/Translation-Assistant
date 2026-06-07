"""
New-file creation dialog — equivalent to frmNew.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCompleter, QDialog, QFormLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from translation_assistant.core import build_new_file

_CJK_FAMILIES = ["Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "sans-serif"]


class NewFileDialog(QDialog):
    """
    Accepts raw source text plus optional document metadata (series, order,
    chapter title), formats it into the ---SEPERATOR--- structure, and stores
    everything in the DB via the caller.

    After accept(), raw_output_text, series_title, series_order, and
    chapter_title are populated.
    """

    def __init__(self, db, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._raw_output_text = ""
        self._series_title = ""
        self._series_order = 0
        self._chapter_title = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Create New Document")
        self.setMinimumWidth(480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        cjk_font = QFont()
        cjk_font.setFamilies(_CJK_FAMILIES)
        cjk_font.setPointSize(11)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Metadata fields
        form = QFormLayout()
        form.setSpacing(4)

        self._series_edit = QLineEdit()
        self._series_edit.setPlaceholderText("Optional — groups chapters together")
        series_names = self._db.get_series_list() if self._db else []
        if series_names:
            completer = QCompleter(series_names, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self._series_edit.setCompleter(completer)
        form.addRow("Series Title:", self._series_edit)

        self._order_spin = QSpinBox()
        self._order_spin.setRange(0, 9999)
        self._order_spin.setValue(0)
        self._order_spin.setFixedWidth(80)
        form.addRow("Series Order:", self._order_spin)

        self._chapter_edit = QLineEdit()
        self._chapter_edit.setPlaceholderText("e.g. Chapter 1: The Beginning")
        form.addRow("Chapter Title:", self._chapter_edit)

        layout.addLayout(form)

        # Source text input
        layout.addWidget(QLabel("Source text:"))
        self._entry_box = QPlainTextEdit()
        self._entry_box.setFont(cjk_font)
        self._entry_box.setMinimumHeight(380)
        layout.addWidget(self._entry_box)

        self._create_btn = QPushButton("Create")
        self._create_btn.setFixedHeight(25)
        self._create_btn.setDefault(True)
        self._create_btn.clicked.connect(self._on_create)
        layout.addWidget(self._create_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._series_edit.setFocus()

    def _on_create(self) -> None:
        self._raw_output_text = build_new_file(self._entry_box.toPlainText())
        self._series_title = self._series_edit.text().strip()
        self._series_order = self._order_spin.value()
        self._chapter_title = self._chapter_edit.text().strip()
        self.accept()

    @property
    def raw_output_text(self) -> str:
        return self._raw_output_text

    @property
    def series_title(self) -> str:
        return self._series_title

    @property
    def series_order(self) -> int:
        return self._series_order

    @property
    def chapter_title(self) -> str:
        return self._chapter_title

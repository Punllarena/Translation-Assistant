from __future__ import annotations

import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from translation_assistant.settings import _get_app_root
from ta.translators.mecab import MeCabTranslator
from ta.translators.jparser import JParserTranslator

_EDRDG_URL = "https://www.edrdg.org/jmdict/edict.html"


class SetupGuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Setup Guide — Optional Tools")
        self.setMinimumWidth(520)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(self._build_mecab_group())
        layout.addWidget(self._build_jparser_group())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _status_label(self, available: bool) -> QLabel:
        if available:
            lbl = QLabel("✓ Installed")
            lbl.setStyleSheet("color: green; font-weight: bold;")
        else:
            lbl = QLabel("✗ Not installed")
            lbl.setStyleSheet("color: red; font-weight: bold;")
        return lbl

    def _build_mecab_group(self) -> QGroupBox:
        available = MeCabTranslator.is_available()
        box = QGroupBox("MeCab — Morphological Analysis")
        layout = QVBoxLayout(box)
        layout.addWidget(self._status_label(available))
        if not available:
            layout.addWidget(QLabel("Install via pip:"))
            cmd_row = QHBoxLayout()
            cmd_edit = QLineEdit("pip install fugashi unidic-lite")
            cmd_edit.setReadOnly(True)
            copy_btn = QPushButton("Copy")
            copy_btn.setMaximumWidth(60)
            copy_btn.clicked.connect(
                lambda: QApplication.clipboard().setText(cmd_edit.text())
            )
            cmd_row.addWidget(cmd_edit)
            cmd_row.addWidget(copy_btn)
            layout.addLayout(cmd_row)
            if sys.platform.startswith("win"):
                note = "Run this in the same Python environment used to launch the app."
            else:
                note = "No system MeCab library needed — fugashi includes its own."
            lbl = QLabel(note)
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
        return box

    def _build_jparser_group(self) -> QGroupBox:
        available = JParserTranslator.is_available()
        box = QGroupBox("JParser — Japanese Dictionary")
        layout = QVBoxLayout(box)
        layout.addWidget(self._status_label(available))
        if not available:
            instr = QLabel(
                "1. Download edict2 from edrdg.org\n"
                "2. Extract the .gz file to get edict2\n"
                "3. Place edict2 in the dictionaries/ folder next to the app"
            )
            instr.setWordWrap(True)
            layout.addWidget(instr)
            btn_row = QHBoxLayout()
            visit_btn = QPushButton("Visit edrdg.org")
            visit_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(_EDRDG_URL))
            )
            btn_row.addWidget(visit_btn)
            dict_dir = _get_app_root() / "dictionaries"
            dict_dir.mkdir(exist_ok=True)
            open_btn = QPushButton("Open dictionaries folder")
            open_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(dict_dir)))
            )
            btn_row.addWidget(open_btn)
            layout.addLayout(btn_row)
        return box

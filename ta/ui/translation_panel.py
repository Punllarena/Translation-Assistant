from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QCheckBox, QSizePolicy,
)

from ta.translators.base import BaseTranslator
from ta.config.languages import Language


class TranslationPanel(QWidget):
    def __init__(self, translator: BaseTranslator, parent=None):
        super().__init__(parent)
        self._translator = translator
        self._current_text: str = ""
        self._current_src = Language.Japanese
        self._current_dst = Language.English
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Title bar
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(0, 0, 0, 0)

        self._enable_cb = QCheckBox(self._translator.name)
        self._enable_cb.setChecked(True)
        self._enable_cb.stateChanged.connect(self._on_toggle)
        title_bar.addWidget(self._enable_cb)

        title_bar.addStretch()

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        title_bar.addWidget(self._status_label)

        self._translate_btn = QPushButton("▶")
        self._translate_btn.setFixedWidth(28)
        self._translate_btn.setToolTip(f"Translate with {self._translator.name}")
        self._translate_btn.clicked.connect(self._on_single_translate)
        title_bar.addWidget(self._translate_btn)

        layout.addLayout(title_bar)

        # Output text area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._output)

    def _connect_signals(self) -> None:
        self._translator.translation_ready.connect(self._on_ready)
        self._translator.translation_error.connect(self._on_error)
        self._translator.translation_started.connect(self._on_started)

    def translate(self, text: str, src: Language, dst: Language) -> None:
        self._current_text = text
        self._current_src = src
        self._current_dst = dst
        if self._enable_cb.isChecked() and self._translator.can_translate(src, dst):
            self._translator.translate(text, src, dst)

    def set_languages(self, src: Language, dst: Language) -> None:
        self._current_src = src
        self._current_dst = dst

    def _on_ready(self, text: str) -> None:
        if text.startswith("<html"):
            self._output.setHtml(text)
        else:
            self._output.setPlainText(text)
        self._status_label.setText("")

    def _on_error(self, msg: str) -> None:
        self._output.setPlainText(f"[Error] {msg}")
        self._status_label.setText("✗")

    def _on_started(self) -> None:
        self._status_label.setText("…")

    def _on_toggle(self, state: int) -> None:
        enabled = bool(state)
        self._output.setEnabled(enabled)
        self._translate_btn.setEnabled(enabled)

    def _on_single_translate(self) -> None:
        if self._current_text:
            self._translator.translate(self._current_text, self._current_src, self._current_dst)

    @property
    def translator_name(self) -> str:
        return self._translator.name

    def is_enabled(self) -> bool:
        return self._enable_cb.isChecked()

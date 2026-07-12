from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QCheckBox, QSizePolicy, QToolButton,
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
        self._thinking_text: str = ""
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
        self._enable_cb.setObjectName("EngineCheckbox")
        self._enable_cb.setChecked(True)
        self._enable_cb.stateChanged.connect(self._on_toggle)
        title_bar.addWidget(self._enable_cb)

        title_bar.addStretch()

        self._status_label = QLabel("")
        self._status_label.setObjectName("EngineStatus")
        self._status_label.setProperty("state", "idle")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        title_bar.addWidget(self._status_label)

        self._translate_btn = QPushButton("▶")
        self._translate_btn.setObjectName("EngineRunBtn")
        self._translate_btn.setFixedWidth(28)
        self._translate_btn.setToolTip(f"Translate with {self._translator.name}")
        self._translate_btn.clicked.connect(self._on_single_translate)
        title_bar.addWidget(self._translate_btn)

        self._copy_btn = QPushButton("⎘")
        self._copy_btn.setObjectName("EngineCopyBtn")
        self._copy_btn.setFixedWidth(28)
        self._copy_btn.setToolTip("Copy translation to clipboard")
        self._copy_btn.clicked.connect(self._on_copy)
        title_bar.addWidget(self._copy_btn)

        layout.addLayout(title_bar)

        # Collapsible reasoning trace (only populated by models that emit it)
        self._thinking_toggle = QToolButton()
        self._thinking_toggle.setObjectName("ThinkingToggle")
        self._thinking_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._thinking_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._thinking_toggle.setCheckable(True)
        self._thinking_toggle.setText("Thinking")
        self._thinking_toggle.toggled.connect(self._on_thinking_toggled)
        self._thinking_toggle.hide()
        layout.addWidget(self._thinking_toggle)

        self._thinking_box = QTextEdit()
        self._thinking_box.setObjectName("ThinkingText")
        self._thinking_box.setReadOnly(True)
        self._thinking_box.setFixedHeight(80)
        self._thinking_box.hide()
        layout.addWidget(self._thinking_box)

        # Output text area
        self._output = QTextEdit()
        self._output.setObjectName("AggTranslationText")
        self._output.setReadOnly(True)
        self._output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._output)

    def _connect_signals(self) -> None:
        self._translator.translation_ready.connect(self._on_ready)
        self._translator.translation_error.connect(self._on_error)
        self._translator.translation_started.connect(self._on_started)
        self._translator.translation_chunk.connect(self._on_chunk)
        self._translator.translation_thinking.connect(self._on_thinking)

    def translate(self, text: str, src: Language, dst: Language) -> None:
        self._current_text = text
        self._current_src = src
        self._current_dst = dst
        if self._enable_cb.isChecked() and self._translator.can_translate(src, dst):
            self._translator.translate(text, src, dst)

    def set_languages(self, src: Language, dst: Language) -> None:
        self._current_src = src
        self._current_dst = dst

    def show_result(self, text: str, source: str, src: Language, dst: Language) -> None:
        """Display a cached result without contacting the translator."""
        self._current_text = source
        self._current_src = src
        self._current_dst = dst
        if not self._enable_cb.isChecked():
            return
        # The reasoning trace belongs to whatever streamed last, not this line.
        self._thinking_text = ""
        self._thinking_box.clear()
        self._thinking_toggle.hide()
        self._thinking_box.hide()
        self._on_ready(text)

    def request_key(self) -> tuple[str, Language, Language]:
        """Identity of the last request sent (or shown) on this panel."""
        return (self._current_text, self._current_src, self._current_dst)

    def _set_status(self, state: str, text: str) -> None:
        self._status_label.setText(text)
        self._status_label.setProperty("state", state)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    def _on_ready(self, text: str) -> None:
        if text:
            if text.startswith("<html"):
                self._output.setHtml(text)
            else:
                self._output.setPlainText(text)
        self._set_status("ok", "✓")

    def _on_error(self, msg: str) -> None:
        self._output.setPlainText(f"[Error] {msg}")
        self._set_status("error", "✗")

    def _on_started(self) -> None:
        self._output.clear()
        self._thinking_text = ""
        self._thinking_box.clear()
        self._thinking_toggle.hide()
        self._thinking_box.hide()
        self._set_status("working", "…")

    def _on_chunk(self, token: str) -> None:
        if self._thinking_text and self._thinking_toggle.isChecked():
            # First real answer token: collapse the reasoning trace out of the way.
            self._thinking_toggle.setChecked(False)
        self._output.moveCursor(QTextCursor.MoveOperation.End)
        self._output.insertPlainText(token)
        self._set_status("working", "…")

    def _on_thinking(self, token: str) -> None:
        self._thinking_text += token
        if self._thinking_toggle.isHidden():
            self._thinking_toggle.show()
            self._thinking_toggle.setChecked(True)
        self._thinking_box.moveCursor(QTextCursor.MoveOperation.End)
        self._thinking_box.insertPlainText(token)
        self._set_status("working", "…")

    def _on_thinking_toggled(self, expanded: bool) -> None:
        self._thinking_box.setVisible(expanded)
        self._thinking_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        if expanded:
            self._thinking_toggle.setText("Thinking")
        else:
            lines = self._thinking_text.count("\n") + 1
            self._thinking_toggle.setText(f"Thinking ({lines} lines)")

    def _on_toggle(self, state: int) -> None:
        enabled = bool(state)
        self._output.setEnabled(enabled)
        self._translate_btn.setEnabled(enabled)
        self._copy_btn.setEnabled(enabled)

    def _on_single_translate(self) -> None:
        if self._current_text:
            self._translator.translate(self._current_text, self._current_src, self._current_dst)

    def _on_copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        text = self._output.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)

    @property
    def translator_name(self) -> str:
        return self._translator.name

    def is_enabled(self) -> bool:
        return self._enable_cb.isChecked()

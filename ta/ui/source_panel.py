from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QComboBox, QCheckBox, QSizePolicy,
)

from ta.config.languages import Language, display_names


class SourcePanel(QWidget):
    translate_requested = Signal(str)
    clipboard_toggled = Signal(bool)
    languages_changed = Signal(Language, Language)
    history_prev_requested = Signal()
    history_next_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)

        self._translate_btn = QPushButton("▶▶ Translate All")
        self._translate_btn.clicked.connect(self._on_translate)
        toolbar.addWidget(self._translate_btn)

        toolbar.addSpacing(8)

        self._src_combo = QComboBox()
        self._dst_combo = QComboBox()
        names = display_names()
        for name, lang in names:
            self._src_combo.addItem(name, lang)
            self._dst_combo.addItem(name, lang)
        self._set_combo_default(self._src_combo, Language.Japanese)
        self._set_combo_default(self._dst_combo, Language.English)
        self._src_combo.currentIndexChanged.connect(self._on_lang_changed)
        self._dst_combo.currentIndexChanged.connect(self._on_lang_changed)

        toolbar.addWidget(self._src_combo)
        toolbar.addWidget(self._dst_combo)

        toolbar.addSpacing(8)

        self._clipboard_cb = QCheckBox("Clipboard")
        self._clipboard_cb.setChecked(True)
        self._clipboard_cb.stateChanged.connect(
            lambda s: self.clipboard_toggled.emit(bool(s))
        )
        toolbar.addWidget(self._clipboard_cb)

        toolbar.addStretch()

        hist_prev = QPushButton("◀ Hist")
        hist_prev.setToolTip("Previous history entry (Ctrl+Alt+Up)")
        hist_prev.clicked.connect(self.history_prev_requested)
        toolbar.addWidget(hist_prev)

        hist_next = QPushButton("Hist ▶")
        hist_next.setToolTip("Next history entry (Ctrl+Alt+Down)")
        hist_next.clicked.connect(self.history_next_requested)
        toolbar.addWidget(hist_next)

        layout.addLayout(toolbar)

        # Source text input
        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText("Paste Japanese text here…")
        self._text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._text_edit.setMaximumHeight(120)
        layout.addWidget(self._text_edit)

    def _set_combo_default(self, combo: QComboBox, lang: Language) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == lang:
                combo.setCurrentIndex(i)
                return

    def _on_translate(self) -> None:
        text = self._text_edit.toPlainText().strip()
        if text:
            self.translate_requested.emit(text)

    def _on_lang_changed(self) -> None:
        self.languages_changed.emit(self.src_language(), self.dst_language())

    def src_language(self) -> Language:
        return self._src_combo.currentData()

    def dst_language(self) -> Language:
        return self._dst_combo.currentData()

    def set_text(self, text: str) -> None:
        self._text_edit.setPlainText(text)

    def get_text(self) -> str:
        return self._text_edit.toPlainText()

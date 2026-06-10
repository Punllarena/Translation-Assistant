from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QSplitter, QSizePolicy

from ta.ui.translation_panel import TranslationPanel
from ta.config.languages import Language


class PanelsContainer(QWidget):
    """Resizable 2-column splitter grid of TranslationPanels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels: list[TranslationPanel] = []
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Two vertical splitters as columns
        self._col0 = QSplitter(Qt.Orientation.Vertical)
        self._col1 = QSplitter(Qt.Orientation.Vertical)
        self._splitter.addWidget(self._col0)
        self._splitter.addWidget(self._col1)

        from PySide6.QtWidgets import QVBoxLayout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._splitter)

    def add_panel(self, panel: TranslationPanel) -> None:
        self._panels.append(panel)
        if len(self._panels) % 2 == 1:
            self._col0.addWidget(panel)
        else:
            self._col1.addWidget(panel)

    def remove_panel(self, name: str) -> None:
        for panel in self._panels:
            if panel.translator_name == name:
                panel.setParent(None)  # type: ignore
                self._panels.remove(panel)
                break

    def translate_all(self, text: str, src: Language, dst: Language) -> None:
        for panel in self._panels:
            panel.translate(text, src, dst)

    def set_languages(self, src: Language, dst: Language) -> None:
        for panel in self._panels:
            panel.set_languages(src, dst)

    def save_layout(self) -> dict:
        return {
            "horizontal": self._splitter.sizes(),
            "col0": self._col0.sizes(),
            "col1": self._col1.sizes(),
        }

    def restore_layout(self, data: dict) -> None:
        if "horizontal" in data:
            self._splitter.setSizes(data["horizontal"])
        if "col0" in data:
            saved = data["col0"]
            if len(saved) == self._col0.count():
                self._col0.setSizes(saved)
        if "col1" in data:
            saved = data["col1"]
            if len(saved) == self._col1.count():
                self._col1.setSizes(saved)

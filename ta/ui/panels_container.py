from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QSizePolicy

from ta.ui.translation_panel import TranslationPanel
from ta.config.languages import Language


class PanelsContainer(QWidget):
    """Tabbed container of TranslationPanels — one tab per translator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels: list[TranslationPanel] = []

        self._tab_widget = QTabWidget()
        self._tab_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tab_widget)

    def add_panel(self, panel: TranslationPanel) -> None:
        self._panels.append(panel)
        self._tab_widget.addTab(panel, panel.translator_name)

    def remove_panel(self, name: str) -> None:
        for i, panel in enumerate(self._panels):
            if panel.translator_name == name:
                self._tab_widget.removeTab(i)
                self._panels.pop(i)
                break

    def translate_all(self, text: str, src: Language, dst: Language) -> None:
        for panel in self._panels:
            panel.translate(text, src, dst)

    def set_languages(self, src: Language, dst: Language) -> None:
        for panel in self._panels:
            panel.set_languages(src, dst)

    def save_layout(self) -> dict:
        return {"tab_index": self._tab_widget.currentIndex()}

    def restore_layout(self, data: dict) -> None:
        idx = data.get("tab_index", 0)
        if isinstance(idx, int) and 0 <= idx < self._tab_widget.count():
            self._tab_widget.setCurrentIndex(idx)

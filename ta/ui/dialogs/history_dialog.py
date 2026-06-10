from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QWidget,
    QHBoxLayout, QVBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QTextEdit, QLabel,
)
from PySide6.QtCore import Qt

from ta.core.history import HistoryStore, HistoryEntry


class HistoryDialog(QDialog):
    def __init__(self, store: HistoryStore, parent=None):
        super().__init__(parent)
        self._store = store
        self._entries: list[HistoryEntry] = list(reversed(store.all_entries()))
        self.setWindowTitle("History")
        self.setMinimumSize(700, 480)
        self._setup_ui()
        self._populate()

    def _setup_ui(self) -> None:
        main = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: entry list
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        splitter.addWidget(self._list)

        # Right: source + translations
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)

        right_layout.addWidget(QLabel("Source:"))
        self._source_edit = QTextEdit()
        self._source_edit.setReadOnly(True)
        self._source_edit.setMaximumHeight(80)
        right_layout.addWidget(self._source_edit)

        right_layout.addWidget(QLabel("Translations:"))
        self._translations_edit = QTextEdit()
        self._translations_edit.setReadOnly(True)
        right_layout.addWidget(self._translations_edit)

        splitter.addWidget(right)
        splitter.setSizes([220, 480])
        main.addWidget(splitter)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        # Close button is mapped to rejected in Qt
        main.addWidget(buttons)

    def _populate(self) -> None:
        self._list.clear()
        for entry in self._entries:
            label = f"{entry.timestamp}  {entry.source[:40]}{'…' if len(entry.source) > 40 else ''}"
            self._list.addItem(QListWidgetItem(label))
        if self._entries:
            self._list.setCurrentRow(0)

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._entries):
            self._source_edit.clear()
            self._translations_edit.clear()
            return
        entry = self._entries[row]
        self._source_edit.setPlainText(entry.source)
        parts = []
        for name, text in entry.translations.items():
            parts.append(f"[{name}]\n{text}")
        self._translations_edit.setPlainText("\n\n".join(parts))

    # ------------------------------------------------------------------
    # Test-facing accessors
    # ------------------------------------------------------------------

    def entry_count(self) -> int:
        return self._list.count()

    def entry_sources(self) -> list[str]:
        return [e.source for e in self._entries]

    def select_entry(self, row: int) -> None:
        self._list.setCurrentRow(row)

    def selected_source(self) -> str:
        return self._source_edit.toPlainText()

    def selected_translations(self) -> str:
        return self._translations_edit.toPlainText()

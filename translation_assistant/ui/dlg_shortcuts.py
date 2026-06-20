from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QKeySequenceEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QAction
    from translation_assistant.settings import AppSettings

_HANDLE_KEY_SHORTCUTS: list[tuple[str, str]] = [
    ("Enter",       "Save & Next"),
    ("PageDown",    "Next (no save)"),
    ("PageUp",      "Previous"),
    ("Ctrl+End",    "Jump to next untranslated"),
    ("Ctrl+Home",   "Jump to first"),
    ("Ctrl+Right",  "Advance parse"),
    ("Ctrl+Left",   "Retreat parse"),
    ("Ctrl+F",      "Copy translation to clipboard"),
    ("Ctrl+A",      "Select all in translation field"),
    ("Ctrl+J",      "Add word to dictionary"),
]


class ShortcutsDialog(QDialog):
    def __init__(
        self,
        registry: list[tuple[str, str, "QAction", str]],
        settings: "AppSettings",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(520, 560)
        self._registry = registry
        self._settings = settings
        self._editors: dict[str, QKeySequenceEdit] = {}

        self._table = QTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 200)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self._populate()

        btn_box = QDialogButtonBox()
        self._btn_reset = QPushButton("Reset Defaults")
        self._btn_reset.clicked.connect(self._on_reset)
        btn_box.addButton(self._btn_reset, QDialogButtonBox.ButtonRole.ResetRole)
        btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        btn_box.addButton(QDialogButtonBox.StandardButton.Ok)
        btn_box.accepted.connect(self._on_ok)
        btn_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addWidget(btn_box)

    def _add_section_header(self, label: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        item = QTableWidgetItem(label)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setBackground(self.palette().mid())
        self._table.setItem(row, 0, item)
        self._table.setSpan(row, 0, 1, 2)

    def _add_editable_row(self, key: str, name: str, action: "QAction", default: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        name_item = QTableWidgetItem(name)
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, 0, name_item)

        current = self._settings.get_shortcut(key) or default
        kse = QKeySequenceEdit(QKeySequence(current))
        kse.setProperty("_default", default)

        clear_btn = QPushButton("✕")
        clear_btn.setFixedWidth(28)
        clear_btn.setToolTip("Reset to default")
        clear_btn.clicked.connect(lambda: kse.setKeySequence(QKeySequence(default)))

        cell_widget = QWidget()
        h = QHBoxLayout(cell_widget)
        h.setContentsMargins(2, 2, 2, 2)
        h.addWidget(kse)
        h.addWidget(clear_btn)

        self._table.setCellWidget(row, 1, cell_widget)
        self._editors[key] = kse

    def _add_readonly_row(self, key_str: str, name: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        name_item = QTableWidgetItem(name)
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, 0, name_item)

        key_item = QTableWidgetItem(key_str)
        key_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self._table.setItem(row, 1, key_item)

    def _populate(self) -> None:
        self._table.setRowCount(0)
        self._editors.clear()
        self._add_section_header("─── Editable ───")
        for key, name, action, default in self._registry:
            self._add_editable_row(key, name, action, default)
        self._add_section_header("─── View Only ───")
        for key_str, name in _HANDLE_KEY_SHORTCUTS:
            self._add_readonly_row(key_str, name)

    def _on_reset(self) -> None:
        for key, _, _, default in self._registry:
            editor = self._editors.get(key)
            if editor is not None:
                editor.setKeySequence(QKeySequence(default))

    def _on_ok(self) -> None:
        seen: dict[str, str] = {}  # sequence string -> display name
        conflicts: list[str] = []
        for key, name, _, _ in self._registry:
            kse = self._editors.get(key)
            if kse is None:
                continue
            seq = kse.keySequence().toString()
            if not seq:
                continue
            if seq in seen:
                conflicts.append(f'"{name}" and "{seen[seq]}"')
            else:
                seen[seq] = name

        if conflicts:
            QMessageBox.warning(
                self,
                "Shortcut Conflict",
                "The following shortcuts conflict:\n\n" + "\n".join(conflicts)
                + "\n\nPlease resolve before saving.",
            )
            return

        for key, _, action, _ in self._registry:
            kse = self._editors.get(key)
            if kse is None:
                continue
            seq = kse.keySequence().toString()
            self._settings.set_shortcut(key, seq)
            action.setShortcut(seq)

        self.accept()

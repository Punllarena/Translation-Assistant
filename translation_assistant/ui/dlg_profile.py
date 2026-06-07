"""
Profile manager dialog — equivalent to frmProfile.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from translation_assistant.db import Database
from translation_assistant.settings import AppSettings


class ProfileDialog(QDialog):
    """
    Manages per-profile glossary and the parse-character setting via the DB.

    Lets the user:
    - Switch between profiles
    - Edit phrase/translation pairs in a table
    - Create and delete profiles
    - Update parse characters

    After accept(), text_output contains the saved glossary entries as strings.
    """

    def __init__(self, settings: AppSettings, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._db = db
        self._text_output: list[str] = []
        self._setup_ui()
        self._load_profiles()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("Profile Setting")
        self.setFixedSize(345, 500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Parse characters row
        parse_form = QFormLayout()
        self._parse_edit = QLineEdit(self._settings.parse_char)
        parse_form.addRow("Parse Characters:", self._parse_edit)
        layout.addLayout(parse_form)

        # Profile selector + action buttons
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self._combo = QComboBox()
        self._combo.setMinimumWidth(130)
        self._combo.currentIndexChanged.connect(self._on_profile_changed)
        profile_row.addWidget(self._combo, 1)
        layout.addLayout(profile_row)

        btn_row = QHBoxLayout()
        self._new_btn = QPushButton("Create New")
        self._new_btn.setFixedHeight(24)
        self._new_btn.clicked.connect(self._on_new_profile)
        self._delete_btn = QPushButton("Delete Profile")
        self._delete_btn.setFixedHeight(24)
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_profile)
        btn_row.addStretch()
        btn_row.addWidget(self._new_btn)
        btn_row.addWidget(self._delete_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Phrase / Translation table
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Phrases", "Translation"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 140)
        self._table.cellDoubleClicked.connect(self._on_row_double_click)
        layout.addWidget(self._table, stretch=1)

        # Add row button
        add_btn = QPushButton("Add Row")
        add_btn.setFixedHeight(22)
        add_btn.clicked.connect(lambda: self._append_row())
        layout.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Save / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.clicked.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Profile loading
    # ------------------------------------------------------------------

    def _load_profiles(self) -> None:
        self._combo.blockSignals(True)
        self._combo.clear()
        for name in sorted(self._db.list_profiles()):
            self._combo.addItem(name)
        self._combo.blockSignals(False)

        current = self._settings.profile_used
        idx = self._combo.findText(current)
        self._combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._on_profile_changed(self._combo.currentIndex())

    def _on_profile_changed(self, index: int) -> None:
        if index < 0:
            return
        name = self._combo.itemText(index)
        row = self._db._conn.execute(
            "SELECT is_default FROM profiles WHERE name = ?", (name,)
        ).fetchone()
        is_default = bool(row and row[0])
        self._delete_btn.setEnabled(not is_default)
        self._populate_table(name)

    def _populate_table(self, profile_name: str) -> None:
        self._table.setRowCount(0)
        for phrase, translation in self._db.get_glossary(profile_name):
            self._append_row(phrase, translation)

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------

    def _append_row(self, phrase: str = "", translation: str = "") -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(phrase))
        self._table.setItem(row, 1, QTableWidgetItem(translation))

    def _on_row_double_click(self, row: int, _col: int) -> None:
        phrase = self._table.item(row, 0)
        trans = self._table.item(row, 1)
        p = phrase.text() if phrase else ""
        t = trans.text() if trans else ""
        entry = f"{p} = {t}"
        reply = QMessageBox.question(
            self,
            "Delete Phrase",
            f"Are you sure you want to delete:\n{entry}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._table.removeRow(row)

    # ------------------------------------------------------------------
    # Profile CRUD
    # ------------------------------------------------------------------

    def _on_new_profile(self) -> None:
        from translation_assistant.ui.dlg_profile_name import ProfileNameDialog

        dlg = ProfileNameDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        name = dlg.filename
        if not name:
            return

        if self._db.get_profile_id(name) is not None:
            reply = QMessageBox.question(
                self,
                "Profile Exists",
                f"Profile '{name}' already exists. Switch to it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        else:
            self._db.create_profile(name)

        idx = self._combo.findText(name)
        if idx < 0:
            self._combo.addItem(name)
            idx = self._combo.count() - 1
        self._combo.setCurrentIndex(idx)

    def _on_delete_profile(self) -> None:
        name = self._combo.currentText()
        reply = QMessageBox.question(
            self,
            "Delete Profile",
            f"Are you sure you want to delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._db.delete_profile(name)
        idx = self._combo.currentIndex()
        self._combo.removeItem(idx)
        if self._combo.count() > 0:
            self._settings.profile_used = self._combo.currentText()

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        name = self._combo.currentText()

        self._text_output.clear()
        rows: list[tuple[str, str]] = []

        for row in range(self._table.rowCount()):
            phrase_item = self._table.item(row, 0)
            trans_item = self._table.item(row, 1)
            phrase = phrase_item.text() if phrase_item else ""
            translation = (trans_item.text() if trans_item else "").replace(" ", "_")
            if phrase or translation:
                rows.append((phrase, translation))
                self._text_output.append(f"{phrase},{translation}")

        self._db.set_glossary(name, rows)

        self._settings.profile_used = name
        self._settings.parse_char = self._parse_edit.text()
        self._settings.save()
        self.accept()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def text_output(self) -> list[str]:
        """Glossary entries that were saved, as 'phrase,translation' strings."""
        return self._text_output

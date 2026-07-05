"""
Series Manager dialog — view all series, set syosetu URL, open chapter fetcher.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QMenu,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QToolTip,
    QVBoxLayout,
)
from translation_assistant.core import load_glossary
from translation_assistant.scraper import _validate_series_url

from translation_assistant.db import Database


class SeriesManagerDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._loading = False
        self._setup_ui()
        self._load()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Manage Series")
        self.setMinimumSize(700, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Series Title", "Syosetu URL", "Chapters", "Profile"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.currentCellChanged.connect(lambda row, *_: self._on_row_changed(row))
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._table)

        self._set_url_action = QAction("Set URL…", self)
        self._set_url_action.triggered.connect(self._on_set_url)
        self._set_wp_action = QAction("Set WP Fields…", self)
        self._set_wp_action.triggered.connect(self._on_set_wp_fields)
        self._add_profile_action = QAction("Add Profile", self)
        self._add_profile_action.triggered.connect(self._on_add_profile)
        self._import_profile_action = QAction("Import Phrases from CSV…", self)
        self._import_profile_action.triggered.connect(self._on_import_profile)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._new_series_btn = QPushButton("New Series…")
        self._new_series_btn.clicked.connect(self._on_new_series)
        self._fetch_btn = QPushButton("Fetch new chapters…")
        self._fetch_btn.setEnabled(False)
        self._fetch_btn.clicked.connect(self._on_fetch)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._new_series_btn)
        btn_row.addWidget(self._fetch_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _load(self) -> None:
        self._loading = True
        try:
            series = self._db.get_series_list_full()
            self._table.setRowCount(len(series))
            for row, s in enumerate(series):
                cells = [s["title"], s["url"], str(s["chapter_count"]), s["profile_name"]]
                for col, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    if col != 1:  # only the URL column is editable
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._table.setItem(row, col, item)
        finally:
            self._loading = False
        self._on_row_changed(self._table.currentRow())

    def _current_series(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        return {
            "title": self._table.item(row, 0).text(),
            "url": self._table.item(row, 1).text(),
            "profile": self._table.item(row, 3).text(),
        }

    def _on_row_changed(self, row: int) -> None:
        s = self._current_series()
        self._fetch_btn.setEnabled(s is not None and bool(s["url"]))

    def _on_context_menu(self, pos) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        self._table.setCurrentCell(row, 0)
        s = self._current_series()
        if s is None:
            return
        self._add_profile_action.setEnabled(not s["profile"])
        self._import_profile_action.setEnabled(bool(s["profile"]))
        menu = QMenu(self)
        menu.addAction(self._set_url_action)
        menu.addAction(self._set_wp_action)
        menu.addSeparator()
        menu.addAction(self._add_profile_action)
        menu.addAction(self._import_profile_action)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 1:
            return
        title = self._table.item(item.row(), 0).text()
        url = item.text().strip()
        if url:
            try:
                _validate_series_url(url)
            except ValueError as exc:
                self._loading = True
                item.setText(self._db.get_series_url(title))
                self._loading = False
                QToolTip.showText(QCursor.pos(), str(exc), self._table)
                return
        self._db.set_series_url(title, url)
        self._loading = True
        item.setText(url)
        self._loading = False
        self._on_row_changed(item.row())

    def _on_set_url(self) -> None:
        s = self._current_series()
        if s is None:
            return
        url, ok = QInputDialog.getText(
            self,
            "Set Series URL",
            f"Syosetu URL for \"{s['title']}\":",
            text=s["url"],
        )
        if not ok:
            return
        url = url.strip()
        if url:
            try:
                _validate_series_url(url)
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid URL", str(exc))
                return
        self._db.set_series_url(s["title"], url)
        self._load()

    def _on_fetch(self) -> None:
        s = self._current_series()
        if s is None or not s["url"]:
            return
        from translation_assistant.ui.dlg_fetch_series import FetchSeriesDialog
        dlg = FetchSeriesDialog(self._db, s["title"], s["url"], parent=self)
        dlg.exec()
        self._load()

    def _on_set_wp_fields(self) -> None:
        s = self._current_series()
        if s is None:
            return
        from translation_assistant.wp_publisher import slugify
        meta = self._db.get_series_wp_meta(s["title"])
        current_slug = meta["series_slug"] or slugify(s["title"])
        current_short = meta["series_title_short"]

        from PySide6.QtWidgets import (
            QComboBox, QDialog, QDialogButtonBox, QFormLayout,
            QLineEdit, QSpinBox, QVBoxLayout,
        )
        from PySide6.QtCore import Qt
        dlg = QDialog(self)
        dlg.setWindowTitle(f"WP Fields — {s['title']}")
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        slug_edit = QLineEdit(current_slug)
        slug_edit.setPlaceholderText("url-safe-slug")
        short_edit = QLineEdit(current_short)
        short_edit.setPlaceholderText("Abbreviation")
        form.addRow("Series Slug:", slug_edit)
        form.addRow("Short Title:", short_edit)

        pw_meta = self._db.get_series_wp_password_settings(s["title"])
        pw_enabled_val = pw_meta["wp_password_enabled"]  # "1", "0", or None
        unlock_after_val = pw_meta["wp_unlock_after"]    # int or -1

        pw_combo = QComboBox()
        pw_combo.addItems(["Use global", "Always on", "Always off"])
        if pw_enabled_val == "1":
            pw_combo.setCurrentIndex(1)
        elif pw_enabled_val == "0":
            pw_combo.setCurrentIndex(2)
        else:
            pw_combo.setCurrentIndex(0)
        form.addRow("Password protection:", pw_combo)

        unlock_spin = QSpinBox()
        unlock_spin.setRange(1, 99)
        unlock_spin.setValue(unlock_after_val if unlock_after_val > 0 else 3)
        unlock_spin.setEnabled(pw_combo.currentIndex() == 1)
        pw_combo.currentIndexChanged.connect(
            lambda idx: unlock_spin.setEnabled(idx == 1)
        )
        form.addRow("Keep locked:", unlock_spin)
        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec():
            self._db.set_series_wp_meta(s["title"], slug_edit.text().strip(), short_edit.text().strip())
            idx = pw_combo.currentIndex()
            enabled_out = ("1" if idx == 1 else "0" if idx == 2 else None)
            unlock_out = unlock_spin.value() if idx == 1 else -1
            self._db.set_series_wp_password_settings(s["title"], enabled_out, unlock_out)

    def _on_add_profile(self) -> None:
        # Same semantics as NewSeriesDialog's "Create new profile" checkbox
        s = self._current_series()
        if s is None or s["profile"]:
            return
        title = s["title"]
        if self._db.get_profile_id(title) is None:
            self._db.create_profile(title)
        self._db.set_series_profile(title, title)
        self._load()

    def _on_import_profile(self) -> None:
        s = self._current_series()
        if s is None or not s["profile"]:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Phrases from CSV", "", "CSV files (*.csv)"
        )
        if not path:
            return
        rows = load_glossary(Path(path))
        if not rows:
            QMessageBox.warning(self, "Import Phrases", "No phrases found in file.")
            return
        for phrase, translation in rows:
            # add_phrase is INSERT OR REPLACE — the file wins on duplicate phrases
            self._db.add_phrase(s["profile"], phrase, translation)
        QMessageBox.information(
            self, "Import Phrases",
            f"Imported {len(rows)} phrases into profile '{s['profile']}'.",
        )

    def _on_new_series(self) -> None:
        from translation_assistant.ui.dlg_new_series import NewSeriesDialog
        dlg = NewSeriesDialog(self._db, parent=self)
        if dlg.exec():
            self._load()

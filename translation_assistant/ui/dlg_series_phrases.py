"""Series Phrase Suggestions dialog."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHeaderView, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from translation_assistant.core import extract_frequent_nouns
from translation_assistant.db import Database
from translation_assistant.settings import AppSettings


class SeriesPhrasesDialog(QDialog):
    def __init__(
        self,
        db: Database,
        settings: AppSettings,
        current_series: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._settings = settings
        self._raw_results: list[tuple[str, int]] = []
        self._current_glossary: set[str] = set()
        self.setWindowTitle("Series Phrase Suggestions")
        self.setMinimumSize(500, 480)
        self._setup_ui()
        self._populate_series(current_series)
        self._populate_profiles()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._series_combo = QComboBox()
        self._series_combo.currentTextChanged.connect(self._on_series_changed)
        form.addRow("Series:", self._series_combo)

        self._profile_combo = QComboBox()
        self._profile_combo.currentTextChanged.connect(self._on_profile_changed)
        form.addRow("Add to profile:", self._profile_combo)

        self._min_freq_spin = QSpinBox()
        self._min_freq_spin.setRange(1, 999)
        self._min_freq_spin.setValue(2)
        form.addRow("Min frequency:", self._min_freq_spin)

        layout.addLayout(form)

        self._analyze_btn = QPushButton("Analyze")
        self._analyze_btn.clicked.connect(self._on_analyze)
        layout.addWidget(self._analyze_btn)

        self._status_label = QLabel("")
        layout.addWidget(self._status_label)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Term", "Count"])
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(1, 60)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table)

        add_row = QHBoxLayout()
        self._translation_edit = QLineEdit()
        self._translation_edit.setPlaceholderText("Enter translation…")
        self._translation_edit.setEnabled(False)
        self._translation_edit.textChanged.connect(self._on_translation_changed)
        add_row.addWidget(self._translation_edit, 1)
        self._add_btn = QPushButton("Add to Profile")
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._on_add)
        add_row.addWidget(self._add_btn)
        layout.addLayout(add_row)

        close_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btns.rejected.connect(self.reject)
        layout.addWidget(close_btns)

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def _populate_series(self, current_series: str) -> None:
        series = self._db.get_series_list()
        self._series_combo.blockSignals(True)
        self._series_combo.clear()
        if not series:
            self._series_combo.blockSignals(False)
            self._analyze_btn.setEnabled(False)
            self._status_label.setText("No series found")
            return
        for s in series:
            self._series_combo.addItem(s)
        self._series_combo.blockSignals(False)
        idx = self._series_combo.findText(current_series)
        self._series_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _populate_profiles(self) -> None:
        profiles = self._db.list_profiles()
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        for p in profiles:
            self._profile_combo.addItem(p)
        self._profile_combo.blockSignals(False)
        series = self._series_combo.currentText()
        default = self._db.get_series_profile(series) or self._settings.profile_used
        idx = self._profile_combo.findText(default)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)
        self._reload_glossary()

    def _reload_glossary(self) -> None:
        profile = self._profile_combo.currentText()
        self._current_glossary = {phrase for phrase, _ in self._db.get_glossary(profile)}

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_series_changed(self, _: str) -> None:
        self._raw_results = []
        self._refresh_table()
        series = self._series_combo.currentText()
        default = self._db.get_series_profile(series) or self._settings.profile_used
        idx = self._profile_combo.findText(default)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)

    def _on_profile_changed(self, _: str) -> None:
        self._reload_glossary()
        self._refresh_table()

    def _on_analyze(self) -> None:
        series = self._series_combo.currentText()
        if not series:
            return
        doc_ids = self._db.get_document_ids_by_series(series)
        raw_lines: list[str] = []
        for doc_id in doc_ids:
            raw_lines.extend(
                ln["raw_text"]
                for ln in self._db.get_lines(doc_id)
                if ln["raw_text"].strip()
            )
        if not raw_lines:
            self._status_label.setText("No lines found for this series")
            self._table.setRowCount(0)
            return
        try:
            results = extract_frequent_nouns(
                raw_lines,
                self._current_glossary,
                self._min_freq_spin.value(),
            )
        except (ImportError, RuntimeError) as exc:
            QMessageBox.warning(
                self,
                "MeCab Not Available",
                "MeCab is required for phrase analysis.\n"
                "Install it with: pip install mecab-python3\n\n"
                f"Error: {exc}",
            )
            self._table.setRowCount(0)
            return
        self._raw_results = results
        self._refresh_table()

    def _refresh_table(self) -> None:
        visible = [(t, c) for t, c in self._raw_results if t not in self._current_glossary]
        self._table.setRowCount(0)
        for term, count in visible:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(term))
            self._table.setItem(row, 1, QTableWidgetItem(str(count)))
        if visible:
            self._status_label.setText(f"{len(visible)} candidates found")
        elif self._raw_results:
            n = len(self._raw_results)
            self._status_label.setText(
                f"No new candidates ({n} terms already in glossary)"
            )
        self._translation_edit.setEnabled(False)
        self._translation_edit.clear()
        self._add_btn.setEnabled(False)

    def _on_selection_changed(self) -> None:
        has_sel = bool(self._table.selectedItems())
        self._translation_edit.setEnabled(has_sel)
        if has_sel:
            self._translation_edit.setFocus()
        self._update_add_btn()

    def _on_translation_changed(self, _: str) -> None:
        self._update_add_btn()

    def _update_add_btn(self) -> None:
        has_sel = bool(self._table.selectedItems())
        has_text = bool(self._translation_edit.text().strip())
        self._add_btn.setEnabled(has_sel and has_text)

    def _on_add(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        term = self._table.item(row, 0).text()
        translation = self._translation_edit.text().strip().replace(" ", "_")
        if not translation:
            return
        profile = self._profile_combo.currentText()
        self._db.add_phrase(profile, term, translation)
        self._current_glossary.add(term)
        self._table.removeRow(row)
        self._translation_edit.clear()
        self._translation_edit.setEnabled(False)
        self._add_btn.setEnabled(False)

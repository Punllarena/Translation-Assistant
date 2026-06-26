"""
New-file creation dialog — equivalent to frmNew.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from translation_assistant.core import build_new_file
from translation_assistant.scraper import FetchWorker

_CJK_FAMILIES = ["Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "sans-serif"]
_USE_SERIES = "Use the Series Title"


class NewFileDialog(QDialog):
    """
    Accepts raw source text plus optional document metadata (series, order,
    chapter title), formats it into the ---SEPERATOR--- structure, and stores
    everything in the DB via the caller.

    After accept(), raw_output_text, series_title, series_order, chapter_title,
    and linked_profile are populated.
    """

    def __init__(self, db, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._raw_output_text = ""
        self._series_title = ""
        self._series_order = 0
        self._chapter_title = ""
        self._linked_profile = ""
        self._worker = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Create New Document")
        self.setMinimumWidth(480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        cjk_font = QFont()
        cjk_font.setFamilies(_CJK_FAMILIES)
        cjk_font.setPointSize(11)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setSpacing(4)

        self._series_edit = QLineEdit()
        self._series_edit.setPlaceholderText("Optional — groups chapters together")
        series_names = self._db.get_series_list() if self._db else []
        if series_names:
            completer = QCompleter(series_names, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.activated.connect(self._on_series_changed)
            self._series_edit.setCompleter(completer)
        self._series_edit.textChanged.connect(self._on_series_changed)
        form.addRow("Series Title:", self._series_edit)

        self._series_url_label = QLabel("Series URL:")
        self._series_url_edit = QLineEdit()
        self._series_url_edit.setPlaceholderText("e.g. https://novel18.syosetu.com/n7696mg/")
        form.addRow(self._series_url_label, self._series_url_edit)
        self._series_url_edit.setVisible(False)
        self._series_url_label.setVisible(False)

        self._order_spin = QSpinBox()
        self._order_spin.setRange(0, 9999)
        self._order_spin.setValue(0)
        self._order_spin.setFixedWidth(80)
        form.addRow("Series Order:", self._order_spin)

        self._chapter_edit = QLineEdit()
        self._chapter_edit.setPlaceholderText("e.g. Chapter 1: The Beginning")
        form.addRow("Chapter Title:", self._chapter_edit)

        layout.addLayout(form)

        # Profile link row
        link_row = QHBoxLayout()
        self._link_profile_check = QCheckBox("Link series to glossary profile:")
        self._profile_combo = QComboBox()
        profiles = self._db.list_profiles() if self._db else []
        self._profile_combo.addItem(_USE_SERIES)
        self._profile_combo.addItems(profiles)
        link_row.addWidget(self._link_profile_check)
        link_row.addWidget(self._profile_combo)
        link_row.addStretch()
        layout.addLayout(link_row)

        self._tabs = QTabWidget()

        # Tab 0: Paste Text
        paste_widget = QVBoxLayout()
        self._entry_box = QPlainTextEdit()
        self._entry_box.setFont(cjk_font)
        self._entry_box.setMinimumHeight(380)
        paste_widget.addWidget(self._entry_box)
        paste_widget.setContentsMargins(0, 4, 0, 0)
        paste_tab = QWidget()
        paste_tab.setLayout(paste_widget)
        self._tabs.addTab(paste_tab, "Paste Text")

        # Tab 1: Fetch from URL
        fetch_tab = QWidget()
        fetch_layout = QVBoxLayout(fetch_tab)
        fetch_layout.setContentsMargins(0, 4, 0, 0)
        fetch_layout.setSpacing(4)

        url_row = QHBoxLayout()
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("e.g. https://ncode.syosetu.com/n7696mg/1/")
        self._fetch_btn = QPushButton("Fetch")
        self._fetch_btn.setFixedWidth(60)
        self._fetch_btn.clicked.connect(self._on_fetch)
        url_row.addWidget(self._url_edit)
        url_row.addWidget(self._fetch_btn)
        fetch_layout.addLayout(url_row)

        self._fetch_status = QLabel("")
        fetch_layout.addWidget(self._fetch_status)

        self._fetch_box = QPlainTextEdit()
        self._fetch_box.setFont(cjk_font)
        self._fetch_box.setMinimumHeight(380)
        fetch_layout.addWidget(self._fetch_box)

        self._tabs.addTab(fetch_tab, "Fetch from URL")

        layout.addWidget(self._tabs)

        self._create_btn = QPushButton("Create")
        self._create_btn.setFixedHeight(25)
        self._create_btn.setDefault(True)
        self._create_btn.clicked.connect(self._on_create)
        layout.addWidget(self._create_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._series_edit.setFocus()

    def _on_series_changed(self, text: str) -> None:
        has_series = bool(text.strip())
        self._series_url_edit.setVisible(has_series)
        self._series_url_label.setVisible(has_series)
        if not text.strip():
            return
        if self._db:
            next_order = self._db.get_next_series_order(text.strip())
            self._order_spin.setValue(next_order)
            linked = self._db.get_series_profile(text.strip())
            if linked:
                idx = self._profile_combo.findText(linked)
                if idx >= 0:
                    self._profile_combo.setCurrentIndex(idx)
                self._link_profile_check.setChecked(True)
            url = self._db.get_series_url(text.strip())
            self._series_url_edit.setText(url)

    def _on_fetch(self) -> None:
        url = self._url_edit.text().strip()
        if not url:
            return
        self._fetch_btn.setEnabled(False)
        self._fetch_status.setText("Fetching…")
        self._worker = FetchWorker(url, parent=self)
        self._worker.finished.connect(self._on_fetch_done)
        self._worker.error.connect(self._on_fetch_error)
        self._worker.start()

    def _on_fetch_done(self, title: str, content: str) -> None:
        self._fetch_box.setPlainText(content)
        if title:
            self._chapter_edit.setText(title)
        self._fetch_status.setText("Done")
        self._fetch_btn.setEnabled(True)
        self._worker = None

    def _on_fetch_error(self, msg: str) -> None:
        self._fetch_status.setText(f"Error: {msg}")
        self._fetch_btn.setEnabled(True)
        self._worker = None

    def _on_create(self) -> None:
        if self._tabs.currentIndex() == 0:
            text = self._entry_box.toPlainText()
        else:
            text = self._fetch_box.toPlainText()
        self._raw_output_text = build_new_file(text)
        self._series_title = self._series_edit.text().strip()
        self._series_order = self._order_spin.value()
        self._chapter_title = self._chapter_edit.text().strip()
        if self._link_profile_check.isChecked() and self._series_title and self._db:
            choice = self._profile_combo.currentText()
            if choice == _USE_SERIES:
                profile_name = self._series_title
                if self._db.get_profile_id(profile_name) is None:
                    self._db.create_profile(profile_name)
            else:
                profile_name = choice
            self._linked_profile = profile_name
            self._db.set_series_profile(self._series_title, profile_name)
        else:
            self._linked_profile = ""
        series_url = self._series_url_edit.text().strip()
        if series_url and self._series_title and self._db:
            self._db.set_series_url(self._series_title, series_url)
        self.accept()

    @property
    def raw_output_text(self) -> str:
        return self._raw_output_text

    @property
    def series_title(self) -> str:
        return self._series_title

    @property
    def series_order(self) -> int:
        return self._series_order

    @property
    def chapter_title(self) -> str:
        return self._chapter_title

    @property
    def linked_profile(self) -> str:
        return self._linked_profile

    @property
    def source_url(self) -> str:
        if self._tabs.currentIndex() == 1:
            return self._url_edit.text().strip()
        return ""

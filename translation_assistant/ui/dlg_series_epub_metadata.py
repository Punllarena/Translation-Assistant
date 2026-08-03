"""
Set EPUB Metadata dialog — attaches author/illustrator/publisher/identifier
and a cover image to a series' single (volume_title="") document bucket, so
scraped series can produce a properly-tagged EPUB without being re-imported
through ImportEpubDialog. Single-volume only: see
docs/superpowers/specs/2026-07-31-epub-metadata-for-scraped-series-design.md.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from translation_assistant.db import Database

_IMAGE_FILTER = "Images (*.jpg *.jpeg *.png *.gif *.webp)"


class SeriesEpubMetadataDialog(QDialog):

    def __init__(self, db: Database, series_title: str, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._series_title = series_title
        # Single-volume only: discover the one bucket this series' documents
        # already live in (falls back to "" for a brand-new/empty series).
        self._volume_title = self._discover_volume_title()
        self._pending_cover_path: str | None = None
        self._cover_cleared = False
        self._setup_ui()
        self._load()

    def _discover_volume_title(self) -> str:
        doc_ids = self._db.get_document_ids_by_series(self._series_title)
        if not doc_ids:
            return ""
        return self._db.get_document(doc_ids[0])["volume_title"]

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"Set EPUB Metadata — {self._series_title}")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._volume_edit = QLineEdit()
        form.addRow("Volume Title:", self._volume_edit)
        self._author_edit = QLineEdit()
        form.addRow("Author:", self._author_edit)
        self._illustrator_edit = QLineEdit()
        form.addRow("Illustrator:", self._illustrator_edit)
        self._publisher_edit = QLineEdit()
        form.addRow("Publisher:", self._publisher_edit)
        self._identifier_edit = QLineEdit()
        form.addRow("ISBN:", self._identifier_edit)

        cover_row = QHBoxLayout()
        self._cover_label = QLabel("None")
        cover_row.addWidget(self._cover_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse_cover)
        cover_row.addWidget(browse_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._on_clear_cover)
        cover_row.addWidget(clear_btn)
        form.addRow("Cover:", cover_row)

        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load(self) -> None:
        meta = self._db.get_volume_metadata(self._series_title, self._volume_title)
        self._volume_edit.setText(meta["volume_title"])
        self._author_edit.setText(meta["volume_author"])
        self._illustrator_edit.setText(meta["volume_illustrator"])
        self._publisher_edit.setText(meta["volume_publisher"])
        self._identifier_edit.setText(meta["volume_identifier"])
        if meta["has_cover"]:
            self._cover_label.setText("(existing cover)")

    def _on_browse_cover(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Cover Image", "", _IMAGE_FILTER)
        if not path:
            return
        self._pending_cover_path = path
        self._cover_cleared = False
        self._cover_label.setText(Path(path).name)

    def _on_clear_cover(self) -> None:
        self._pending_cover_path = None
        self._cover_cleared = True
        self._cover_label.setText("None")

    def _on_save(self) -> None:
        new_title = self._volume_edit.text().strip()
        if new_title != self._volume_title:
            self._db.set_volume_title(self._series_title, self._volume_title, new_title)
            self._volume_title = new_title

        self._db.update_volume_metadata(
            self._series_title, self._volume_title,
            volume_author=self._author_edit.text().strip(),
            volume_illustrator=self._illustrator_edit.text().strip(),
            volume_publisher=self._publisher_edit.text().strip(),
            volume_identifier=self._identifier_edit.text().strip(),
            new_volume_title=self._volume_title,
        )

        if self._pending_cover_path is not None or self._cover_cleared:
            doc_ids = self._db.get_document_ids_by_volume(self._series_title, self._volume_title)
            if doc_ids:
                first_doc_id = doc_ids[0]
                if self._pending_cover_path is not None:
                    data = Path(self._pending_cover_path).read_bytes()
                    self._db.replace_document_cover(first_doc_id, self._pending_cover_path, data)
                else:
                    self._db.clear_document_cover(first_doc_id)

        self.accept()

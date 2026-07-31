"""
Import EPUB Dialog — parses a purchased EPUB volume and imports its
chapters into the existing document/series model.
Same browse -> configure -> import -> summary shape as dlg_batch_import.py.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCompleter, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from translation_assistant.core import build_new_file, lines_to_db_rows, parse_file_content
from translation_assistant.db import Database
from translation_assistant.epub import EpubError, extract_chapter_content, open_book

_DEFAULT_CHECK_THRESHOLD = 500


class ImportEpubDialog(QDialog):

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._book_path: Path | None = None
        self._book: dict | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Import EPUB")
        self.setMinimumSize(480, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)
        self._stack.addWidget(self._build_input_page())
        self._stack.addWidget(self._build_summary_page())

    def _build_input_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        file_row = QHBoxLayout()
        self._file_label = QLabel("No file selected.")
        self._file_label.setWordWrap(True)
        file_row.addWidget(self._file_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        series_row = QHBoxLayout()
        series_row.addWidget(QLabel("Series title:"))
        self._series_edit = QLineEdit()
        series_names = self._db.get_series_list()
        if series_names:
            completer = QCompleter(series_names, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self._series_edit.setCompleter(completer)
        series_row.addWidget(self._series_edit, 1)
        layout.addLayout(series_row)

        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("Volume title:"))
        self._volume_edit = QLineEdit()
        volume_row.addWidget(self._volume_edit, 1)
        layout.addLayout(volume_row)

        author_row = QHBoxLayout()
        author_row.addWidget(QLabel("Author:"))
        self._author_edit = QLineEdit()
        author_row.addWidget(self._author_edit, 1)
        layout.addLayout(author_row)

        illustrator_row = QHBoxLayout()
        illustrator_row.addWidget(QLabel("Illustrator:"))
        self._illustrator_edit = QLineEdit()
        illustrator_row.addWidget(self._illustrator_edit, 1)
        layout.addLayout(illustrator_row)

        publisher_row = QHBoxLayout()
        publisher_row.addWidget(QLabel("Publisher:"))
        self._publisher_edit = QLineEdit()
        publisher_row.addWidget(self._publisher_edit, 1)
        layout.addLayout(publisher_row)

        identifier_row = QHBoxLayout()
        identifier_row.addWidget(QLabel("ISBN:"))
        self._identifier_edit = QLineEdit()
        identifier_row.addWidget(self._identifier_edit, 1)
        layout.addLayout(identifier_row)

        layout.addWidget(QLabel("Chapters:"))
        self._chapter_list = QListWidget()
        layout.addWidget(self._chapter_list, 1)

        self._import_btn = QPushButton("Import")
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._on_import)
        layout.addWidget(self._import_btn)

        return page

    def _build_summary_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._summary_header = QLabel()
        layout.addWidget(self._summary_header)

        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._summary_label)
        scroll.setMinimumHeight(120)
        layout.addWidget(scroll, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        return page

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select EPUB File", "", "EPUB files (*.epub)")
        if not path:
            return
        try:
            book = open_book(Path(path))
        except EpubError as exc:
            QMessageBox.critical(self, "Import Error", f"Could not read this EPUB:\n{exc}")
            return

        self._book_path = Path(path)
        self._book = book
        self._file_label.setText(str(self._book_path))
        self._series_edit.setText(book["title"])
        self._volume_edit.setText(book["title"])
        self._author_edit.setText(book.get("author", ""))
        self._illustrator_edit.setText(book.get("illustrator", ""))
        self._publisher_edit.setText(book.get("publisher", ""))
        self._identifier_edit.setText(book.get("identifier", ""))

        self._chapter_list.clear()
        for ch in book["chapters"]:
            item = QListWidgetItem(f"{ch['order']}. {ch['title']}  ({ch['char_count']} chars)")
            item.setData(Qt.ItemDataRole.UserRole, ch)
            item.setCheckState(
                Qt.CheckState.Checked if ch["char_count"] >= _DEFAULT_CHECK_THRESHOLD
                else Qt.CheckState.Unchecked
            )
            self._chapter_list.addItem(item)
        self._import_btn.setEnabled(bool(book["chapters"]))

    def _on_import(self) -> None:
        if self._book is None or self._book_path is None:
            return
        series_title = self._series_edit.text().strip()
        volume_title = self._volume_edit.text().strip()
        volume_author = self._author_edit.text().strip()
        volume_illustrator = self._illustrator_edit.text().strip()
        volume_publisher = self._publisher_edit.text().strip()
        volume_identifier = self._identifier_edit.text().strip()
        if not series_title or not volume_title:
            # Blank titles would make the dedup lookup match every series-less
            # legacy document in the DB, silently skipping real chapters.
            QMessageBox.warning(
                self, "Missing Title", "Series title and volume title are required."
            )
            return

        already_imported = self._db.get_volume_chapter_titles(series_title, volume_title)
        next_order = self._db.get_next_series_order(series_title)
        cover_href = self._book.get("cover_href")
        cover_data = None
        if cover_href and not self._db.volume_has_cover(series_title, volume_title):
            try:
                import zipfile
                with zipfile.ZipFile(self._book_path) as zf:
                    cover_data = zf.read(cover_href)
            except Exception:
                cover_data = None

        imported = []
        skipped = []
        errors = []
        empty = []
        first_new_doc_id = None
        for i in range(self._chapter_list.count()):
            item = self._chapter_list.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            ch = item.data(Qt.ItemDataRole.UserRole)
            if ch["title"] in already_imported:
                skipped.append(ch["title"])
                continue
            try:
                text, images = extract_chapter_content(self._book_path, ch["href"])
                formatted = build_new_file(text)
                raw_lines, translated_lines, _ = parse_file_content(formatted)
                rows = lines_to_db_rows(raw_lines, translated_lines)
                doc_id = self._db.create_document(
                    ch["title"],
                    series_title=series_title,
                    series_order=next_order,
                    chapter_title=ch["title"],
                    volume_title=volume_title,
                    # No source_url: a zip-internal href is not a fetchable URL,
                    # and a non-empty source_url makes dlg_open offer "Re-fetch".
                    volume_author=volume_author,
                    volume_illustrator=volume_illustrator,
                    volume_publisher=volume_publisher,
                    volume_identifier=volume_identifier,
                )
                self._db.save_lines(doc_id, rows)
                for img in images:
                    self._db.add_document_image(
                        doc_id, img["anchor_position"], False, img["src_path"], img["data"]
                    )
                if first_new_doc_id is None:
                    first_new_doc_id = doc_id
                next_order += 1
                imported.append(ch["title"])
                if not raw_lines:
                    empty.append(ch["title"])
            except Exception as exc:
                errors.append((ch["title"], str(exc)))

        if cover_data is not None and first_new_doc_id is not None:
            self._db.add_document_image(first_new_doc_id, 0, True, cover_href, cover_data)

        self._show_summary(imported, skipped, errors, empty)

    def _show_summary(self, imported: list[str], skipped: list[str],
                      errors: list[tuple[str, str]], empty: list[str] | None = None) -> None:
        if imported:
            self._summary_header.setText("<b>Import complete.</b>")
        else:
            self._summary_header.setText("<b>Import finished — nothing new imported.</b>")

        lines = [
            f"Imported: {len(imported)}",
            f"Skipped:  {len(skipped)}  (already imported)",
            f"Errors:   {len(errors)}",
        ]
        if skipped:
            lines.append("")
            lines.append("Skipped: " + ", ".join(skipped))
        if empty:
            lines.append("")
            lines.append(
                "No text extracted (0 lines) — these will always read as 0% "
                "translated and are omitted from EPUB export: " + ", ".join(empty)
            )
        if errors:
            lines.append("")
            for title, msg in errors:
                lines.append(f"Error: {title} — {msg}")

        self._summary_label.setText("\n".join(lines))
        self._stack.setCurrentIndex(1)

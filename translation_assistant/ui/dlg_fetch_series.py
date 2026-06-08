"""
Chapter picker and batch fetch progress dialog for a syosetu series.
Phase 1: load chapter list from index page, let user pick.
Phase 2: fetch selected chapters with rate limiting, save to DB.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton, QVBoxLayout,
)

from translation_assistant.core import build_new_file, lines_to_db_rows, parse_file_content
from translation_assistant.db import Database
from translation_assistant.scraper import IndexFetchWorker, SeriesFetchWorker


class FetchSeriesDialog(QDialog):
    def __init__(self, db: Database, series_title: str, series_url: str, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._series_title = series_title
        self._series_url = series_url
        self._chapters: list[dict] = []
        self._fetch_worker: SeriesFetchWorker | None = None
        self._index_worker: IndexFetchWorker | None = None
        self._added = 0
        self._setup_ui()
        self._start_index_load()

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"Fetch Chapters — {self._series_title}")
        self.setMinimumSize(500, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._status_label = QLabel("Loading chapter list…")
        layout.addWidget(self._status_label)

        self._list = QListWidget()
        self._list.setVisible(False)
        self._list.itemChanged.connect(self._on_check_changed)
        layout.addWidget(self._list)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._action_btn = QPushButton("Fetch Selected (0)")
        self._action_btn.setEnabled(False)
        self._action_btn.clicked.connect(self._on_action)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._action_btn)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

    def _start_index_load(self) -> None:
        self._index_worker = IndexFetchWorker(self._series_url, parent=self)
        self._index_worker.finished.connect(self._on_index_loaded)
        self._index_worker.error.connect(self._on_index_error)
        self._index_worker.start()

    def _on_index_loaded(self, chapters: list) -> None:
        self._chapters = chapters
        existing = set(self._db.get_series_chapters(self._series_title))
        self._list.blockSignals(True)
        for ch in chapters:
            item = QListWidgetItem(f"Chapter {ch['num']}: {ch['title']}")
            item.setData(Qt.ItemDataRole.UserRole, ch)
            already = ch["num"] in existing
            item.setCheckState(
                Qt.CheckState.Unchecked if already else Qt.CheckState.Checked
            )
            if already:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setText(item.text() + "  (already fetched)")
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._list.setVisible(True)
        self._status_label.setText(
            f"{len(chapters)} chapters found. Select chapters to fetch."
        )
        self._update_action_btn()
        self._index_worker = None

    def _on_index_error(self, msg: str) -> None:
        self._status_label.setText(f"Error loading chapter list: {msg}")
        self._index_worker = None

    def _on_check_changed(self, _item: QListWidgetItem) -> None:
        self._update_action_btn()

    def _update_action_btn(self) -> None:
        count = sum(
            1 for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
            and bool(self._list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled)
        )
        self._action_btn.setText(f"Fetch Selected ({count})")
        self._action_btn.setEnabled(count > 0)

    def _selected_chapters(self) -> list[dict]:
        result = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if (item.checkState() == Qt.CheckState.Checked
                    and bool(item.flags() & Qt.ItemFlag.ItemIsEnabled)):
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    def _on_action(self) -> None:
        selected = self._selected_chapters()
        if not selected:
            return
        total = len(selected)
        self._action_btn.setEnabled(False)
        self._list.setEnabled(False)
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._status_label.setText(f"Fetching chapter 1 of {total}…")
        self._cancel_btn.setText("Cancel")
        self._added = 0

        self._fetch_worker = SeriesFetchWorker(selected, parent=self)
        self._fetch_worker.chapter_done.connect(self._on_chapter_done)
        self._fetch_worker.progress.connect(self._on_progress)
        self._fetch_worker.error.connect(self._on_chapter_error)
        self._fetch_worker.finished.connect(self._on_fetch_finished)
        self._fetch_worker.start()

    def _on_chapter_done(self, num: int, title: str, content: str) -> None:
        formatted = build_new_file(content)
        raw_lines, translated_lines, _ = parse_file_content(formatted)
        rows = lines_to_db_rows(raw_lines, translated_lines)
        doc_id = self._db.create_document(
            title,
            series_title=self._series_title,
            series_order=num,
            chapter_title=title,
        )
        self._db.save_lines(doc_id, rows)
        self._added += 1

    def _on_progress(self, current: int, total: int) -> None:
        self._progress_bar.setValue(current)
        if current < total:
            self._status_label.setText(f"Fetching chapter {current + 1} of {total}…")

    def _on_chapter_error(self, num: int, msg: str) -> None:
        self._error_label.setVisible(True)
        prev = self._error_label.text()
        self._error_label.setText(
            (prev + "\n" if prev else "") + f"Chapter {num}: {msg}"
        )

    def _on_fetch_finished(self) -> None:
        self._progress_bar.setValue(self._progress_bar.maximum())
        self._status_label.setText(f"Done — {self._added} chapter(s) added.")
        self._cancel_btn.setText("Close")
        self._cancel_btn.setEnabled(True)
        self._fetch_worker = None

    def closeEvent(self, event) -> None:
        if self._fetch_worker is not None:
            self._fetch_worker.requestInterruption()
            self._fetch_worker.wait(3000)
        elif self._index_worker is not None and self._index_worker.isRunning():
            self._index_worker.wait(3000)
        super().closeEvent(event)

    def _on_cancel(self) -> None:
        if self._fetch_worker is not None:
            self._fetch_worker.requestInterruption()
            self._fetch_worker.wait(3000)
        elif self._index_worker is not None and self._index_worker.isRunning():
            self._index_worker.wait(3000)
        self.reject()

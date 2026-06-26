"""
Document picker dialog — two-panel layout with series list on left, chapter tree on right.
"""
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSpinBox,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from translation_assistant.db import Database

_NO_SERIES = "(No Series)"
_CHAPTER_HEADERS = ["#", "Title", "Progress", "Last Edited"]


class OpenDocumentDialog(QDialog):
    """
    Lists documents from the DB in a two-panel layout.
    Left panel: series list. Right panel: chapter tree (flat, 4 cols).
    User selects a chapter and clicks Open (or double-clicks).
    """

    _SORT_KEYS = {
        0: lambda item: item.data(0, Qt.ItemDataRole.UserRole) or 0,
        1: lambda item: item.text(1).lower(),
        2: lambda item: item.data(2, Qt.ItemDataRole.UserRole) or 0,
        3: lambda item: item.text(3),
    }

    def __init__(self, db: Database, parent=None, *, current_doc_id: int | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._selected_doc_id: int | None = None
        self._doc_ids: dict[int, int] = {}  # id(QTreeWidgetItem) → doc_id
        self._source_urls: dict[int, str] = {}
        self._refetch_worker = None
        self._setup_ui()
        self._load_series()
        if current_doc_id is not None:
            self._select_doc(current_doc_id)
        elif self._series_list.count():
            self._series_list.setCurrentRow(0)

    def _setup_ui(self) -> None:
        self.setWindowTitle("Open Document")
        self.setMinimumSize(780, 460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter chapters…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        outer.addWidget(self._filter_edit)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._series_list = QListWidget()
        self._series_list.setFixedWidth(220)
        self._series_list.currentItemChanged.connect(self._on_series_selected)
        self._series_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._series_list.customContextMenuRequested.connect(self._on_series_context_menu)
        self._splitter.addWidget(self._series_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(_CHAPTER_HEADERS)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionsClickable(True)
        self._tree.header().sectionClicked.connect(self._sort_chapters)
        self._tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self._tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self._tree.currentItemChanged.connect(self._on_chapter_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.itemActivated.connect(self._on_item_activated)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_chapter_context_menu)
        right_layout.addWidget(self._tree)

        self._splitter.addWidget(right)
        self._splitter.setStretchFactor(1, 1)
        outer.addWidget(self._splitter)

        self._sort_col = 0
        self._sort_asc = True

        btn_row = QHBoxLayout()
        self._open_btn = QPushButton("Open")
        self._open_btn.setEnabled(False)
        self._open_btn.setDefault(True)
        self._open_btn.clicked.connect(self._on_open)
        self._edit_btn = QPushButton("Edit…")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit)
        self._edit_source_btn = QPushButton("Edit Source…")
        self._edit_source_btn.setEnabled(False)
        self._edit_source_btn.clicked.connect(self._on_edit_source)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setEnabled(False)
        self._delete_btn.setStyleSheet("color: red;")
        self._delete_btn.clicked.connect(self._on_delete)
        self._refetch_btn = QPushButton("Re-fetch")
        self._refetch_btn.setEnabled(False)
        self._refetch_btn.clicked.connect(self._on_refetch)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        for btn in (self._open_btn, self._edit_btn, self._edit_source_btn,
                    self._delete_btn, self._refetch_btn, cancel_btn):
            btn_row.addWidget(btn)
        outer.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Stub methods — implemented in Tasks 3–5
    # ------------------------------------------------------------------

    def _load_series(self) -> None:
        self._series_list.clear()
        docs = self._db.list_documents()

        series_counts: dict[str, int] = {}
        for doc in docs:
            key = doc["series_title"] or ""
            series_counts[key] = series_counts.get(key, 0) + 1

        if "" in series_counts:
            item = QListWidgetItem(f"{_NO_SERIES} ({series_counts['']})")
            item.setData(Qt.ItemDataRole.UserRole, "")
            self._series_list.addItem(item)

        for name in sorted(k for k in series_counts if k):
            item = QListWidgetItem(f"{name} ({series_counts[name]})")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._series_list.addItem(item)

    def _load_chapters(self, series_raw: str) -> None:
        self._tree.clear()
        self._doc_ids.clear()
        self._source_urls.clear()

        docs = self._db.list_documents()
        docs = [d for d in docs if (d["series_title"] or "") == series_raw]
        docs.sort(key=lambda d: (d["series_order"], d["title"]))

        for doc in docs:
            display = doc["chapter_title"] if doc["chapter_title"] else doc["title"]
            progress_pct = doc["progress"]
            item = QTreeWidgetItem([
                str(doc["series_order"]),
                display,
                f"{progress_pct}%",
                _fmt_date(doc.get("updated_at", "")),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, doc["series_order"])
            item.setData(2, Qt.ItemDataRole.UserRole, progress_pct)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            if progress_pct == 0:
                item.setForeground(2, QColor("#888888"))
            elif progress_pct == 100:
                item.setForeground(2, QColor("#2a8a2a"))
            else:
                item.setForeground(2, QColor("#c8a000"))

            self._doc_ids[id(item)] = doc["id"]
            self._source_urls[id(item)] = doc.get("source_url", "")
            self._tree.addTopLevelItem(item)

        self._apply_filter(self._filter_edit.text())
        self._update_sort_header()

    def _on_series_selected(self, current, _prev) -> None:
        if current is None:
            self._tree.clear()
            self._doc_ids.clear()
            self._source_urls.clear()
            return
        self._load_chapters(current.data(Qt.ItemDataRole.UserRole))

    def _sort_chapters(self, col: int) -> None:
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        count = self._tree.topLevelItemCount()
        items = [self._tree.takeTopLevelItem(0) for _ in range(count)]
        key_fn = self._SORT_KEYS.get(col, lambda item: item.text(1).lower())
        items.sort(key=key_fn, reverse=not self._sort_asc)
        for item in items:
            self._tree.addTopLevelItem(item)
        self._update_sort_header()

    def _update_sort_header(self) -> None:
        headers = _CHAPTER_HEADERS
        for col, label in enumerate(headers):
            if col == self._sort_col:
                arrow = " ▲" if self._sort_asc else " ▼"
            else:
                arrow = ""
            self._tree.headerItem().setText(col, label + arrow)

    def _on_chapter_context_menu(self, pos) -> None:
        pass

    def _on_series_context_menu(self, pos) -> None:
        pass

    def _current_series_raw(self) -> str | None:
        item = self._series_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _restore_series(self, series_raw: str | None) -> None:
        if series_raw is None:
            if self._series_list.count():
                self._series_list.setCurrentRow(0)
            return
        for i in range(self._series_list.count()):
            if self._series_list.item(i).data(Qt.ItemDataRole.UserRole) == series_raw:
                self._series_list.setCurrentRow(i)
                return
        if self._series_list.count():
            self._series_list.setCurrentRow(0)

    # ------------------------------------------------------------------
    # Core navigation / selection
    # ------------------------------------------------------------------

    def _select_doc(self, doc_id: int) -> None:
        try:
            doc = self._db.get_document(doc_id)
        except ValueError:
            return
        series_raw = doc["series_title"] or ""
        # Select the series (triggers _load_chapters)
        for i in range(self._series_list.count()):
            if self._series_list.item(i).data(Qt.ItemDataRole.UserRole) == series_raw:
                self._series_list.setCurrentRow(i)
                break
        # Find chapter in (now-loaded) tree
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if self._doc_ids.get(id(item)) == doc_id:
                self._tree.setCurrentItem(item)
                self._tree.scrollToItem(item)
                return

    def _current_leaf(self) -> QTreeWidgetItem | None:
        return self._tree.currentItem()

    def _on_chapter_selection_changed(self) -> None:
        leaf = self._current_leaf()
        is_leaf = leaf is not None
        self._open_btn.setEnabled(is_leaf)
        self._edit_btn.setEnabled(is_leaf)
        self._edit_source_btn.setEnabled(is_leaf)
        self._delete_btn.setEnabled(is_leaf)
        has_url = is_leaf and bool(self._source_urls.get(id(leaf), ""))
        self._refetch_btn.setEnabled(has_url)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_open(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        self._selected_doc_id = self._doc_ids[id(leaf)]
        self.accept()

    def _on_delete(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        title = leaf.text(1)
        answer = QMessageBox.question(
            self,
            "Delete Document",
            f'Delete "{title}"? This cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        doc_id = self._doc_ids.pop(id(leaf), None)
        if doc_id is not None:
            self._db.delete_document(doc_id)
        series_raw = self._current_series_raw()
        self._load_series()
        self._restore_series(series_raw)

    def _on_edit(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        doc_id = self._doc_ids[id(leaf)]
        doc = self._db.get_document(doc_id)
        dlg = _EditMetadataDialog(
            series_title=doc["series_title"],
            series_order=doc["series_order"],
            chapter_title=doc["chapter_title"],
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._do_edit(doc_id, dlg.series_title, dlg.series_order, dlg.chapter_title)

    def _on_edit_source(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        doc_id = self._doc_ids[id(leaf)]
        dlg = _EditSourceDialog(doc_id, leaf.text(1), self._db, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            series_raw = self._current_series_raw()
            self._load_series()
            self._restore_series(series_raw)
            self._select_doc(doc_id)

    def _on_refetch(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from translation_assistant.scraper import FetchWorker

        leaf = self._current_leaf()
        if leaf is None:
            return
        doc_id = self._doc_ids[id(leaf)]
        url = self._source_urls.get(id(leaf), "")
        if not url:
            return
        answer = QMessageBox.question(
            self,
            "Re-fetch",
            f"Re-fetch content from:\n{url}\n\nExisting translations will be preserved by line position.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for btn in (self._open_btn, self._edit_btn, self._delete_btn, self._refetch_btn):
            btn.setEnabled(False)
        self._refetch_btn.setText("Fetching…")
        self._refetch_worker = FetchWorker(url, parent=self)
        self._refetch_worker.finished.connect(
            lambda title, content: self._on_refetch_done(doc_id, title, content)
        )
        self._refetch_worker.error.connect(self._on_refetch_error)
        self._refetch_worker.start()

    def _on_refetch_done(self, doc_id: int, title: str, content: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        from translation_assistant.core import build_new_file, parse_file_content

        formatted = build_new_file(f"{title}\n\n{content}" if title else content)
        raw_lines, _, _ = parse_file_content(formatted)
        self._db.replace_raw_content(doc_id, raw_lines)
        self._refetch_worker = None
        self._refetch_btn.setText("Re-fetch")
        series_raw = self._current_series_raw()
        self._load_series()
        self._restore_series(series_raw)
        self._select_doc(doc_id)
        QMessageBox.information(self, "Re-fetch", "Content re-fetched successfully.")

    def _on_refetch_error(self, msg: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        self._refetch_worker = None
        self._refetch_btn.setText("Re-fetch")
        self._on_chapter_selection_changed()
        QMessageBox.warning(self, "Re-fetch Failed", f"Error: {msg}")

    def closeEvent(self, event) -> None:
        if self._refetch_worker is not None:
            self._refetch_worker.wait(3000)
        super().closeEvent(event)

    def _do_edit(self, doc_id: int, series_title: str, series_order: int, chapter_title: str) -> None:
        self._db.update_document_metadata(
            doc_id,
            series_title=series_title,
            series_order=series_order,
            chapter_title=chapter_title,
        )
        series_raw = self._current_series_raw()
        self._load_series()
        self._restore_series(series_raw)
        self._select_doc(doc_id)

    def _on_item_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        self._selected_doc_id = self._doc_ids[id(item)]
        self.accept()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        self._selected_doc_id = self._doc_ids[id(item)]
        self.accept()

    def _open_series_manager(self) -> None:
        from translation_assistant.ui.dlg_series import SeriesManagerDialog
        dlg = SeriesManagerDialog(self._db, parent=self)
        dlg.exec()

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            match = not query or query in item.text(1).lower()
            item.setHidden(not match)

    @property
    def selected_doc_id(self) -> int | None:
        return self._selected_doc_id


class _EditMetadataDialog(QDialog):
    def __init__(self, *, series_title: str, series_order: int, chapter_title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Document")
        self.setMinimumWidth(380)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setSpacing(4)

        self._series_edit = QLineEdit(series_title)
        form.addRow("Series Title:", self._series_edit)

        self._order_spin = QSpinBox()
        self._order_spin.setRange(0, 9999)
        self._order_spin.setValue(series_order)
        self._order_spin.setFixedWidth(80)
        form.addRow("Series Order:", self._order_spin)

        self._chapter_edit = QLineEdit(chapter_title)
        form.addRow("Chapter Title:", self._chapter_edit)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Save")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    @property
    def series_title(self) -> str:
        return self._series_edit.text().strip()

    @property
    def series_order(self) -> int:
        return self._order_spin.value()

    @property
    def chapter_title(self) -> str:
        return self._chapter_edit.text().strip()


class _EditSourceDialog(QDialog):
    def __init__(self, doc_id: int, doc_title: str, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._doc_id = doc_id
        self._db = db
        self.setWindowTitle(f"Edit Source — {doc_title}")
        self.setMinimumSize(500, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        from PySide6.QtWidgets import QPlainTextEdit
        self._editor = QPlainTextEdit()
        editor_font = QFont("monospace")
        editor_font.setPointSize(10)
        self._editor.setFont(editor_font)
        layout.addWidget(self._editor)

        rows = self._db.get_lines(doc_id)
        text = "\n".join(r["raw_text"] for r in rows)
        self._editor.setPlainText(text)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_save(self) -> None:
        from translation_assistant.core import build_new_file, parse_file_content
        text = self._editor.toPlainText()
        formatted = build_new_file(text)
        raw_lines, _, _ = parse_file_content(formatted)
        self._db.replace_raw_content(self._doc_id, raw_lines)
        self.accept()


def _fmt_date(iso: str) -> str:
    """Format SQLite datetime string to short human-readable form."""
    if not iso:
        return ""
    try:
        dt = datetime.strptime(iso[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso[:16]

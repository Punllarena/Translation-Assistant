"""
Document picker dialog — shows all documents grouped by series in a tree view.
"""
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout,
)

from translation_assistant.db import Database

_NO_SERIES = "(No Series)"


class OpenDocumentDialog(QDialog):
    """
    Lists documents from the DB grouped by series_title.
    Ungrouped documents appear under "(No Series)".
    User selects a leaf item and clicks Open (or double-clicks).
    """

    def __init__(self, db: Database, parent=None, *, current_doc_id: int | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._selected_doc_id: int | None = None
        self._doc_ids: dict[int, int] = {}  # id(QTreeWidgetItem) → doc_id
        self._source_urls: dict[int, str] = {}
        self._refetch_worker = None
        self._setup_ui()
        self._load_documents()
        if current_doc_id is not None:
            self._select_doc(current_doc_id)

    def _setup_ui(self) -> None:
        self.setWindowTitle("Open Document")
        self.setMinimumSize(680, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by title…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        top_row.addWidget(self._filter_edit)

        self._sort_combo = QComboBox()
        self._sort_combo.addItems([
            "Series Order",
            "Last Edited",
            "Progress ↑",
            "Progress ↓",
            "Title A→Z",
        ])
        self._sort_combo.currentIndexChanged.connect(self._load_documents)
        top_row.addWidget(self._sort_combo)
        layout.addLayout(top_row)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Title", "Progress", "Last Edited"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self._tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self._tree)

        btn_row = QHBoxLayout()
        self._open_btn = QPushButton("Open")
        self._open_btn.setEnabled(False)
        self._open_btn.setDefault(True)
        self._open_btn.clicked.connect(self._on_open)
        self._edit_btn = QPushButton("Edit…")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit)
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
        btn_row.addWidget(self._open_btn)
        btn_row.addWidget(self._edit_btn)
        btn_row.addWidget(self._delete_btn)
        btn_row.addWidget(self._refetch_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _load_documents(self) -> None:
        self._tree.clear()
        self._doc_ids.clear()
        self._source_urls.clear()

        docs = self._db.list_documents()
        if not docs:
            return

        groups: dict[str, QTreeWidgetItem] = {}
        group_counts: dict[str, int] = {}

        idx = self._sort_combo.currentIndex() if hasattr(self, "_sort_combo") else 0
        _display = lambda d: d["chapter_title"] if d["chapter_title"] else d["title"]
        if idx == 1:  # Last Edited
            docs_sorted = sorted(docs, key=lambda d: d["updated_at"] or "", reverse=True)
        elif idx == 2:  # Progress ↑
            docs_sorted = sorted(docs, key=lambda d: (d["progress"], d["series_title"] or _NO_SERIES, d["series_order"]))
        elif idx == 3:  # Progress ↓
            docs_sorted = sorted(docs, key=lambda d: (-d["progress"], d["series_title"] or _NO_SERIES, d["series_order"]))
        elif idx == 4:  # Title A→Z
            docs_sorted = sorted(docs, key=lambda d: (d["series_title"] or _NO_SERIES, _display(d)))
        else:  # Series Order (default)
            docs_sorted = sorted(docs, key=lambda d: (d["series_title"] or _NO_SERIES, d["series_order"]))

        for doc in docs_sorted:
            series = doc["series_title"] or _NO_SERIES
            if series not in groups:
                group_item = QTreeWidgetItem(self._tree, [series, "", ""])
                group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                font = group_item.font(0)
                font.setBold(True)
                group_item.setFont(0, font)
                groups[series] = group_item
                group_counts[series] = 0

            display = doc["chapter_title"] if doc["chapter_title"] else doc["title"]
            progress = f"{doc['progress']}%"
            last_edited = _fmt_date(doc.get("updated_at", ""))
            leaf = QTreeWidgetItem(groups[series], [display, progress, last_edited])
            leaf.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            pct = doc["progress"]
            if pct == 0:
                leaf.setForeground(1, QColor("#888888"))
            elif pct == 100:
                leaf.setForeground(1, QColor("#2a8a2a"))
            else:
                leaf.setForeground(1, QColor("#c8a000"))

            self._doc_ids[id(leaf)] = doc["id"]
            self._source_urls[id(leaf)] = doc.get("source_url", "")
            group_counts[series] += 1

        for series, group_item in groups.items():
            count = group_counts[series]
            group_item.setText(0, f"{series} ({count})")

        self._tree.expandAll()

    def _select_doc(self, doc_id: int) -> None:
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            for j in range(group.childCount()):
                leaf = group.child(j)
                if self._doc_ids.get(id(leaf)) == doc_id:
                    self._tree.setCurrentItem(leaf)
                    self._tree.scrollToItem(leaf)
                    return

    def _current_leaf(self) -> QTreeWidgetItem | None:
        item = self._tree.currentItem()
        if item is None or item.childCount() > 0:
            return None
        return item

    def _on_selection_changed(self) -> None:
        leaf = self._current_leaf()
        is_leaf = leaf is not None
        self._open_btn.setEnabled(is_leaf)
        self._edit_btn.setEnabled(is_leaf)
        self._delete_btn.setEnabled(is_leaf)
        has_url = is_leaf and bool(self._source_urls.get(id(leaf), ""))
        self._refetch_btn.setEnabled(has_url)

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
        title = leaf.text(0)
        answer = QMessageBox.question(
            self,
            "Delete Document",
            f'Delete "{title}"? This cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        doc_id = self._doc_ids.pop(id(leaf))
        self._db.delete_document(doc_id)
        group = leaf.parent()
        group.removeChild(leaf)
        if group.childCount() == 0:
            self._tree.invisibleRootItem().removeChild(group)
        self._on_selection_changed()

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
        self._load_documents()
        QMessageBox.information(self, "Re-fetch", "Content re-fetched successfully.")

    def _on_refetch_error(self, msg: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        self._refetch_worker = None
        self._refetch_btn.setText("Re-fetch")
        self._on_selection_changed()
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
        self._load_documents()

    def _on_item_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        if item.childCount() > 0:
            return
        self._selected_doc_id = self._doc_ids[id(item)]
        self.accept()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        if item.childCount() > 0:
            return
        self._selected_doc_id = self._doc_ids[id(item)]
        self.accept()

    def _on_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        if item.childCount() == 0:
            item = item.parent()
        if item is None or item.text(0) == _NO_SERIES:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        action = menu.addAction("Manage Series…")
        if menu.exec(self._tree.viewport().mapToGlobal(pos)) == action:
            self._open_series_manager()

    def _open_series_manager(self) -> None:
        from translation_assistant.ui.dlg_series import SeriesManagerDialog
        dlg = SeriesManagerDialog(self._db, parent=self)
        dlg.exec()

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            any_visible = False
            for j in range(group.childCount()):
                leaf = group.child(j)
                match = not query or query in leaf.text(0).lower()
                leaf.setHidden(not match)
                if match:
                    any_visible = True
            group.setHidden(not any_visible)

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


def _fmt_date(iso: str) -> str:
    """Format SQLite datetime string to short human-readable form."""
    if not iso:
        return ""
    try:
        dt = datetime.strptime(iso[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso[:16]

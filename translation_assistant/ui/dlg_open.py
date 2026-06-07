"""
Document picker dialog — shows all documents grouped by series in a tree view.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from translation_assistant.db import Database

_NO_SERIES = "(No Series)"


class OpenDocumentDialog(QDialog):
    """
    Lists documents from the DB grouped by series_title.
    Ungrouped documents appear under "(No Series)".
    User selects a leaf item and clicks Open (or double-clicks).
    """

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._selected_doc_id: int | None = None
        self._doc_ids: dict[int, int] = {}  # QTreeWidgetItem id → doc_id
        self._setup_ui()
        self._load_documents()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Open Document")
        self.setMinimumSize(560, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by title…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter_edit)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Title", "Progress"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self._tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._tree)

        btn_row = QHBoxLayout()
        self._open_btn = QPushButton("Open")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._on_open)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(self._open_btn)
        btn_row.addWidget(self._delete_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _load_documents(self) -> None:
        self._tree.clear()
        self._doc_ids.clear()

        docs = self._db.list_documents()
        if not docs:
            return

        # Group by series_title
        groups: dict[str, QTreeWidgetItem] = {}

        for doc in sorted(docs, key=lambda d: (d["series_title"], d["series_order"])):
            series = doc["series_title"] or _NO_SERIES
            if series not in groups:
                group_item = QTreeWidgetItem(self._tree, [series, ""])
                group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not selectable
                font = group_item.font(0)
                font.setBold(True)
                group_item.setFont(0, font)
                groups[series] = group_item

            display = doc["chapter_title"] if doc["chapter_title"] else doc["title"]
            progress = f"{doc['progress']}%"
            leaf = QTreeWidgetItem(groups[series], [display, progress])
            leaf.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._doc_ids[id(leaf)] = doc["id"]

        self._tree.expandAll()

    def _current_leaf(self) -> QTreeWidgetItem | None:
        item = self._tree.currentItem()
        if item is None or item.childCount() > 0:
            return None
        return item

    def _on_selection_changed(self) -> None:
        is_leaf = self._current_leaf() is not None
        self._open_btn.setEnabled(is_leaf)
        self._delete_btn.setEnabled(is_leaf)

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
        doc_id = self._doc_ids.pop(id(leaf))
        self._db.delete_document(doc_id)
        group = leaf.parent()
        group.removeChild(leaf)
        if group.childCount() == 0:
            self._tree.invisibleRootItem().removeChild(group)
        self._on_selection_changed()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        if item.childCount() > 0:
            return  # group header — ignore
        self._selected_doc_id = self._doc_ids[id(item)]
        self.accept()

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

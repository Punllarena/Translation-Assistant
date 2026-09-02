"""
Document picker dialog — two-panel layout with series list on left, chapter tree on right.
"""
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from translation_assistant.core import natural_key
from translation_assistant.db import Database

_NO_SERIES = "(No Series)"
_CHAPTER_HEADERS = ["#", "Title", "Progress", "Lines", "Images", "Last Edited", "WP", "Volume"]


class _ChapterTree(QTreeWidget):
    """QTreeWidget that notifies after an internal drag-drop reorder."""

    def __init__(self, on_reordered, parent=None) -> None:
        super().__init__(parent)
        self._on_reordered = on_reordered

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        if event.isAccepted():
            self._on_reordered()


class OpenDocumentDialog(QDialog):
    """
    Lists documents from the DB in a two-panel layout.
    Left panel: series list. Right panel: chapter tree (flat, 5 cols).
    User selects a chapter and clicks Open (or double-clicks).
    """

    _SORT_KEYS = {
        0: lambda item: item.data(0, Qt.ItemDataRole.UserRole) or 0,
        1: lambda item: item.text(1).lower(),
        2: lambda item: item.data(2, Qt.ItemDataRole.UserRole) or 0,
        3: lambda item: item.data(3, Qt.ItemDataRole.UserRole) or 0,
        4: lambda item: item.data(4, Qt.ItemDataRole.UserRole) or 0,
        5: lambda item: item.text(5),
        6: lambda item: item.text(6),
        7: lambda item: item.text(7).lower(),
    }

    def __init__(self, db: Database, parent=None, *,
                 current_doc_id: int | None = None,
                 settings=None) -> None:
        super().__init__(parent)
        self._db = db
        self._settings = settings
        self._selected_doc_id: int | None = None
        self._initial_doc_id = current_doc_id
        self.open_doc_merged_away = False
        self.open_doc_split = False
        self._doc_ids: dict[int, int] = {}  # id(QTreeWidgetItem) → doc_id
        self._source_urls: dict[int, str] = {}
        self._volume_titles: dict[int, str] = {}
        self._refetch_worker = None
        self._setup_ui()
        self._load_series()
        if current_doc_id is not None:
            self._select_doc(current_doc_id)
        else:
            self._restore_initial_series()

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

        self._tree = _ChapterTree(self._persist_tree_order)
        self._tree.setColumnCount(8)
        self._tree.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self._tree.setHeaderLabels(_CHAPTER_HEADERS)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionsClickable(True)
        self._tree.header().sectionClicked.connect(self._sort_chapters)
        # Volume is logical col 7 but displays right after "#"; a visual move keeps
        # every other column's logical index (and all the index-keyed code) unchanged.
        self._tree.header().moveSection(7, 1)
        self._tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
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
        self._edit_volume_btn = QPushButton("Edit Volume…")
        self._edit_volume_btn.setEnabled(False)
        self._edit_volume_btn.clicked.connect(self._on_edit_volume)
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
        for btn in (self._open_btn, self._edit_btn, self._edit_volume_btn, self._edit_source_btn,
                    self._delete_btn, self._refetch_btn, cancel_btn):
            btn_row.addWidget(btn)
        outer.addLayout(btn_row)

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
        self._sort_col = 0  # reset to default on series switch
        self._sort_asc = True
        self._tree.clear()
        self._doc_ids.clear()
        self._source_urls.clear()
        self._volume_titles.clear()

        docs = self._db.list_documents()
        docs = [d for d in docs if (d["series_title"] or "") == series_raw]
        docs.sort(key=lambda d: (d["series_order"], d["title"]))

        for doc in docs:
            display = doc["chapter_title"] if doc["chapter_title"] else doc["title"]
            progress_pct = doc["progress"]
            _wp_status = doc.get("wp_status") or ""
            _wp_badge = {"publish": "pub", "future": "sched"}.get(_wp_status, "")
            _wp_date = doc.get("wp_date") or ""
            if _wp_badge and _wp_date:
                _wp_cell = f"{_wp_badge} {_fmt_wp_date(_wp_date)}"
            else:
                _wp_cell = _wp_badge
            line_count = doc.get("line_count") or 0
            image_count = doc.get("image_count") or 0
            item = QTreeWidgetItem([
                str(doc["series_order"]),
                display,
                f"{progress_pct}%",
                str(line_count),
                str(image_count),
                _fmt_date(doc.get("updated_at", "")),
                _wp_cell,
                doc.get("volume_title", "") or "",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, doc["series_order"])
            item.setData(2, Qt.ItemDataRole.UserRole, progress_pct)
            item.setData(3, Qt.ItemDataRole.UserRole, line_count)
            item.setData(4, Qt.ItemDataRole.UserRole, image_count)
            # drops land between rows, never nest under an item
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setTextAlignment(4, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            if progress_pct == 0:
                item.setForeground(2, QColor("#888888"))
            elif progress_pct == 100:
                item.setForeground(2, QColor("#2a8a2a"))
            else:
                item.setForeground(2, QColor("#c8a000"))

            self._doc_ids[id(item)] = doc["id"]
            self._source_urls[id(item)] = doc.get("source_url", "")
            self._volume_titles[id(item)] = doc.get("volume_title", "")
            self._tree.addTopLevelItem(item)

        self._apply_filter(self._filter_edit.text())
        self._update_sort_header()

    def _restore_initial_series(self) -> None:
        last = self._settings.open_dialog_last_series if self._settings else ""
        if last:
            for i in range(self._series_list.count()):
                if self._series_list.item(i).data(Qt.ItemDataRole.UserRole) == last:
                    self._series_list.setCurrentRow(i)
                    return
        if self._series_list.count():
            self._series_list.setCurrentRow(0)

    def _on_series_selected(self, current, _prev) -> None:
        if current is None:
            self._tree.clear()
            self._doc_ids.clear()
            self._source_urls.clear()
            self._volume_titles.clear()
            return
        series_raw = current.data(Qt.ItemDataRole.UserRole)
        self._filter_edit.setText("")  # spec: filter clears on series switch
        self._load_chapters(series_raw)
        if self._settings:
            self._settings.open_dialog_last_series = series_raw

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

    def _persist_tree_order(self) -> None:
        """Save the current visual order as series_order 1..N (drag-drop)."""
        pairs = []
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            doc_id = self._doc_ids.get(id(item))
            if doc_id is None:
                continue
            order = i + 1
            pairs.append((doc_id, order))
            item.setText(0, str(order))
            item.setData(0, Qt.ItemDataRole.UserRole, order)
        self._db.set_series_orders(pairs)
        self._sort_col = 0  # drag defines the new canonical order
        self._sort_asc = True
        self._update_sort_header()

    def _renumber_by_title(self) -> None:
        """Rewrite series_order 1..N by natural title sort."""
        items = [self._tree.topLevelItem(i) for i in range(self._tree.topLevelItemCount())]
        items.sort(key=lambda it: natural_key(it.text(1)))
        pairs = [(self._doc_ids[id(it)], i + 1) for i, it in enumerate(items)]
        self._db.set_series_orders(pairs)
        series_raw = self._current_series_raw()
        if series_raw is not None:
            self._load_chapters(series_raw)

    def _on_chapter_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self._tree.setCurrentItem(item)
        merge_ids = self._selected_doc_ids()
        menu = QMenu(self)
        act_open = menu.addAction("Open")
        menu.addSeparator()
        act_edit = menu.addAction("Edit…")
        act_edit_src = menu.addAction("Edit Source…")
        menu.addSeparator()
        act_refetch = menu.addAction("Re-fetch")
        act_refetch.setEnabled(bool(self._source_urls.get(id(item), "")))
        act_renumber = menu.addAction("Renumber by Title")
        act_merge = menu.addAction("Merge Chapters")
        act_merge.setEnabled(len(merge_ids) >= 2)
        act_split = menu.addAction("Split Chapter…")
        act_split.setEnabled(len(merge_ids) <= 1)
        menu.addSeparator()
        act_delete = menu.addAction("Delete")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen == act_merge:
            self._on_merge()
        elif chosen == act_split:
            self._on_split()
        elif chosen == act_open:
            self._on_open()
        elif chosen == act_edit:
            self._on_edit()
        elif chosen == act_edit_src:
            self._on_edit_source()
        elif chosen == act_refetch:
            self._on_refetch()
        elif chosen == act_renumber:
            self._renumber_by_title()
        elif chosen == act_delete:
            self._on_delete()

    def _on_series_context_menu(self, pos) -> None:
        item = self._series_list.itemAt(pos)
        if item is None:
            return
        series_raw = item.data(Qt.ItemDataRole.UserRole)
        if series_raw == "":
            return  # no menu for (No Series)
        menu = QMenu(self)
        act = menu.addAction("Manage Series…")
        if menu.exec(self._series_list.viewport().mapToGlobal(pos)) == act:
            self._open_series_manager()

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
        has_volume = is_leaf and bool(self._volume_titles.get(id(leaf), ""))
        self._edit_volume_btn.setEnabled(has_volume)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_open(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        self._selected_doc_id = self._doc_ids[id(leaf)]
        self.accept()

    def _selected_doc_ids(self) -> list[int]:
        return [
            self._doc_ids[id(it)]
            for it in self._tree.selectedItems()
            if id(it) in self._doc_ids
        ]

    def _on_merge(self) -> None:
        doc_ids = self._selected_doc_ids()
        if len(doc_ids) < 2:
            return
        docs = sorted(
            (self._db.get_document(d) for d in doc_ids),
            key=lambda d: d["series_order"],
        )
        target = docs[0]

        def _name(d):
            return d["chapter_title"] or d["title"]

        published = [
            d for d in docs
            if (self._db.get_document_wp_status(d["id"]) or {}).get("wp_status")
        ]
        msg = (
            f"Merge these {len(docs)} chapters into one?\n\n"
            + " + ".join(_name(d) for d in docs)
            + f"\n\nThey are joined in this order and become "
            f'"{_name(target)}".'
        )
        if published:
            msg += (
                "\n\nWarning: one or more selected chapters is published to "
                "WordPress. Only the first chapter's WordPress post stays "
                "tracked here; the others' posts remain on the site but are no "
                "longer managed by this app."
            )
        if QMessageBox.question(
            self, "Merge Chapters", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        default_title = _name(target)
        new_title, ok = QInputDialog.getText(
            self, "Merge Chapters", "Merged chapter title:", text=default_title
        )
        if not ok:
            return
        new_title = new_title.strip() or default_title

        merged_id = self._db.merge_documents(doc_ids, new_title)
        if self._initial_doc_id in doc_ids and self._initial_doc_id != merged_id:
            self.open_doc_merged_away = True

        series_raw = self._current_series_raw()
        self._load_series()
        self._restore_series(series_raw)
        self._select_doc(merged_id)

    def _on_split(self) -> None:
        sel = self._selected_doc_ids()
        if len(sel) == 1:
            doc_id = sel[0]
        else:
            leaf = self._current_leaf()
            if leaf is None or id(leaf) not in self._doc_ids:
                return
            doc_id = self._doc_ids[id(leaf)]
        doc = self._db.get_document(doc_id)
        name = doc["chapter_title"] or doc["title"]
        dlg = _SplitChapterDialog(doc_id, name, self._db, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if not getattr(dlg, "_new_ids", None):
            return
        if self._initial_doc_id == doc_id:
            self.open_doc_split = True
        series_raw = self._current_series_raw()
        self._load_series()
        self._restore_series(series_raw)
        self._select_doc(doc_id)

    def _on_delete(self) -> None:
        leaves = [lf for lf in self._tree.selectedItems() if id(lf) in self._doc_ids]
        if not leaves:
            cur = self._current_leaf()
            leaves = [cur] if cur is not None and id(cur) in self._doc_ids else []
        if not leaves:
            return
        if len(leaves) == 1:
            prompt = f'Delete "{leaves[0].text(1)}"? This cannot be undone.'
        else:
            prompt = f"Delete these {len(leaves)} chapters? This cannot be undone."
        answer = QMessageBox.question(
            self,
            "Delete Document",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for lf in leaves:
            doc_id = self._doc_ids.pop(id(lf), None)
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

    def _on_edit_volume(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        doc_id = self._doc_ids[id(leaf)]
        doc = self._db.get_document(doc_id)
        dlg = _EditVolumeMetadataDialog(
            volume_title=doc["volume_title"],
            volume_author=doc["volume_author"],
            volume_illustrator=doc["volume_illustrator"],
            volume_publisher=doc["volume_publisher"],
            volume_identifier=doc["volume_identifier"],
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._do_edit_volume(
                doc_id, doc["series_title"], doc["volume_title"],
                new_volume_title=dlg.volume_title,
                volume_author=dlg.volume_author,
                volume_illustrator=dlg.volume_illustrator,
                volume_publisher=dlg.volume_publisher,
                volume_identifier=dlg.volume_identifier,
            )

    def _on_edit_source(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        doc_id = self._doc_ids[id(leaf)]
        dlg = _EditSourceDialog(doc_id, leaf.text(1), self._db, parent=self)
        if self._settings:
            from translation_assistant.ui import remember_dialog_geometry
            remember_dialog_geometry(dlg, self._settings, "dlg_edit_source")
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

    def _do_edit_volume(self, doc_id: int, series_title: str, old_volume_title: str, *,
                        new_volume_title: str, volume_author: str, volume_illustrator: str,
                        volume_publisher: str, volume_identifier: str) -> None:
        merge = False
        if new_volume_title != old_volume_title:
            existing = self._db.get_document_ids_by_volume(series_title, new_volume_title)
            if existing:
                from PySide6.QtWidgets import QMessageBox
                answer = QMessageBox.question(
                    self, "Merge Volumes",
                    f"'{new_volume_title}' already exists in this series with "
                    f"{len(existing)} chapter(s). Renaming will merge both volumes "
                    "together and apply this dialog's author/illustrator/publisher/ISBN "
                    "to all chapters in the merged volume. This cannot be undone. Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                merge = True
        self._db.update_volume_metadata(
            series_title, old_volume_title,
            new_volume_title=new_volume_title,
            volume_author=volume_author,
            volume_illustrator=volume_illustrator,
            volume_publisher=volume_publisher,
            volume_identifier=volume_identifier,
            merge=merge,
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
        dlg = SeriesManagerDialog(self._db, settings=self._settings, parent=self)
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


class _EditVolumeMetadataDialog(QDialog):
    def __init__(self, *, volume_title: str, volume_author: str, volume_illustrator: str,
                 volume_publisher: str, volume_identifier: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Volume Metadata")
        self.setMinimumWidth(380)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setSpacing(4)

        self._volume_edit = QLineEdit(volume_title)
        form.addRow("Volume Title:", self._volume_edit)

        self._author_edit = QLineEdit(volume_author)
        form.addRow("Author:", self._author_edit)

        self._illustrator_edit = QLineEdit(volume_illustrator)
        form.addRow("Illustrator:", self._illustrator_edit)

        self._publisher_edit = QLineEdit(volume_publisher)
        form.addRow("Publisher:", self._publisher_edit)

        self._identifier_edit = QLineEdit(volume_identifier)
        form.addRow("ISBN:", self._identifier_edit)

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

    def accept(self) -> None:
        if not self._volume_edit.text().strip():
            QMessageBox.warning(self, "Volume Title Required", "Volume Title cannot be empty.")
            return
        super().accept()

    @property
    def volume_title(self) -> str:
        return self._volume_edit.text().strip()

    @property
    def volume_author(self) -> str:
        return self._author_edit.text().strip()

    @property
    def volume_illustrator(self) -> str:
        return self._illustrator_edit.text().strip()

    @property
    def volume_publisher(self) -> str:
        return self._publisher_edit.text().strip()

    @property
    def volume_identifier(self) -> str:
        return self._identifier_edit.text().strip()


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


SPLIT_MARKER = "---CHAPTER SPLIT---"


class _SplitChapterDialog(QDialog):
    """Place ``SPLIT_MARKER`` lines to break one chapter into consecutive ones.

    One text line per original raw line. The *Insert Split Here* button drops a
    marker on its own line (type the new chapter's title right after it). Only
    marker positions matter — text edits here are ignored; use *Edit Source* to
    change wording. On save, cuts are handed to ``Database.split_document`` and
    the new document ids land in ``self._new_ids``.
    """

    def __init__(self, doc_id: int, doc_title: str, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._doc_id = doc_id
        self._db = db
        self._new_ids: list[int] = []
        self.setWindowTitle(f"Split Chapter — {doc_title}")
        self.setMinimumSize(500, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        hint = QLabel(
            "Place a split marker where each new chapter begins; type its title "
            "after the marker. Text edits here are ignored — use Edit Source to "
            "change wording."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._editor = QPlainTextEdit()
        editor_font = QFont("monospace")
        editor_font.setPointSize(10)
        self._editor.setFont(editor_font)
        self._editor.setPlainText(
            "\n".join(r["raw_text"] for r in self._db.get_lines(doc_id))
        )
        self._editor.textChanged.connect(self._update_save_enabled)
        layout.addWidget(self._editor)

        btn_row = QHBoxLayout()
        insert_btn = QPushButton("Insert Split Here")
        insert_btn.clicked.connect(self._insert_marker)
        self._save_btn = QPushButton("Split")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._on_split)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(insert_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._update_save_enabled()

    def _update_save_enabled(self) -> None:
        self._save_btn.setEnabled(SPLIT_MARKER in self._editor.toPlainText())

    def _insert_marker(self) -> None:
        c = self._editor.textCursor()
        c.movePosition(c.MoveOperation.StartOfBlock)
        c.insertText(SPLIT_MARKER + "\n")
        c.movePosition(c.MoveOperation.PreviousCharacter)  # back onto the marker line
        self._editor.setTextCursor(c)
        self._editor.setFocus()

    def _cuts(self) -> list[tuple[int, str]]:
        cuts: list[tuple[int, str]] = []
        n = 0  # count of real (non-marker) lines seen so far
        for raw in self._editor.toPlainText().split("\n"):
            s = raw.strip()
            if s == SPLIT_MARKER or s.startswith(SPLIT_MARKER):
                title = s[len(SPLIT_MARKER):].strip()
                if n >= 1 and (not cuts or cuts[-1][0] != n):
                    cuts.append((n, title))
            else:
                n += 1
        # a marker at/after the last real line is not a valid cut
        return [(pos, title) for pos, title in cuts if pos <= n - 1]

    def _on_split(self) -> None:
        cuts = self._cuts()
        if not cuts:
            QMessageBox.warning(
                self, "Split Chapter",
                "Place at least one split marker between two lines.",
            )
            return
        self._new_ids = self._db.split_document(self._doc_id, cuts)
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


def _fmt_wp_date(iso: str) -> str:
    """Format ISO 8601 WP date to compact M/D form."""
    if not iso:
        return ""
    try:
        dt = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%-m/%-d")
    except ValueError:
        return ""

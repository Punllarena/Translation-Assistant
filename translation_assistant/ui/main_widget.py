"""
TranslationAssistantWidget — all TA logic as a QWidget for embedding in CombinedMainWindow.
"""
from contextlib import contextmanager
import re
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QLabel, QMenu,
    QMessageBox, QPushButton, QSizePolicy, QSplitter, QStatusBar, QTextEdit, QVBoxLayout, QWidget,
)

from translation_assistant._version import BUILD_DATE
from translation_assistant.settings import AppSettings
from translation_assistant.spellcheck import SpellHighlighter

_CJK_FAMILIES = ["Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "sans-serif"]
_PUNCTUATIONS = ["「」", "『』", "【】", "…", "〜", "〈〉", "《》", "ー"]

_HELP_TOP = (
    "HOW TO USE:\n"
    "Creating New File for Translations:\n"
    "1.)Click File->New\n"
    "2.)Copy Raw from Source and paste it on the textbox\n"
    "3.)Click Create\n"
    "4.)Save File into the desired location\n"
    "5.)Translate\n"
    "6.)Once done translating click on Clipboard. Paste on your preferred editor or your blog for final edit and posting\n\n"
    "Creating New Profile\n"
    "1.)Click Settings->Profile\n"
    "2.)Click New Profile\n"
    "3.)Type profile name\n"
    "4.)Click OK\n\n"
    "Adding Phrases to Profile:\n"
    "Option 1:\n"
    "1.)Click Settings->Add Phrase\n"
    "2.)Enter Raw on Phrase textbox\n"
    "3.)Enter translation of phrase in Translation textbox\n"
    "4.)Click Save\n"
    "Option 2:\n"
    "1.)Click Settings->Profile\n"
    "2.)Add Raw text and Translated Test on their respective boxes at the end of table\n"
    "3.)Click Save\n\n"
    "Deleting Phrases\n"
    "1.)Click Settings->Profile\n"
    "2.)Double-Click phrase you want to delete\n"
    "3.)Confirm Delete\n"
    "4.)Click Save\n\n"
    "Editing Phrases\n"
    "1.)Click Settings->Profile\n"
    "2.)Click on a phrase, and click once again\n"
    "3.)Modify entry\n"
    "4.)Click Save\n\n"
    "Adding to Custom Dictionary\n"
    "1.)Highlight word to add to custom dictionary\n"
    "2.)Press CTRL+J\n\n"
    "Special Punctuations\n"
    "1.) Click the Special Punctuations menu or press F1-F8"
)

_HELP_BOTTOM = (
    "NAVIGATION CONTROLS:\n"
    "ENTER Key or PgDn Key  = Move down next sentence.\n"
    "PgUp Key = Move up to previous sentence\n"
    "CTRL+Left Key = Highlight previous parsed phrase in a sentence\n"
    "CTRL+Right Key = Highlight next parsed phrase in a sentence\n"
    "CTRL+Home Key = Go to the first line\n"
    "CTRL+End Key = Go to the most recent un-translated sentence"
)


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")


class ReviewTextEdit(QTextEdit):
    """Read-only review panel that emits the character offset on double-click."""

    line_double_clicked = Signal(int)

    def mouseDoubleClickEvent(self, event):
        click_pos = self.cursorForPosition(event.position().toPoint()).position()
        super().mouseDoubleClickEvent(event)
        self.line_double_clicked.emit(click_pos)


class TranslationAssistantWidget(QWidget):

    source_sentence_changed = Signal(str)

    def __init__(self, _settings: AppSettings | None = None, _db=None) -> None:
        super().__init__()
        self._settings = _settings if _settings is not None else AppSettings()
        self._db = _db

        # Document state
        self._raw_lines: list[str] = []
        self._translated_lines: list[str] = []
        self._raw_section: str = ""
        self._doc_id: int | None = None

        # Navigation state
        self._array_pointer: int = 0
        self._parse_sentences: list[str] = []
        self._parse_pointer: int = -1
        self._replaced: bool = False
        self._top_map: dict[int, tuple[int, int]] = {}
        self._bottom_map: dict[int, tuple[int, int]] = {}

        # Glossary / parse chars
        self._glossary: list[tuple[str, str]] = []
        self._parse_chars: list[str] = []

        # Progress
        self._tl_complete: int = 0

        self._build_actions()
        self._setup_central_widget()
        self._setup_statusbar()
        self._setup_timers()
        self._load_initial_state()

    # ------------------------------------------------------------------
    # Action construction (CombinedMainWindow puts these in its menu bar)
    # ------------------------------------------------------------------

    def _build_actions(self) -> None:
        self.action_new_doc = QAction("New Document (CTRL+N)", self)
        self.action_new_doc.triggered.connect(self._on_new_doc)
        self.action_new_doc.setShortcut("Ctrl+N")

        self.action_new_series = QAction("New Series", self)
        self.action_new_series.triggered.connect(self._on_new_series)

        self.action_open = QAction("Open (CTRL+O)", self)
        self.action_open.triggered.connect(self._on_open)
        self.action_open.setShortcut("Ctrl+O")

        self.action_import = QAction("Import from file…", self)
        self.action_import.triggered.connect(self._on_import)

        self.action_batch_import = QAction("Import Folder…", self)
        self.action_batch_import.triggered.connect(self._on_batch_import)

        self.action_save = QAction("Save (CTRL+S)", self)
        self.action_save.triggered.connect(self._on_save)
        self.action_save.setShortcut("Ctrl+S")
        self.action_save.setEnabled(False)

        self.action_export = QAction("Export to file…", self)
        self.action_export.triggered.connect(self._on_export)
        self.action_export.setEnabled(False)

        self.action_manage_series = QAction("Manage Series…", self)
        self.action_manage_series.triggered.connect(self._on_manage_series)

        self.action_db_export = QAction("Export Database Backup…", self)
        self.action_db_export.triggered.connect(self._on_db_export)

        self.action_db_import = QAction("Import Database Backup…", self)
        self.action_db_import.triggered.connect(self._on_db_import)

        self.action_profile = QAction("Profile (CTRL+P)", self)
        self.action_profile.triggered.connect(self._on_profile)
        self.action_profile.setShortcut("Ctrl+P")

        self.action_phrase = QAction("Phrase (CTRL+L)", self)
        self.action_phrase.triggered.connect(self._on_phrase)
        self.action_phrase.setShortcut("Ctrl+L")

        self.action_progress = QAction("Show Progress", self)
        self.action_progress.setCheckable(True)
        self.action_progress.setChecked(self._settings.show_progress)
        self.action_progress.triggered.connect(self._on_toggle_progress)

        self.action_tm = QAction("Show Translation Memory", self)
        self.action_tm.setCheckable(True)
        self.action_tm.setChecked(self._settings.tm_visible)
        self.action_tm.triggered.connect(self._on_toggle_tm)

        self.action_go_to_line = QAction("Go to Line… (Ctrl+G)", self)
        self.action_go_to_line.setShortcut("Ctrl+G")
        self.action_go_to_line.triggered.connect(self._on_go_to_line)
        self.action_go_to_line.setEnabled(False)

        self.action_on_top = QAction("Always On Top", self)
        self.action_on_top.setCheckable(True)
        self.action_on_top.setChecked(self._settings.on_top)
        self.action_on_top.triggered.connect(self._on_toggle_on_top)

        self.action_tts_jp = QAction("Japanese", self)
        self.action_tts_jp.setCheckable(True)
        self.action_tts_jp.setEnabled(False)
        self.action_tts_jp.triggered.connect(self._on_toggle_tts_jp)

        self.action_tts_cn = QAction("Chinese", self)
        self.action_tts_cn.setCheckable(True)
        self.action_tts_cn.setEnabled(False)
        self.action_tts_cn.triggered.connect(self._on_toggle_tts_cn)

        self.action_clipboard = QAction("Clipboard (CTRL+I)", self)
        self.action_clipboard.triggered.connect(self._on_clipboard_export)
        self.action_clipboard.setShortcut("Ctrl+I")
        self.action_clipboard.setEnabled(False)

        self.action_about = QAction("About", self)
        self.action_about.triggered.connect(self._on_about)

        self.action_export_md_tl_doc = QAction("Export Markdown (Translation)…", self)
        self.action_export_md_tl_doc.triggered.connect(self._on_export_md_tl_doc)
        self.action_export_md_tl_doc.setEnabled(False)

        self.action_export_md_ruby_doc = QAction("Export Markdown (Ruby)…", self)
        self.action_export_md_ruby_doc.triggered.connect(self._on_export_md_ruby_doc)
        self.action_export_md_ruby_doc.setEnabled(False)

        self.action_export_md_tl_series = QAction("Export Series Markdown (Translation)…", self)
        self.action_export_md_tl_series.triggered.connect(self._on_export_md_tl_series)
        self.action_export_md_tl_series.setEnabled(False)

        self.action_export_md_ruby_series = QAction("Export Series Markdown (Ruby)…", self)
        self.action_export_md_ruby_series.triggered.connect(self._on_export_md_ruby_series)
        self.action_export_md_ruby_series.setEnabled(False)

        # Build punctuation actions list (CombinedMainWindow puts these in a submenu)
        _punct_labels = [
            "Single Quote : 「　」  (F1)",
            "Double Quote : 『　』  (F2)",
            "Lenticular : 【　】  (F3)",
            "Ellipsis : …  (F4)",
            "Wave Dash : 〜  (F5)",
            "Single Title Bracket : 〈 〉  (F6)",
            "Double Title Bracket : 《 》  (F7)",
            "Long Dash : ー  (F8)",
        ]
        self.punct_actions: list[QAction] = []
        for i, label in enumerate(_punct_labels):
            act = QAction(label, self)
            act.setShortcut(f"F{i + 1}")
            act.triggered.connect(lambda checked, idx=i: self._insert_punctuation(idx))
            self.punct_actions.append(act)

    # ------------------------------------------------------------------
    # Widget setup
    # ------------------------------------------------------------------

    def _setup_central_widget(self) -> None:
        font = QFont()
        font.setFamilies(_CJK_FAMILIES)
        font.setPointSizeF(12.5)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 0)
        layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setChildrenCollapsible(False)

        self._review_top = ReviewTextEdit()
        self._review_top.setReadOnly(True)
        self._review_top.setFont(font)
        self._review_top.setPlainText(_HELP_TOP)
        self._review_top.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._review_top.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._review_top.setMinimumHeight(50)
        self._review_top.line_double_clicked.connect(self._on_review_top_double_click)
        self._splitter.addWidget(self._review_top)

        self._raw_line = QTextEdit()
        self._raw_line.setReadOnly(True)
        self._raw_line.setFont(font)
        self._raw_line.setMinimumHeight(40)
        self._raw_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._splitter.addWidget(self._raw_line)

        self._tm_panel = QWidget()
        self._tm_panel.setMinimumHeight(0)
        self._tm_layout = QVBoxLayout(self._tm_panel)
        self._tm_layout.setContentsMargins(2, 2, 2, 2)
        self._tm_layout.setSpacing(2)
        self._tm_panel.setVisible(False)
        self._splitter.addWidget(self._tm_panel)

        self._translated_line = QTextEdit()
        self._translated_line.setFont(font)
        self._translated_line.setMinimumHeight(40)
        self._translated_line.setAcceptRichText(False)
        self._translated_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._translated_line.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._translated_line.customContextMenuRequested.connect(self._on_translated_context_menu)
        self._splitter.addWidget(self._translated_line)
        self._spell_highlighter = SpellHighlighter(self._translated_line.document())

        self._review_bottom = ReviewTextEdit()
        self._review_bottom.setReadOnly(True)
        self._review_bottom.setFont(font)
        self._review_bottom.setPlainText(_HELP_BOTTOM)
        self._review_bottom.setMinimumHeight(50)
        self._review_bottom.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._review_bottom.line_double_clicked.connect(self._on_review_bottom_double_click)
        self._splitter.addWidget(self._review_bottom)

        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setStretchFactor(3, 0)
        self._splitter.setStretchFactor(4, 0)

        saved = self._settings.splitter_state
        if not saved.isEmpty():
            self._splitter.restoreState(saved)
        else:
            self._splitter.setSizes([300, 52, 0, 52, 137])

        layout.addWidget(self._splitter)

        for widget in (self._review_top, self._raw_line,
                       self._translated_line, self._review_bottom):
            widget.installEventFilter(self)

    def _setup_statusbar(self) -> None:
        self._status_bar = QStatusBar()
        layout = self.layout()
        layout.addWidget(self._status_bar)

        self._completion_label = QLabel("0% Complete")
        self._line_label = QLabel("Line: xxxx/xxxx")
        self._word_label = QLabel("xxxx Words")
        self._filesaved_label = QLabel("")
        self._status_bar.addWidget(self._completion_label)
        self._status_bar.addWidget(self._line_label)
        self._status_bar.addWidget(self._word_label)
        self._status_bar.addPermanentWidget(self._filesaved_label)
        self._update_progress_visibility()

    def _setup_timers(self) -> None:
        self._clipboard_timer = QTimer(self)
        self._clipboard_timer.setSingleShot(True)
        self._clipboard_timer.setInterval(400)
        self._clipboard_timer.timeout.connect(self._on_clipboard_timer)

        self._filesaved_timer = QTimer(self)
        self._filesaved_timer.setSingleShot(True)
        self._filesaved_timer.setInterval(2000)
        self._filesaved_timer.timeout.connect(lambda: self._filesaved_label.setText(""))

        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._on_autosave_timer)

    def _load_initial_state(self) -> None:
        self._update_parse_chars()
        self._load_glossary_for_profile()
        self._load_spell_dict()
        self._try_init_tts()
        last = self._settings.last_doc_id
        if last is not None:
            try:
                self.open_document(last)
            except (ValueError, Exception):
                pass

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def _update_parse_chars(self) -> None:
        self._parse_chars = [c for c in self._settings.parse_char.split(" ") if c]

    def _load_glossary_for_profile(self) -> None:
        profile_name = self._settings.profile_used
        if self._db.get_profile_id(profile_name) is None:
            if self._db.get_profile_id("Default") is None:
                self._db.create_profile("Default", is_default=True)
            self._settings.profile_used = "Default"
            self._settings.save()
            profile_name = "Default"
        self._glossary = self._db.get_glossary(profile_name)

    def _load_spell_dict(self) -> None:
        words = self._db.get_custom_words(self._settings.profile_used)
        self._spell_highlighter.load_custom_words_list(words)

    def _try_init_tts(self) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            for v in (voices or []):
                name = getattr(v, "name", "")
                if "ja" in name.lower() or "japanese" in name.lower() or "haruka" in name.lower():
                    self.action_tts_jp.setEnabled(True)
                elif "zh" in name.lower() or "chinese" in name.lower() or "huihui" in name.lower():
                    self.action_tts_cn.setEnabled(True)
            engine.stop()
            self._tts_engine = engine
        except Exception:
            self._tts_engine = None

    # ------------------------------------------------------------------
    # Content loading
    # ------------------------------------------------------------------

    def load_content(self, text: str, *, title: str = "Untitled",
                     series_title: str = "", series_order: int = 0,
                     chapter_title: str = "", source_url: str = "") -> None:
        from translation_assistant.core import parse_file_content
        raw_lines, translated_lines, raw_section = parse_file_content(text)
        self._raw_lines = raw_lines
        self._translated_lines = translated_lines
        self._raw_section = raw_section
        self._array_pointer = 0

        doc_id = self._db.create_document(
            title,
            series_title=series_title,
            series_order=series_order,
            chapter_title=chapter_title,
            source_url=source_url,
        )
        self._db.save_lines(doc_id, self._lines_as_db_rows())
        self._doc_id = doc_id
        if series_title:
            linked = self._db.get_series_profile(series_title)
            if linked and self._db.get_profile_id(linked) is not None:
                self._settings.profile_used = linked
                self._load_glossary_for_profile()
        self._finish_load()

    def open_document(self, doc_id: int) -> None:
        rows = self._db.get_lines(doc_id)
        self._raw_lines = [r["prefix"] + r["raw_text"] for r in rows]
        self._translated_lines = [r["translated_text"] for r in rows]
        self._raw_section = ""
        self._doc_id = doc_id
        doc = self._db.get_document(doc_id)
        pos = doc["last_position"]
        self._array_pointer = min(pos, max(0, len(self._raw_lines) - 1))
        series = doc.get("series_title", "")
        if series:
            linked = self._db.get_series_profile(series)
            if linked and self._db.get_profile_id(linked) is not None:
                self._settings.profile_used = linked
                self._load_glossary_for_profile()
        self._finish_load()

    def _lines_as_db_rows(self) -> list[dict]:
        from translation_assistant.core import lines_to_db_rows
        return lines_to_db_rows(self._raw_lines, self._translated_lines)

    def _finish_load(self) -> None:
        from translation_assistant.core import (
            replace_and_parse, build_review_text, calculate_progress,
        )
        raw_lines = self._raw_lines
        translated_lines = self._translated_lines
        p = self._array_pointer

        self._top_map = {}
        self._bottom_map = {}
        self._review_top.clear()

        display, sentences, replaced = replace_and_parse(
            raw_lines[p], self._glossary, self._parse_chars
        )
        self._raw_line.setPlainText(display)
        self._translated_line.setPlainText(translated_lines[p])
        self._parse_sentences = sentences
        self._parse_pointer = -1
        self._replaced = replaced

        n = len(raw_lines)
        if p + 1 < n:
            bottom_text, self._bottom_map = build_review_text(
                raw_lines, translated_lines, p + 1, n - 1
            )
        else:
            bottom_text = ""
            self._bottom_map = {}
        self._review_bottom.setPlainText(bottom_text)

        if p > 0:
            top_text, self._top_map = build_review_text(raw_lines, translated_lines, 0, p - 1)
            self._review_top.setPlainText(top_text)

        self._line_label.setText(f"Line: {p + 1}/{n}")
        pct, wc = calculate_progress(raw_lines, translated_lines)
        self._tl_complete = pct
        self._completion_label.setText(f"{pct}% Complete")
        self._word_label.setText(f"{wc} Words")

        self.action_save.setEnabled(True)
        self.action_export.setEnabled(True)
        self.action_clipboard.setEnabled(True)
        self.action_go_to_line.setEnabled(True)
        self.action_export_md_tl_doc.setEnabled(True)
        self.action_export_md_ruby_doc.setEnabled(True)
        _doc_meta = self._db.get_document(self._doc_id)
        _has_series = bool(_doc_meta.get("series_title", ""))
        self.action_export_md_tl_series.setEnabled(_has_series)
        self.action_export_md_ruby_series.setEnabled(_has_series)
        self._translated_line.setFocus()
        self._start_clipboard_timer()
        self._restart_autosave_timer()

        # Emit so the Aggregator translates the first sentence on load
        raw = self._raw_lines[p]
        self.source_sentence_changed.emit(raw.lstrip("%$").strip())

    def _save_to_db(self) -> None:
        if self._doc_id is None:
            return
        self._db.save_lines(self._doc_id, self._lines_as_db_rows())
        self._filesaved_label.setText("File saved....")
        self._filesaved_timer.start()

    # ------------------------------------------------------------------
    # UI update helpers
    # ------------------------------------------------------------------

    def _update_ui_for_pointer(self) -> None:
        from translation_assistant.core import (
            replace_and_parse, build_review_text, calculate_progress,
        )
        p = self._array_pointer
        n = len(self._raw_lines)

        if p > 0:
            top_text, self._top_map = build_review_text(
                self._raw_lines, self._translated_lines, 0, p - 1
            )
        else:
            top_text, self._top_map = "", {}
        self._review_top.setPlainText(top_text)
        self._review_top.moveCursor(QTextCursor.MoveOperation.End)

        display, sentences, replaced = replace_and_parse(
            self._raw_lines[p], self._glossary, self._parse_chars
        )
        self._raw_line.setPlainText(display)
        self._translated_line.setPlainText(self._translated_lines[p])
        self._parse_sentences = sentences
        self._parse_pointer = -1
        self._replaced = replaced

        if p < n - 1:
            bottom_text, self._bottom_map = build_review_text(
                self._raw_lines, self._translated_lines, p + 1, n - 1
            )
        else:
            bottom_text, self._bottom_map = "", {}
        self._review_bottom.setPlainText(bottom_text)
        cursor = self._review_bottom.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self._review_bottom.setTextCursor(cursor)

        self._line_label.setText(f"Line: {p + 1}/{n}")
        pct, wc = calculate_progress(self._raw_lines, self._translated_lines)
        self._tl_complete = pct
        self._completion_label.setText(f"{pct}% Complete")
        self._word_label.setText(f"{wc} Words")
        self._translated_line.setFocus()
        self._start_clipboard_timer()

        raw = self._raw_lines[p]
        self.source_sentence_changed.emit(raw.lstrip("%$").strip())
        self._update_tm_panel()

    def _update_tm_panel(self) -> None:
        while self._tm_layout.count():
            item = self._tm_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._raw_lines or not self._settings.tm_visible:
            self._tm_panel.setVisible(False)
            return

        p = self._array_pointer
        raw = self._raw_lines[p]
        raw_text = raw[1:] if raw and raw[0] in ('%', '$') else raw
        matches = self._db.find_tm_matches(raw_text, self._doc_id)

        if not matches:
            self._tm_panel.setVisible(False)
            return

        self._tm_panel.setVisible(True)
        for m in matches:
            date_str = m["updated_at"][:10] if m.get("updated_at") else ""
            label = f"{m['translated_text']}  —  {m['doc_title']}, {date_str}"
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setStyleSheet("text-align: left; padding: 2px 4px;")
            translation = m["translated_text"]
            btn.clicked.connect(
                lambda checked, t=translation: self._translated_line.setPlainText(t)
            )
            self._tm_layout.addWidget(btn)

    def _update_progress_visibility(self) -> None:
        visible = self._settings.show_progress
        self._completion_label.setVisible(visible)
        self._line_label.setVisible(visible)
        self._word_label.setVisible(visible)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _save_current_translation(self) -> None:
        if not self._raw_lines:
            return
        text = self._translated_line.toPlainText()
        self._translated_lines[self._array_pointer] = text
        if self._doc_id is not None:
            self._db.save_translation(self._doc_id, self._array_pointer, text)

    def _navigate_forward(self, write_file: bool = False) -> None:
        if not self._raw_lines:
            return
        self._clipboard_timer.stop()
        self._save_current_translation()

        from translation_assistant.core import line_has_content
        n = len(self._raw_lines)
        eof = False
        p = self._array_pointer
        while True:
            if p < n - 1:
                p += 1
                if line_has_content(self._raw_lines[p]):
                    break
            else:
                eof = True
                break

        self._array_pointer = p
        if not eof:
            self._update_ui_for_pointer()
        else:
            self._line_label.setText(f"Line: {p + 1}/{n}")
            from translation_assistant.core import calculate_progress
            pct, wc = calculate_progress(self._raw_lines, self._translated_lines)
            self._tl_complete = pct
            self._completion_label.setText(f"{pct}% Complete")
            self._word_label.setText(f"{wc} Words")

        if write_file:
            self._save_current_translation()
            if self._doc_id is not None:
                self._save_to_db()

        self._translated_line.setFocus()

    def _navigate_backward(self) -> None:
        if not self._raw_lines:
            return
        self._clipboard_timer.stop()
        self._save_current_translation()

        from translation_assistant.core import line_has_content
        p = self._array_pointer
        eof = False
        while True:
            if p == 0:
                eof = True
                break
            p -= 1
            if line_has_content(self._raw_lines[p]):
                break

        self._array_pointer = p
        if not eof:
            self._update_ui_for_pointer()
        else:
            n = len(self._raw_lines)
            self._line_label.setText(f"Line: {p + 1}/{n}")

        self._translated_line.setFocus()

    def _jump_to_first(self) -> None:
        if not self._raw_lines or self._array_pointer == 0:
            return
        self._clipboard_timer.stop()
        self._save_current_translation()
        self._array_pointer = 0
        self._update_ui_for_pointer()
        self._translated_line.setFocus()

    def _jump_to_next_untranslated(self) -> None:
        if not self._raw_lines:
            return
        if not self._translated_line.toPlainText():
            return
        self._clipboard_timer.stop()
        self._save_current_translation()
        from translation_assistant.core import calculate_progress
        pct, wc = calculate_progress(self._raw_lines, self._translated_lines)
        self._tl_complete = pct
        if pct == 100:
            return
        from translation_assistant.core import line_has_content
        n = len(self._raw_lines)
        for i in range(n):
            if line_has_content(self._raw_lines[i]) and not self._translated_lines[i]:
                self._array_pointer = i
                self._update_ui_for_pointer()
                break
        self._translated_line.setFocus()

    # ------------------------------------------------------------------
    # Parse navigation
    # ------------------------------------------------------------------

    def _advance_parse(self) -> None:
        if not self._raw_lines:
            return
        self._clipboard_timer.stop()
        count = len(self._parse_sentences)
        if self._parse_pointer + 1 < count:
            self._parse_pointer += 1
        if self._parse_pointer == -1:
            from translation_assistant.core import replace_and_parse
            display, sentences, replaced = replace_and_parse(
                self._raw_lines[self._array_pointer], self._glossary, self._parse_chars
            )
            self._raw_line.setPlainText(display)
            self._parse_sentences = sentences
            self._replaced = replaced
        else:
            self._highlight_parse_sentence(self._parse_pointer)
        self._start_clipboard_timer()
        self._translated_line.setFocus()

    def _retreat_parse(self) -> None:
        if not self._raw_lines:
            return
        self._clipboard_timer.stop()
        if self._parse_pointer - 1 >= -1 and not self._replaced:
            self._parse_pointer -= 1
        elif self._parse_pointer - 1 >= -2 and self._replaced:
            self._parse_pointer -= 1

        if self._parse_pointer == -1:
            cursor = self._raw_line.textCursor()
            cursor.clearSelection()
            self._raw_line.setTextCursor(cursor)
        elif self._parse_pointer == -2:
            raw = self._raw_lines[self._array_pointer]
            self._raw_line.setPlainText(raw.replace("$", "").replace("%", ""))
        else:
            self._highlight_parse_sentence(self._parse_pointer)
        self._start_clipboard_timer()
        self._translated_line.setFocus()

    def _highlight_parse_sentence(self, idx: int) -> None:
        text = self._raw_line.toPlainText()
        sentence = self._parse_sentences[idx]
        pos = text.find(sentence)
        if pos < 0:
            return
        cursor = self._raw_line.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(pos + len(sentence), QTextCursor.MoveMode.KeepAnchor)
        self._raw_line.setTextCursor(cursor)

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

    def _start_clipboard_timer(self) -> None:
        self._clipboard_timer.stop()
        self._clipboard_timer.start()

    def _on_clipboard_timer(self) -> None:
        selected = self._raw_line.textCursor().selectedText()
        text = selected if selected else self._raw_line.toPlainText()
        QApplication.clipboard().setText(text)

    def _restart_autosave_timer(self) -> None:
        minutes = self._settings.auto_save
        if minutes > 0:
            self._autosave_timer.setInterval(minutes * 60_000)
            self._autosave_timer.start()
        else:
            self._autosave_timer.stop()

    def _on_autosave_timer(self) -> None:
        if not self._raw_lines:
            return
        self._save_current_translation()
        if self._doc_id is not None:
            self._save_to_db()

    def _on_clipboard_export(self) -> None:
        if not self._raw_lines:
            return
        do_copy = False
        if self._tl_complete == 100:
            do_copy = True
        else:
            reply = QMessageBox.question(
                self, "Incomplete Translation",
                "Translation is not complete. Copy anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            do_copy = reply == QMessageBox.StandardButton.Yes

        if do_copy:
            from translation_assistant.core import build_clipboard_output
            self._save_current_translation()
            text = build_clipboard_output(self._raw_lines, self._translated_lines)
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Clipboard", "Copy to Clipboard Done")

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        if not self._raw_lines:
            return
        self._save_current_translation()
        if self._doc_id is not None:
            self._save_to_db()

    def _on_new_doc(self) -> None:
        from translation_assistant.ui.dlg_new import NewFileDialog
        with self._topmost_suspended():
            dlg = NewFileDialog(self._db, parent=self)
            if dlg.exec():
                display = dlg.chapter_title or "New Document"
                self.load_content(
                    dlg.raw_output_text,
                    title=display,
                    series_title=dlg.series_title,
                    series_order=dlg.series_order,
                    chapter_title=dlg.chapter_title,
                    source_url=dlg.source_url,
                )

    def _on_new_series(self) -> None:
        if self._db is None:
            QMessageBox.warning(self, "New Series", "No database open.")
            return
        from translation_assistant.ui.dlg_new_series import NewSeriesDialog
        from translation_assistant.ui.dlg_series import SeriesManagerDialog
        with self._topmost_suspended():
            dlg = NewSeriesDialog(self._db, parent=self)
            if dlg.exec():
                dlg2 = SeriesManagerDialog(self._db, parent=self)
                dlg2.exec()

    def _on_open(self) -> None:
        from translation_assistant.ui.dlg_open import OpenDocumentDialog
        with self._topmost_suspended():
            dlg = OpenDocumentDialog(self._db, parent=self, current_doc_id=self._doc_id)
            if dlg.exec() and dlg.selected_doc_id is not None:
                self.open_document(dlg.selected_doc_id)

    def _on_import(self) -> None:
        with self._topmost_suspended():
            filepath, _ = QFileDialog.getOpenFileName(
                self, "Import Translation File", "", "Text Files (*.txt)"
            )
        if not filepath:
            return
        text = Path(filepath).read_text(encoding="utf-8")
        if "---SEPERATOR---" not in text:
            QMessageBox.critical(
                self, "File Error",
                "The file you have chosen is not supported by this app."
            )
            return
        self.load_content(text, title=Path(filepath).stem)

    def _on_batch_import(self) -> None:
        from translation_assistant.ui.dlg_batch_import import BatchImportDialog
        with self._topmost_suspended():
            dlg = BatchImportDialog(self._db, self._settings, parent=self)
            dlg.exec()

    def _on_export(self) -> None:
        if not self._raw_lines:
            return
        self._save_current_translation()
        with self._topmost_suspended():
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Export Translation File", "", "Text Files (*.txt)"
            )
        if not filepath:
            return
        from translation_assistant.core import export_txt
        self._save_to_db()
        export_txt(self._doc_id, Path(filepath), self._db)
        self._filesaved_label.setText("File exported....")
        self._filesaved_timer.start()

    def _export_md_doc(self, builder) -> None:
        if not self._raw_lines:
            return
        self._save_current_translation()
        with self._topmost_suspended():
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Export Markdown", "", "Markdown (*.md)"
            )
        if not filepath:
            return
        meta = self._db.get_document(self._doc_id)
        title = meta.get("chapter_title") or meta.get("title", "")
        result = builder(self._raw_lines, self._translated_lines, title)
        Path(filepath).write_text(result, encoding="utf-8")
        QMessageBox.information(self, "Export Complete", f"Markdown saved to:\n{filepath}")

    def _export_md_series(self, builder) -> None:
        if self._doc_id is None:
            return
        meta = self._db.get_document(self._doc_id)
        series_title = meta.get("series_title", "")
        if not series_title:
            return
        with self._topmost_suspended():
            folder = QFileDialog.getExistingDirectory(
                self, f"Export Series: {series_title}"
            )
        if not folder:
            return
        from translation_assistant.core import db_rows_to_arrays
        doc_ids = self._db.get_document_ids_by_series(series_title)
        written = 0
        skipped = 0
        for doc_id in doc_ids:
            doc_meta = self._db.get_document(doc_id)
            rows = self._db.get_lines(doc_id)
            raw_lines, translated_lines = db_rows_to_arrays(rows)
            heading = doc_meta.get("chapter_title") or doc_meta.get("title", "")
            stem = _sanitize_filename(doc_meta.get("title") or f"doc_{doc_id}")
            filename = f"{doc_meta['series_order']:03d} - {stem}.md"
            dest = Path(folder) / filename
            if dest.exists():
                skipped += 1
                continue
            result = builder(raw_lines, translated_lines, heading)
            dest.write_text(result, encoding="utf-8")
            written += 1
        QMessageBox.information(
            self, "Export Complete",
            f"Exported {written} file(s) to:\n{folder}\n\n"
            f"{skipped} file(s) skipped (already exist).",
        )

    def _on_export_md_tl_doc(self) -> None:
        from translation_assistant.core import build_markdown_translation
        self._export_md_doc(build_markdown_translation)

    def _on_export_md_ruby_doc(self) -> None:
        from translation_assistant.core import build_markdown_ruby
        self._export_md_doc(build_markdown_ruby)

    def _on_export_md_tl_series(self) -> None:
        from translation_assistant.core import build_markdown_translation
        self._export_md_series(build_markdown_translation)

    def _on_export_md_ruby_series(self) -> None:
        from translation_assistant.core import build_markdown_ruby
        self._export_md_series(build_markdown_ruby)

    def _on_db_export(self) -> None:
        import shutil
        with self._topmost_suspended():
            dest, _ = QFileDialog.getSaveFileName(
                self, "Export Database Backup", "ta_backup.db", "SQLite Database (*.db)"
            )
        if not dest:
            return
        self._save_current_translation()
        self._save_to_db()
        shutil.copy2(self._settings.db_path, dest)
        self._filesaved_label.setText("Database exported.")
        self._filesaved_timer.start()

    def _on_db_import(self) -> None:
        import shutil
        from translation_assistant.db import Database
        with self._topmost_suspended():
            src, _ = QFileDialog.getOpenFileName(
                self, "Import Database Backup", "", "SQLite Database (*.db)"
            )
        if not src:
            return
        confirm = QMessageBox.question(
            self, "Import Database",
            "This will replace the current database with the selected backup.\n"
            "Any unsaved changes will be lost. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._db.close()
        shutil.copy2(src, self._settings.db_path)
        self._db = Database(self._settings.db_path)
        self._doc_id = None
        self._raw_lines = []
        self._translated_lines = []
        self._raw_section = ""
        self._array_pointer = 0
        self._parse_sentences = []
        self._parse_pointer = -1
        self._review_top.setPlainText(_HELP_TOP)
        self._review_bottom.setPlainText(_HELP_BOTTOM)
        self._raw_line.clear()
        self._translated_line.clear()
        self.action_save.setEnabled(False)
        self.action_export.setEnabled(False)
        self._load_glossary_for_profile()
        self._filesaved_label.setText("Database imported.")
        self._filesaved_timer.start()

    def _on_manage_series(self) -> None:
        from translation_assistant.ui.dlg_series import SeriesManagerDialog
        with self._topmost_suspended():
            dlg = SeriesManagerDialog(self._db, parent=self)
            dlg.exec()

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------

    def _on_profile(self) -> None:
        from translation_assistant.ui.dlg_profile import ProfileDialog
        with self._topmost_suspended():
            dlg = ProfileDialog(self._settings, self._db, parent=self)
            if dlg.exec():
                self._update_parse_chars()
                self._glossary = self._db.get_glossary(self._settings.profile_used)
                self._load_spell_dict()
                if self._raw_lines:
                    from translation_assistant.core import replace_and_parse
                    display, sentences, replaced = replace_and_parse(
                        self._raw_lines[self._array_pointer],
                        self._glossary, self._parse_chars,
                    )
                    self._raw_line.setPlainText(display)
                    self._parse_sentences = sentences
                    self._replaced = replaced
                    self._start_clipboard_timer()

    def _on_phrase(self) -> None:
        from translation_assistant.ui.dlg_phrase import PhraseDialog
        with self._topmost_suspended():
            dlg = PhraseDialog(self._db, self._settings.profile_used, parent=self)
            if dlg.exec():
                self._glossary = self._db.get_glossary(self._settings.profile_used)
                if self._raw_lines:
                    from translation_assistant.core import replace_and_parse
                    display, sentences, replaced = replace_and_parse(
                        self._raw_lines[self._array_pointer],
                        self._glossary, self._parse_chars,
                    )
                    self._raw_line.setPlainText(display)
                    self._parse_sentences = sentences
                    self._replaced = replaced
                    self._start_clipboard_timer()

    # ------------------------------------------------------------------
    # Settings toggles
    # ------------------------------------------------------------------

    def _on_toggle_progress(self) -> None:
        self._settings.show_progress = self.action_progress.isChecked()
        self._settings.save()
        self._update_progress_visibility()

    def _on_toggle_tm(self) -> None:
        self._settings.tm_visible = self.action_tm.isChecked()
        self._settings.save()
        self._update_tm_panel()

    def _on_go_to_line(self) -> None:
        if not self._raw_lines:
            return
        n = len(self._raw_lines)
        line_num, ok = QInputDialog.getInt(
            self,
            "Go to Line",
            f"Line number (1–{n}):",
            value=self._array_pointer + 1,
            min=1,
            max=n,
        )
        if not ok:
            return
        self._clipboard_timer.stop()
        self._save_current_translation()
        self._array_pointer = line_num - 1
        self._update_ui_for_pointer()
        self._translated_line.setFocus()

    def _on_toggle_on_top(self) -> None:
        enabled = self.action_on_top.isChecked()
        self._settings.on_top = enabled
        self._settings.save()
        # Delegate to parent window
        parent = self.window()
        if parent and parent is not self:
            flags = parent.windowFlags()
            if enabled:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint
            parent.setWindowFlags(flags)
            parent.show()

    def _on_toggle_tts_jp(self) -> None:
        if self.action_tts_jp.isChecked():
            self.action_tts_cn.setChecked(False)
            self._settings.tts = True
            self._settings.tts_lang = 0
        else:
            self._settings.tts = False
        self._settings.save()

    def _on_toggle_tts_cn(self) -> None:
        if self.action_tts_cn.isChecked():
            self.action_tts_jp.setChecked(False)
            self._settings.tts = True
            self._settings.tts_lang = 1
        else:
            self._settings.tts = False
        self._settings.save()

    def _on_about(self) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle("About")
        msg.setText(
            "Programmed by: Pun<br>"
            "Port of joeglens's Translation Assistant<br> and Translation Aggregator<br>"
            f"Version {BUILD_DATE}<br>"
            '<a href="https://github.com/Punllarena/Translation-Assistant">Github Link</a>'
        )
        msg.exec()
    # ------------------------------------------------------------------
    # Punctuation
    # ------------------------------------------------------------------

    def _insert_punctuation(self, index: int) -> None:
        text = _PUNCTUATIONS[index]
        cursor = self._translated_line.textCursor()
        insert_pos = cursor.position()
        cursor.insertText(text)
        cursor.setPosition(insert_pos + 1)
        self._translated_line.setTextCursor(cursor)
        self._translated_line.setFocus()

    # ------------------------------------------------------------------
    # Dictionary
    # ------------------------------------------------------------------

    def _add_to_dictionary(self) -> None:
        selected = self._translated_line.textCursor().selectedText()
        if not selected:
            return
        self._db.add_word(self._settings.profile_used, selected)
        self._spell_highlighter.add_word(selected)
        QMessageBox.information(
            self, "Dictionary",
            f'The word "{selected}" has been added to the dictionary.'
        )

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _on_translated_context_menu(self, pos) -> None:
        menu = QMenu(self)

        if self._spell_highlighter.available:
            word_cursor = self._translated_line.cursorForPosition(pos)
            word_cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            word = word_cursor.selectedText()

            if word and not self._spell_highlighter.check(word):
                suggestions = self._spell_highlighter.suggest(word)[:5]
                if suggestions:
                    for s in suggestions:
                        act = menu.addAction(s)
                        f = QFont(act.font())
                        f.setBold(True)
                        act.setFont(f)
                        def _apply(checked, _s=s, _c=word_cursor):
                            _c.insertText(_s)
                        act.triggered.connect(_apply)
                else:
                    no_sug = menu.addAction("No Spelling Suggestions")
                    no_sug.setEnabled(False)
                menu.addSeparator()

        for action in self._translated_line.createStandardContextMenu().actions():
            menu.addAction(action)

        menu.addSeparator()
        has_selection = bool(self._translated_line.textCursor().selectedText())
        add_act = menu.addAction("Add to Dictionary")
        add_act.setEnabled(has_selection)
        add_act.triggered.connect(self._add_to_dictionary)

        menu.exec(self._translated_line.mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Double-click navigation
    # ------------------------------------------------------------------

    def _on_review_top_double_click(self, char_pos: int) -> None:
        if not self._raw_lines or self._array_pointer == 0:
            return
        for idx, (start, end) in self._top_map.items():
            if start < char_pos < end:
                self._save_current_translation()
                self._array_pointer = idx
                self._update_ui_for_pointer()
                return

    def _on_review_bottom_double_click(self, char_pos: int) -> None:
        if not self._raw_lines:
            return
        n = len(self._raw_lines)
        if self._array_pointer >= n - 1:
            return
        for idx, (start, end) in self._bottom_map.items():
            if start < char_pos < end:
                self._save_current_translation()
                self._array_pointer = idx
                self._update_ui_for_pointer()
                return

    # ------------------------------------------------------------------
    # Event filter — unified keyboard handler
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            watched = (
                self._review_top, self._raw_line,
                self._translated_line, self._review_bottom,
            )
            if obj in watched and self._handle_key(event):
                return True
        return super().eventFilter(obj, event)

    def _handle_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        mods = event.modifiers()
        ctrl = mods == Qt.KeyboardModifier.ControlModifier

        if ctrl and key == Qt.Key.Key_F:
            QApplication.clipboard().setText(self._translated_line.toPlainText())
            return True

        if not self._raw_lines:
            return False

        if ctrl and key == Qt.Key.Key_End:
            self._jump_to_next_untranslated()
            return True
        if ctrl and key == Qt.Key.Key_Home:
            self._jump_to_first()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._navigate_forward(write_file=True)
            return True
        if key == Qt.Key.Key_PageDown:
            self._navigate_forward(write_file=False)
            return True
        if key == Qt.Key.Key_PageUp:
            self._navigate_backward()
            return True
        if ctrl and key == Qt.Key.Key_Right:
            self._advance_parse()
            return True
        if ctrl and key == Qt.Key.Key_Left:
            self._retreat_parse()
            return True
        if ctrl and key == Qt.Key.Key_A:
            self._translated_line.selectAll()
            return True
        if ctrl and key == Qt.Key.Key_J:
            self._add_to_dictionary()
            return True

        return False

    # ------------------------------------------------------------------
    # Window management helpers (delegate to parent window)
    # ------------------------------------------------------------------

    @contextmanager
    def _topmost_suspended(self):
        was = self._settings.on_top
        parent = self.window()
        if was and parent and parent is not self:
            flags = parent.windowFlags()
            parent.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
            parent.show()
        try:
            yield
        finally:
            if was and parent and parent is not self:
                flags = parent.windowFlags()
                parent.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
                parent.show()

    def save_state(self) -> None:
        """Called by CombinedMainWindow.closeEvent."""
        self._settings.splitter_state = self._splitter.saveState()
        self._save_current_translation()
        self._settings.last_doc_id = self._doc_id
        self._settings.save()

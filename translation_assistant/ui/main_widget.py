"""
TranslationAssistantWidget — all TA logic as a QWidget for embedding in CombinedMainWindow.
"""
from contextlib import contextmanager
import re
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QFont, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QInputDialog, QLabel, QMenu,
    QMessageBox, QProgressBar, QStatusBar, QTextEdit, QVBoxLayout, QWidget,
)

from translation_assistant._version import BUILD_DATE
from translation_assistant.settings import AppSettings
from translation_assistant.ui import remember_dialog_geometry
from translation_assistant.ui.card_list import CardListView, SERIF_FAMILIES
from translation_assistant.jp_highlighter import JpSyntaxHighlighter
from translation_assistant.spellcheck import SpellHighlighter

_PUNCTUATIONS = ["「」", "『』", "【】", "…", "〜", "〈〉", "《》", "ー", "♡"]

def _sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")


class _PublishWorker(QThread):
    succeeded = Signal(dict)
    error = Signal(str)

    def __init__(self, endpoint_url: str, payload: dict, parent=None) -> None:
        super().__init__(parent)
        self._endpoint_url = endpoint_url
        self._payload = payload

    def run(self) -> None:
        from translation_assistant.wp_publisher import publish, WPPublishError
        try:
            result = publish(self._endpoint_url, self._payload)
            self.succeeded.emit(result)
        except WPPublishError as exc:
            self.error.emit(exc.message)
        except Exception as exc:
            self.error.emit(str(exc))


class _StatusCheckWorker(QThread):
    succeeded = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        endpoint_url: str,
        api_key: str,
        series_slug: str,
        chapter: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._endpoint_url = endpoint_url
        self._api_key = api_key
        self._series_slug = series_slug
        self._chapter = chapter

    def run(self) -> None:
        from translation_assistant.wp_publisher import check_status, WPPublishError
        try:
            result = check_status(
                self._endpoint_url, self._api_key, self._series_slug, self._chapter
            )
            self.succeeded.emit(result)
        except WPPublishError as exc:
            self.error.emit(exc.message)
        except Exception as exc:
            self.error.emit(str(exc))


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


def _vline() -> QFrame:
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.VLine)
    frame.setFrameShadow(QFrame.Shadow.Sunken)
    return frame


class _TmRow(QWidget):
    clicked = Signal(str)

    def __init__(self, translation: str, meta: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._translation = translation
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(4, 3, 4, 3)
        vbox.setSpacing(1)
        tl = QLabel(translation)
        tl.setWordWrap(True)
        vbox.addWidget(tl)
        meta_lbl = QLabel(meta)
        meta_lbl.setStyleSheet("font-size: 8pt; color: gray;")
        vbox.addWidget(meta_lbl)

    def mousePressEvent(self, event):
        self.clicked.emit(self._translation)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.setStyleSheet("background: palette(highlight); color: palette(highlighted-text);")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet("")
        super().leaveEvent(event)


class TranslationAssistantWidget(QWidget):

    source_sentence_changed = Signal(str)
    upcoming_sentences_changed = Signal(list)

    def __init__(self, _settings: AppSettings | None = None, _db=None) -> None:
        super().__init__()
        self._settings = _settings if _settings is not None else AppSettings()
        self._db = _db

        # Document state
        self._raw_lines: list[str] = []
        self._translated_lines: list[str] = []
        self._raw_section: str = ""
        self._doc_id: int | None = None
        self._is_dirty: bool = False
        self._doc_title: str = ""
        self._block_dirty: bool = False

        # Navigation state
        self._array_pointer: int = 0
        self._parse_sentences: list[str] = []
        self._parse_pointer: int = -1
        self._replaced: bool = False

        # Glossary / parse chars
        self._glossary: list[tuple[str, str]] = []
        self._parse_chars: list[str] = []

        # Progress
        self._tl_complete: int = 0
        self._last_save_time: float = 0.0

        # Last-publish password/schedule state (set in _on_publish_wp, read in _on_publish_done)
        self._last_pw: str | None = None
        self._last_unlock_idx: int | None = None
        self._last_scheduled_date: str | None = None
        self._wp_post_url: str | None = None

        self._build_actions()
        self._build_shortcut_registry()
        self._setup_central_widget()
        self._setup_statusbar()
        self._setup_timers()
        self._load_initial_state()

    # ------------------------------------------------------------------
    # Action construction (CombinedMainWindow puts these in its menu bar)
    # ------------------------------------------------------------------

    def _build_actions(self) -> None:
        self.action_new_doc = QAction("New Document", self)
        self.action_new_doc.triggered.connect(self._on_new_doc)
        self.action_new_doc.setShortcut("Ctrl+N")

        self.action_new_series = QAction("New Series", self)
        self.action_new_series.triggered.connect(self._on_new_series)

        self.action_open = QAction("Open", self)
        self.action_open.triggered.connect(self._on_open)
        self.action_open.setShortcut("Ctrl+O")

        self.action_import = QAction("Import from file…", self)
        self.action_import.triggered.connect(self._on_import)

        self.action_batch_import = QAction("Import Folder…", self)
        self.action_batch_import.triggered.connect(self._on_batch_import)

        self.action_save = QAction("Save", self)
        self.action_save.triggered.connect(self._on_save)
        self.action_save.setShortcut("Ctrl+S")
        self.action_save.setEnabled(False)

        self.action_export = QAction("Export to file…", self)
        self.action_export.triggered.connect(self._on_export)
        self.action_export.setEnabled(False)

        self.action_publish_wp = QAction("Publish to WordPress…", self)
        self.action_publish_wp.triggered.connect(self._on_publish_wp)
        self.action_publish_wp.setEnabled(False)

        self.action_manage_series = QAction("Manage Series…", self)
        self.action_manage_series.triggered.connect(self._on_manage_series)

        self.action_db_export = QAction("Export Database Backup…", self)
        self.action_db_export.triggered.connect(self._on_db_export)

        self.action_db_import = QAction("Import Database Backup…", self)
        self.action_db_import.triggered.connect(self._on_db_import)

        self.action_profile = QAction("Profile", self)
        self.action_profile.triggered.connect(self._on_profile)
        self.action_profile.setShortcut("Ctrl+P")

        self.action_phrase = QAction("Phrase", self)
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

        self.action_go_to_line = QAction("Go to Line…", self)
        self.action_go_to_line.setShortcut("Ctrl+G")
        self.action_go_to_line.triggered.connect(self._on_go_to_line)
        self.action_go_to_line.setEnabled(False)

        self.action_on_top = QAction("Always On Top", self)
        self.action_on_top.setCheckable(True)
        self.action_on_top.setChecked(self._settings.on_top)
        self.action_on_top.triggered.connect(self._on_toggle_on_top)

        self.action_clipboard = QAction("Copy to Clipboard", self)
        self.action_clipboard.triggered.connect(self._on_clipboard_export)
        self.action_clipboard.setShortcut("Ctrl+Shift+C")
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
            "Single Quote : 「　」",
            "Double Quote : 『　』",
            "Lenticular : 【　】",
            "Ellipsis : …",
            "Wave Dash : 〜",
            "Single Title Bracket : 〈 〉",
            "Double Title Bracket : 《 》",
            "Long Dash : ー",
            "Heart : ♡",
        ]
        self.punct_actions: list[QAction] = []
        for i, label in enumerate(_punct_labels):
            act = QAction(label, self)
            act.setShortcut(f"F{i + 1}")
            act.triggered.connect(lambda checked, idx=i: self._insert_punctuation(idx))
            self.punct_actions.append(act)

        self.action_stats = QAction("Statistics…", self)
        self.action_stats.triggered.connect(self._on_stats)

        self.action_autosave = QAction("Autosave Interval…", self)
        self.action_autosave.triggered.connect(self._on_set_autosave)

        self.action_series_phrases = QAction("Series Phrase Suggestions…", self)
        self.action_series_phrases.setShortcut("Ctrl+Shift+P")
        self.action_series_phrases.triggered.connect(self._on_series_phrases)

        self.action_font_larger = QAction("Larger", self)
        self.action_font_larger.setShortcut("Ctrl+=")
        self.action_font_larger.triggered.connect(lambda: self._adjust_font_size(+1))

        self.action_font_smaller = QAction("Smaller", self)
        self.action_font_smaller.setShortcut("Ctrl+-")
        self.action_font_smaller.triggered.connect(lambda: self._adjust_font_size(-1))

    def _build_shortcut_registry(self) -> None:
        self._shortcut_registry: list[tuple[str, str, QAction, str]] = [
            ("new_doc",        "New Document",              self.action_new_doc,        "Ctrl+N"),
            ("open",           "Open",                      self.action_open,           "Ctrl+O"),
            ("save",           "Save",                      self.action_save,           "Ctrl+S"),
            ("profile",        "Profile",                   self.action_profile,        "Ctrl+P"),
            ("publish_wp",     "Publish to WordPress",      self.action_publish_wp,     "Ctrl+Shift+W"),
            ("phrase",         "Phrase",                    self.action_phrase,         "Ctrl+L"),
            ("go_to_line",     "Go to Line",                self.action_go_to_line,     "Ctrl+G"),
            ("clipboard",      "Copy to Clipboard",         self.action_clipboard,      "Ctrl+Shift+C"),
            ("series_phrases", "Series Phrase Suggestions", self.action_series_phrases, "Ctrl+Shift+P"),
            ("font_larger",    "Font Size: Larger",         self.action_font_larger,    "Ctrl+="),
            ("font_smaller",   "Font Size: Smaller",        self.action_font_smaller,   "Ctrl+-"),
        ]
        _punct_names = [
            "Single Quote", "Double Quote", "Lenticular",
            "Ellipsis", "Wave Dash", "Single Title Bracket",
            "Double Title Bracket", "Long Dash", "Heart",
        ]
        for i, (act, name) in enumerate(zip(self.punct_actions, _punct_names)):
            self._shortcut_registry.append(
                (f"punct_{i}", f"Special: {name}", act, f"F{i + 1}")
            )
        self._apply_saved_shortcuts()

    def _apply_saved_shortcuts(self) -> None:
        for key, _, action, _ in self._shortcut_registry:
            saved = self._settings.get_shortcut(key)
            if saved:
                action.setShortcut(saved)

    # ------------------------------------------------------------------
    # Widget setup
    # ------------------------------------------------------------------

    def _setup_central_widget(self) -> None:
        font = QFont()
        font.setFamilies(SERIF_FAMILIES)
        font.setPointSizeF(self._settings.font_size)

        def _labeled(title, inner: QWidget) -> QFrame:
            w = QFrame(self)
            w.setObjectName("Card")
            vbox = QVBoxLayout(w)
            vbox.setContentsMargins(8, 8, 8, 8)
            vbox.setSpacing(4)
            lbl = QLabel(title) if isinstance(title, str) else title
            lbl.setObjectName("PanelLabel")
            vbox.addWidget(lbl)
            vbox.addWidget(inner)
            return w

        self._raw_line = QTextEdit()
        self._raw_line.setObjectName("SourceText")
        self._raw_line.setReadOnly(True)
        self._raw_line.setFont(font)
        self._raw_line.setMinimumHeight(40)
        self._raw_line.setMaximumHeight(140)
        self._raw_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._raw_line.setPlaceholderText("No document open — File → New or Ctrl+O")
        self._jp_highlighter = JpSyntaxHighlighter(self._raw_line.document())

        self._translated_line = QTextEdit()
        self._translated_line.setObjectName("TranslationText")
        self._translated_line.setFont(font)
        self._translated_line.setMinimumHeight(40)
        self._translated_line.setMaximumHeight(140)
        self._translated_line.setAcceptRichText(False)
        self._translated_line.setPlaceholderText("Type your translation…")
        self._translated_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._translated_line.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._translated_line.customContextMenuRequested.connect(self._on_translated_context_menu)
        self._spell_highlighter = SpellHighlighter(self._translated_line.document())

        self._card_view = CardListView()
        self._card_view.set_editors(self._raw_line, self._translated_line)
        self._card_view.set_font_size(self._settings.font_size)
        self._card_view.card_clicked.connect(self._on_card_clicked)

        self._tm_panel = QWidget()
        self._tm_panel.setMinimumHeight(0)
        self._tm_layout = QVBoxLayout(self._tm_panel)
        self._tm_layout.setContentsMargins(2, 2, 2, 2)
        self._tm_layout.setSpacing(2)
        _tm_lbl = _ClickableLabel("TM Matches")
        _tm_lbl.clicked.connect(self._toggle_tm_panel)
        self._panel_tm = _labeled(_tm_lbl, self._tm_panel)
        self._panel_tm.setVisible(False)

        for widget in (self._raw_line, self._translated_line):
            widget.installEventFilter(self)

        self._translated_line.textChanged.connect(self._on_translation_text_changed)

    def _setup_statusbar(self) -> None:
        self._status_bar = QStatusBar()

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFormat("%p%")
        self._progress_bar.setMaximumWidth(120)
        self._progress_bar.setTextVisible(True)
        self._line_label = _ClickableLabel()
        self._line_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._line_label.setToolTip("Go to line… (Ctrl+G)")
        self._line_label.clicked.connect(self._on_go_to_line)
        self._word_label = QLabel()
        self._parse_label = QLabel("")
        self._parse_label.setHidden(True)
        self._profile_label = _ClickableLabel()
        self._profile_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._profile_label.setToolTip("Manage profiles (Ctrl+P)")
        self._profile_label.clicked.connect(self._on_profile)
        self._filesaved_label = QLabel("")
        self._stats_label = _ClickableLabel("")
        self._stats_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stats_label.clicked.connect(self._on_stats)
        self._progress_sep = _vline()
        self._status_bar.addWidget(self._progress_bar)
        self._status_bar.addWidget(self._line_label)
        self._status_bar.addWidget(self._word_label)
        self._status_bar.addWidget(self._progress_sep)
        self._status_bar.addWidget(self._parse_label)
        self._status_bar.addWidget(self._profile_label)
        self._status_bar.addPermanentWidget(self._stats_label)
        self._status_bar.addPermanentWidget(_vline())
        self._status_bar.addPermanentWidget(self._filesaved_label)
        self._wp_status_label = _ClickableLabel("")
        self._wp_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wp_status_label.clicked.connect(self._on_wp_status_clicked)
        self._status_bar.addPermanentWidget(self._wp_status_label)
        self._update_progress_visibility()
        self._update_filesaved_label()

    def _update_wp_status_label(self) -> None:
        if self._doc_id is None:
            self._wp_status_label.setText("")
            self._wp_status_label.setToolTip("")
            self._wp_post_url = None
            return
        info = self._db.get_document_wp_status(self._doc_id)
        status_map = {
            "publish":   ("WP: Published", "#2e7d32"),
            "future":    ("WP: Scheduled", "#b26a00"),
            "draft":     ("WP: Draft", "#757575"),
            "not_found": ("WP: —", "#757575"),
        }
        text, color = status_map.get(info["wp_status"] or "", ("WP: —", "#757575"))
        self._wp_status_label.setText(text)
        self._wp_status_label.setStyleSheet(f"color: {color};")
        self._wp_post_url = info["wp_post_url"]
        tooltip = []
        if info.get("wp_date"):
            tooltip.append(f"WordPress date: {info['wp_date']}")
        if self._wp_post_url:
            tooltip.append("Click to open post")
        self._wp_status_label.setToolTip("\n".join(tooltip))

    def _on_wp_status_clicked(self) -> None:
        if self._wp_post_url:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(self._wp_post_url))

    def _setup_timers(self) -> None:
        self._clipboard_timer = QTimer(self)
        self._clipboard_timer.setSingleShot(True)
        self._clipboard_timer.setInterval(400)
        self._clipboard_timer.timeout.connect(self._on_clipboard_timer)

        self._autosave_tick_timer = QTimer(self)
        self._autosave_tick_timer.setInterval(60_000)
        self._autosave_tick_timer.timeout.connect(self._update_filesaved_label)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._on_autosave_timer)

    def _load_initial_state(self) -> None:
        self._update_parse_chars()
        self._load_glossary_for_profile()
        self._load_spell_dict()
        self._update_profile_label()
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
        from translation_assistant.core import line_has_content
        untranslated = next(
            (i for i, t in enumerate(self._translated_lines)
             if line_has_content(self._raw_lines[i]) and not t),
            None,
        )
        pos = untranslated if untranslated is not None else doc["last_position"]
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
        self._last_save_time = 0.0
        self._autosave_tick_timer.stop()
        self._update_filesaved_label()
        from translation_assistant.core import replace_and_parse, line_has_content
        raw_lines = self._raw_lines
        translated_lines = self._translated_lines

        p = self._array_pointer
        if raw_lines and not line_has_content(raw_lines[p]):
            p = next(
                (i for i in range(p, len(raw_lines)) if line_has_content(raw_lines[i])),
                p,
            )
            self._array_pointer = p

        self._card_view.load(raw_lines, translated_lines, self._glossary)

        display, sentences, replaced = replace_and_parse(
            raw_lines[p], self._glossary, self._parse_chars
        )
        self._raw_line.setPlainText(display)
        self._block_dirty = True
        self._translated_line.setPlainText(translated_lines[p])
        self._block_dirty = False
        self._parse_sentences = sentences
        self._parse_pointer = -1
        self._parse_label.setVisible(False)
        self._replaced = replaced

        self._card_view.set_active(p)
        self._update_progress_labels()

        self.action_save.setEnabled(True)
        self.action_export.setEnabled(True)
        self.action_publish_wp.setEnabled(True)
        self.action_clipboard.setEnabled(True)
        self.action_go_to_line.setEnabled(True)
        self.action_export_md_tl_doc.setEnabled(True)
        self.action_export_md_ruby_doc.setEnabled(True)
        _doc_meta = self._db.get_document(self._doc_id)
        _doc_display = _doc_meta.get("chapter_title") or _doc_meta.get("title") or ""
        self._doc_title = _doc_display
        self._refresh_window_title()
        _has_series = bool(_doc_meta.get("series_title", ""))
        self.action_export_md_tl_series.setEnabled(_has_series)
        self.action_export_md_ruby_series.setEnabled(_has_series)
        self._translated_line.setFocus()
        self._start_clipboard_timer()
        self._restart_autosave_timer()
        self._update_stats_label()
        self._update_progress_visibility()
        self._update_profile_label()
        self._set_dirty(False)
        if self._doc_id is not None:
            self._settings.add_to_recent(self._doc_id)

        self._update_wp_status_label()

        # Emit so the Aggregator translates the first sentence on load
        self.source_sentence_changed.emit(display.lstrip("%$").strip())
        self.upcoming_sentences_changed.emit(self._upcoming_sentences())

    def _save_to_db(self) -> None:
        if self._doc_id is None:
            return
        import time
        self._db.save_lines(self._doc_id, self._lines_as_db_rows())
        self._last_save_time = time.monotonic()
        self._update_filesaved_label()
        self._autosave_tick_timer.start()

    def _update_filesaved_label(self) -> None:
        cadence = f"{self._settings.auto_save}m" if self._settings.auto_save > 0 else "off"
        if self._is_dirty:
            self._filesaved_label.setText("● Unsaved")
            return
        if self._last_save_time == 0.0:
            self._filesaved_label.setText(f"Autosave: {cadence}")
            return
        import time
        elapsed_m = int((time.monotonic() - self._last_save_time) / 60)
        when = "just now" if elapsed_m < 1 else f"{elapsed_m}m ago"
        self._filesaved_label.setText(f"✓ Autosaved {when} · autosave {cadence}")

    # ------------------------------------------------------------------
    # UI update helpers
    # ------------------------------------------------------------------

    def _update_ui_for_pointer(self) -> None:
        from translation_assistant.core import replace_and_parse
        p = self._array_pointer

        display, sentences, replaced = replace_and_parse(
            self._raw_lines[p], self._glossary, self._parse_chars
        )
        self._raw_line.setPlainText(display)
        self._block_dirty = True
        self._translated_line.setPlainText(self._translated_lines[p])
        self._block_dirty = False
        self._parse_sentences = sentences
        self._parse_pointer = -1
        self._replaced = replaced

        self._card_view.set_active(p)
        self._update_progress_labels()
        self._translated_line.setFocus()
        self._start_clipboard_timer()

        self.source_sentence_changed.emit(display.lstrip("%$").strip())
        self.upcoming_sentences_changed.emit(self._upcoming_sentences())
        self._update_tm_panel()
        self._parse_label.setVisible(False)

    def _upcoming_sentences(self, limit: int = 20) -> list[str]:
        """Next `limit` content lines after the pointer, transformed like the
        displayed line, for the aggregator's prefetch queue."""
        from translation_assistant.core import replace_and_parse, line_has_content
        out: list[str] = []
        for i in range(self._array_pointer + 1, len(self._raw_lines)):
            if len(out) >= limit:
                break
            raw = self._raw_lines[i]
            if not line_has_content(raw):
                continue
            display, _, _ = replace_and_parse(raw, self._glossary, self._parse_chars)
            display = display.lstrip("%$").strip()
            if display:
                out.append(display)
        return out

    def _update_tm_panel(self) -> None:
        while self._tm_layout.count():
            item = self._tm_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._raw_lines or not self._settings.tm_visible:
            self._panel_tm.setVisible(False)
            return

        p = self._array_pointer
        raw = self._raw_lines[p]
        raw_text = raw[1:] if raw and raw[0] in ('%', '$') else raw
        matches = self._db.find_tm_matches(raw_text, self._doc_id)

        if not matches:
            self._panel_tm.setVisible(False)
            return

        self._panel_tm.setVisible(True)
        for i, m in enumerate(matches):
            date_str = m["updated_at"][:10] if m.get("updated_at") else ""
            meta = f"{m['doc_title']}, {date_str}"
            row = _TmRow(m["translated_text"], meta)
            row.clicked.connect(self._translated_line.setPlainText)
            self._tm_layout.addWidget(row)
            if i < len(matches) - 1:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("color: palette(mid);")
                self._tm_layout.addWidget(sep)

    def _update_progress_labels(self) -> None:
        from translation_assistant.core import calculate_progress, line_has_content
        p = self._array_pointer
        n = len(self._raw_lines)
        self._line_label.setText(f"Page {p + 1}/{n}")
        pct, wc = calculate_progress(self._raw_lines, self._translated_lines)
        self._tl_complete = pct
        self._progress_bar.setValue(pct)
        done = sum(
            1 for r, t in zip(self._raw_lines, self._translated_lines)
            if line_has_content(r) and t
        )
        total = sum(1 for r in self._raw_lines if line_has_content(r))
        self._progress_bar.setToolTip(f"{done} of {total} paragraphs translated")
        self._word_label.setText(f"{wc} Words")

    def _update_progress_visibility(self) -> None:
        visible = self._settings.show_progress and self._doc_id is not None
        self._progress_bar.setVisible(visible)
        self._line_label.setVisible(visible)
        self._word_label.setVisible(visible)
        self._progress_sep.setVisible(visible)

    def _update_profile_label(self) -> None:
        profile = self._settings.profile_used or "Default"
        self._profile_label.setText(f"Profile: {profile}")
        self._profile_label.setVisible(True)

    def _on_set_autosave(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        current = self._settings.auto_save
        minutes, ok = QInputDialog.getInt(
            self, "Autosave Interval",
            "Interval in minutes (0 = disabled):",
            current, 0, 60,
        )
        if ok:
            self._settings.auto_save = minutes
            self._settings.save()
            self._update_filesaved_label()
            self._restart_autosave_timer()

    def _adjust_font_size(self, delta: int) -> None:
        new_size = max(8.0, min(24.0, self._settings.font_size + delta))
        self._settings.font_size = new_size
        self._settings.save()
        self._apply_font()

    def _apply_font(self) -> None:
        font = QFont()
        font.setFamilies(SERIF_FAMILIES)
        font.setPointSizeF(self._settings.font_size)
        for w in (self._raw_line, self._translated_line):
            w.setFont(font)
        self._card_view.set_font_size(self._settings.font_size)

    def _on_translation_text_changed(self) -> None:
        if not self._block_dirty and self._doc_id is not None:
            self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        if self._is_dirty == dirty:
            return
        self._is_dirty = dirty
        self._refresh_window_title()
        self._update_filesaved_label()

    def _refresh_window_title(self) -> None:
        win = self.window()
        if win is not self:
            base = f"{self._doc_title} — Translation Assistant" if self._doc_title else "Translation Assistant"
            win.setWindowTitle(base + " *" if self._is_dirty else base)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _save_current_translation(self) -> None:
        if not self._raw_lines:
            return
        text = self._translated_line.toPlainText()
        self._translated_lines[self._array_pointer] = text
        self._card_view.update_card(self._array_pointer, text)
        if self._doc_id is not None:
            self._db.save_translation(self._doc_id, self._array_pointer, text)
            self._update_stats_label()
            self._set_dirty(False)

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
            self._update_progress_labels()

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
            self._line_label.setText(f"Page {p + 1}/{n}")

        self._translated_line.setFocus()

    def _jump_to_first(self) -> None:
        if not self._raw_lines or self._array_pointer == 0:
            return
        self._clipboard_timer.stop()
        self._save_current_translation()
        self._array_pointer = 0
        self._update_ui_for_pointer()
        self._translated_line.setFocus()

    def _on_card_clicked(self, index: int) -> None:
        if index == self._array_pointer:
            self._translated_line.setFocus()
            return
        self._clipboard_timer.stop()
        self._save_current_translation()
        self._array_pointer = index
        self._update_ui_for_pointer()

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
        if self._parse_pointer >= 0:
            self._parse_label.setText(f"Phrase {self._parse_pointer + 1}/{len(self._parse_sentences)}")
            self._parse_label.setVisible(True)
        else:
            self._parse_label.setVisible(False)
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
        if self._parse_pointer >= 0:
            self._parse_label.setText(f"Phrase {self._parse_pointer + 1}/{len(self._parse_sentences)}")
            self._parse_label.setVisible(True)
        else:
            self._parse_label.setVisible(False)
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
        self._card_view.show_copied_pill(self._array_pointer)

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
                remember_dialog_geometry(dlg2, self._settings, "dlg_series")
                dlg2.exec()

    def _on_open(self) -> None:
        from translation_assistant.ui.dlg_open import OpenDocumentDialog
        with self._topmost_suspended():
            dlg = OpenDocumentDialog(
                self._db, parent=self,
                current_doc_id=self._doc_id,
                settings=self._settings,
            )
            remember_dialog_geometry(dlg, self._settings, "dlg_open")
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

    def _export_md_doc(self, builder) -> None:
        if not self._raw_lines:
            return
        self._save_current_translation()
        from translation_assistant.core import calculate_progress
        pct, _ = calculate_progress(self._raw_lines, self._translated_lines)
        if pct < 100:
            reply = QMessageBox.question(
                self, "Incomplete Translation",
                f"Translation is {pct}% complete. Export anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
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
        self._save_current_translation()
        if self._doc_id is None:
            return
        meta = self._db.get_document(self._doc_id)
        series_title = meta.get("series_title", "")
        if not series_title:
            return
        with self._topmost_suspended():
            parent = QFileDialog.getExistingDirectory(
                self, f"Export Series: {series_title} — select parent folder"
            )
        if not parent:
            return
        folder = Path(parent) / (_sanitize_filename(series_title) or "series")
        folder.mkdir(exist_ok=True)
        from translation_assistant.core import db_rows_to_arrays, calculate_progress
        doc_ids = self._db.get_document_ids_by_series(series_title)
        written = 0
        skipped_exists = 0
        skipped_incomplete = 0
        for doc_id in doc_ids:
            doc_meta = self._db.get_document(doc_id)
            rows = self._db.get_lines(doc_id)
            raw_lines, translated_lines = db_rows_to_arrays(rows)
            pct, _ = calculate_progress(raw_lines, translated_lines)
            if pct < 100:
                skipped_incomplete += 1
                continue
            heading = doc_meta.get("chapter_title") or doc_meta.get("title", "")
            stem = _sanitize_filename(doc_meta.get("title") or f"doc_{doc_id}") or f"doc_{doc_id}"
            filename = f"{doc_meta['series_order']:03d} - {stem}.md"
            dest = Path(folder) / filename
            if dest.exists():
                skipped_exists += 1
                continue
            result = builder(raw_lines, translated_lines, heading)
            dest.write_text(result, encoding="utf-8")
            written += 1
        lines = [f"Exported {written} file(s) to:\n{folder}"]
        if skipped_exists:
            lines.append(f"{skipped_exists} file(s) skipped (already exist)")
        if skipped_incomplete:
            lines.append(f"{skipped_incomplete} file(s) skipped (incomplete translation)")
        QMessageBox.information(self, "Export Complete", "\n\n".join(lines))

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
        self._card_view.load([], [], [])
        self._raw_line.clear()
        self._translated_line.clear()
        self._parse_label.setVisible(False)
        self._doc_title = ""
        self._refresh_window_title()
        self.action_save.setEnabled(False)
        self.action_export.setEnabled(False)
        self.action_publish_wp.setEnabled(False)
        self._load_glossary_for_profile()
        self._filesaved_label.setText("Database imported.")

    def _on_manage_series(self) -> None:
        from translation_assistant.ui.dlg_series import SeriesManagerDialog
        with self._topmost_suspended():
            dlg = SeriesManagerDialog(self._db, parent=self)
            remember_dialog_geometry(dlg, self._settings, "dlg_series")
            dlg.exec()

    def _on_publish_wp(self) -> None:
        from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog
        from translation_assistant.wp_publisher import build_payload, WPPublishError

        endpoint_url = self._settings.wp_endpoint_url
        api_key = self._settings.wp_api_key
        if not endpoint_url or not api_key:
            dlg = WPSettingsDialog(self._settings, parent=self)
            if not dlg.exec():
                return
            endpoint_url = self._settings.wp_endpoint_url
            api_key = self._settings.wp_api_key
            if not endpoint_url or not api_key:
                return

        doc_meta = self._db.get_document(self._doc_id)
        series_title = doc_meta["series_title"]
        series_meta = self._db.get_series_wp_meta(series_title)

        prev_scheduled = False
        if doc_meta["series_order"] > 0:
            prev_status = self._db.get_wp_status_by_series_position(
                doc_meta["series_title"], doc_meta["series_order"] - 1
            )
            prev_scheduled = (
                prev_status is not None and prev_status.get("wp_status") == "future"
            )

        from translation_assistant.wp_publisher import compute_password_fields, resolve_wp_password_enabled
        pw_settings = self._db.get_series_wp_password_settings(series_title)
        pw_enabled = resolve_wp_password_enabled(pw_settings, self._settings.wp_password_enabled)
        unlock_after = (
            pw_settings["wp_unlock_after"]
            if pw_settings["wp_unlock_after"] != -1
            else self._settings.wp_unlock_after
        )
        self._last_pw = None
        self._last_unlock_idx = None
        if pw_enabled:
            self._last_pw, self._last_unlock_idx = compute_password_fields(
                doc_meta["series_order"], unlock_after
            )

        if not series_meta["series_slug"] or not series_meta["series_title_short"]:
            from translation_assistant.ui.dlg_series import SeriesManagerDialog
            QMessageBox.information(
                self,
                "WP Fields Missing",
                f'Set "Series Slug" and "Short Title" for "{series_title}" in Series Manager.',
            )
            dlg = SeriesManagerDialog(self._db, parent=self)
            remember_dialog_geometry(dlg, self._settings, "dlg_series")
            dlg.exec()
            series_meta = self._db.get_series_wp_meta(series_title)
            if not series_meta["series_slug"] or not series_meta["series_title_short"]:
                return

        lines = self._db.get_lines(self._doc_id)
        if not any(ln["translated_text"].strip() for ln in lines):
            QMessageBox.warning(self, "Nothing to Publish", "No translated lines to publish.")
            return

        chapter_label = "Synopsis" if doc_meta["series_order"] == 0 else f"Chapter {doc_meta['series_order']}"

        from PySide6.QtWidgets import QCheckBox, QDateTimeEdit, QDialog, QDialogButtonBox, QVBoxLayout
        from PySide6.QtCore import QDateTime, QTime, Qt as _Qt

        confirm_dlg = QDialog(self)
        confirm_dlg.setWindowTitle("Publish to WordPress")
        confirm_dlg.setWindowFlags(confirm_dlg.windowFlags() & ~_Qt.WindowType.WindowContextHelpButtonHint)
        _cl = QVBoxLayout(confirm_dlg)

        # Cached WP status line
        _cached = self._db.get_document_wp_status(self._doc_id)
        _status_text_map = {"publish": "Published", "future": "Scheduled", "draft": "Draft"}
        _cached_text = _status_text_map.get(_cached["wp_status"] or "", "Not published")
        _status_lbl = QLabel(f"WP status: {_cached_text}")
        _cl.addWidget(_status_lbl)

        _cl.addWidget(QLabel(f'Publish <b>{doc_meta["chapter_title"]}</b> ({chapter_label}) to WordPress?'))

        if prev_scheduled:
            _warn = QLabel(
                f"Warning: Chapter {doc_meta['series_order'] - 1} is still scheduled "
                "and hasn't gone live yet."
            )
            _warn.setWordWrap(True)
            _cl.addWidget(_warn)

        schedule_cb = QCheckBox("Schedule for later")
        _cl.addWidget(schedule_cb)

        # Pre-fill schedule time from settings
        _default_time = self._settings.wp_default_schedule_time
        if _default_time:
            try:
                _h, _m = map(int, _default_time.split(":"))
            except (ValueError, IndexError):
                _default_time = ""
        if _default_time:
            _candidate = QDateTime.currentDateTime()
            _candidate.setTime(QTime(_h, _m))
            if _candidate <= QDateTime.currentDateTime():
                _candidate = _candidate.addDays(1)
            dte = QDateTimeEdit(_candidate)
        else:
            dte = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        dte.setCalendarPopup(True)
        dte.setDisplayFormat("yyyy-MM-dd HH:mm")
        dte.setEnabled(False)
        schedule_cb.toggled.connect(dte.setEnabled)
        _cl.addWidget(dte)

        if prev_scheduled:
            _btns = QDialogButtonBox()
            _btns.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
            _btns.addButton("Publish Anyway", QDialogButtonBox.ButtonRole.AcceptRole)
        else:
            _btns = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
        _btns.accepted.connect(confirm_dlg.accept)
        _btns.rejected.connect(confirm_dlg.reject)
        _cl.addWidget(_btns)

        # Async status refresh
        _status_worker = _StatusCheckWorker(
            endpoint_url, api_key,
            series_meta["series_slug"], doc_meta["series_order"],
            parent=self,
        )

        def _on_status_ok(result: dict) -> None:
            _map = {
                "publish":   "Published",
                "future":    "Scheduled",
                "draft":     "Draft",
                "not_found": "Not published",
            }
            _status_lbl.setText(f"WP status: {_map.get(result.get('status', ''), 'Unknown')}")
            self._db.set_document_wp_status(
                self._doc_id, result.get("status") or None, result.get("post_url"),
                result.get("date"),
            )
            self._update_wp_status_label()

        def _on_status_err(msg: str) -> None:
            _status_lbl.setText(f"WP status: {_cached_text} (cached — {msg})")

        _status_worker.succeeded.connect(_on_status_ok)
        _status_worker.error.connect(_on_status_err)
        _status_worker.start()

        _dlg_result = confirm_dlg.exec()
        _status_worker.quit()
        _status_worker.wait(500)
        if not _dlg_result:
            return

        self._last_scheduled_date = None
        if schedule_cb.isChecked():
            from datetime import timezone as _tz
            _local = dte.dateTime().toPython()
            self._last_scheduled_date = _local.astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            payload = build_payload(
                doc_meta, series_meta, lines, api_key=api_key,
                password=self._last_pw,
                unlock_chapter_index=self._last_unlock_idx,
                scheduled_date=self._last_scheduled_date,
                attribution=self._settings.wp_attribution_enabled,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Payload Error", str(exc))
            return

        self.action_publish_wp.setEnabled(False)
        self._publish_worker = _PublishWorker(endpoint_url, payload, parent=self)
        self._publish_worker.succeeded.connect(self._on_publish_done)
        self._publish_worker.error.connect(self._on_publish_error)
        self._publish_worker.start()

    def _on_publish_done(self, result: dict) -> None:
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
        )
        from PySide6.QtCore import Qt

        already = result.get("created") is False
        page_url = result.get("page_url", "")
        post_url = result.get("post_url", "")

        if not already:
            from datetime import datetime as _dt, timezone as _tz
            wp_status_val = "future" if self._last_scheduled_date else "publish"
            wp_date_val = self._last_scheduled_date or _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._db.set_document_wp_status(self._doc_id, wp_status_val, post_url or None, wp_date_val)
            self._update_wp_status_label()

        dlg = QDialog(self)
        dlg.setWindowTitle("WordPress Publish")
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)

        status_label = QLabel("Already published." if already else ("Scheduled!" if self._last_scheduled_date else "Published!"))
        layout.addWidget(status_label)

        form = QFormLayout()
        if page_url:
            page_label = QLabel(f'<a href="{page_url}">{page_url}</a>')
            page_label.setOpenExternalLinks(True)
            form.addRow("Page:", page_label)
        if post_url and not already:
            post_label = QLabel(f'<a href="{post_url}">{post_url}</a>')
            post_label.setOpenExternalLinks(True)
            form.addRow("Post:", post_label)
        layout.addLayout(form)

        if not already and self._last_pw:
            pw_edit = QLineEdit(self._last_pw)
            pw_edit.setReadOnly(True)
            pw_edit.selectAll()
            layout.addWidget(QLabel("Password (copy this):"))
            layout.addWidget(pw_edit)

        if not already and self._last_unlock_idx is not None:
            layout.addWidget(QLabel(f"Chapter {self._last_unlock_idx} is now unlocked."))

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(dlg.accept)
        layout.addWidget(btns)

        dlg.exec()
        self.action_publish_wp.setEnabled(True)

    def _on_publish_error(self, message: str) -> None:
        QMessageBox.warning(self, "Publish Failed", message)
        self.action_publish_wp.setEnabled(True)

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
                self._update_profile_label()
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

    def _toggle_tm_panel(self) -> None:
        self.action_tm.setChecked(not self.action_tm.isChecked())
        self._on_toggle_tm()

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
        from translation_assistant.core import line_has_content
        idx = line_num - 1
        if not line_has_content(self._raw_lines[idx]):
            idx = next(
                (i for i in range(idx, n) if line_has_content(self._raw_lines[i])),
                next((i for i in range(idx, -1, -1)
                      if line_has_content(self._raw_lines[i])), 0),
            )
        self._clipboard_timer.stop()
        self._save_current_translation()
        self._array_pointer = idx
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
    # Event filter — unified keyboard handler
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            watched = (self._raw_line, self._translated_line)
            if obj in watched and self._handle_key(event):
                return True
        if obj is self._raw_line and event.type() == QEvent.Type.MouseButtonPress:
            self._show_source_word_tooltip(event)
        return super().eventFilter(obj, event)

    def _show_source_word_tooltip(self, event) -> None:
        text = self._raw_line.toPlainText()
        if not text:
            return
        cursor = self._raw_line.cursorForPosition(event.pos())
        info = self._jp_highlighter.token_info_at(text, cursor.position())
        if info:
            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(
                event.globalPosition().toPoint(), info, self._raw_line
            )

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
            if mods == Qt.KeyboardModifier.ShiftModifier:
                return False  # let QTextEdit insert a newline
            self._navigate_forward(write_file=True)
            return True
        if key == Qt.Key.Key_PageDown:
            self._navigate_forward(write_file=False)
            return True
        if key == Qt.Key.Key_PageUp:
            self._navigate_backward()
            return True
        if ctrl and key == Qt.Key.Key_Down:
            self._navigate_forward(write_file=False)
            return True
        if ctrl and key == Qt.Key.Key_Up:
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
    # Usage statistics
    # ------------------------------------------------------------------

    def _update_stats_label(self) -> None:
        try:
            stats = self._db.get_today_stats()
            parts = {
                "paragraphs": f"{stats['paragraphs']} ¶",
                "chars": f"{stats['chars']:,} chars",
                "en_words": f"{stats['en_words']:,} EN words",
            }
            metric = self._settings.stats_metric
            if metric not in parts:
                metric = "paragraphs"
            self._stats_label.setText(f"Today: {parts[metric]}")
            ordered = [metric] + [m for m in parts if m != metric]
            self._stats_label.setToolTip(
                "Today: " + " · ".join(parts[m] for m in ordered)
                + "\nClick for statistics"
            )
            self._stats_label.setVisible(True)
        except Exception:
            self._stats_label.setVisible(False)

    def _on_stats(self) -> None:
        from translation_assistant.ui.dlg_stats import StatsDialog
        with self._topmost_suspended():
            dlg = StatsDialog(self._db, self._settings, self)
            remember_dialog_geometry(dlg, self._settings, "dlg_stats")
            dlg.exec()
        self._update_stats_label()

    def _on_series_phrases(self) -> None:
        from translation_assistant.ui.dlg_series_phrases import SeriesPhrasesDialog, _get_series_for_doc
        dlg = SeriesPhrasesDialog(
            self._db, self._settings,
            current_series=_get_series_for_doc(self._db, self._doc_id),
            parent=self,
        )
        remember_dialog_geometry(dlg, self._settings, "dlg_series_phrases")
        dlg.exec()

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
        self._save_current_translation()
        self._settings.last_doc_id = self._doc_id
        self._settings.save()

    # ------------------------------------------------------------------
    # Panel access (consumed by CombinedMainWindow to build layout)
    # ------------------------------------------------------------------

    @property
    def card_panel(self) -> QWidget:
        return self._card_view

    @property
    def tm_panel(self) -> QFrame:
        return self._panel_tm

    @property
    def status_bar(self) -> QStatusBar:
        return self._status_bar

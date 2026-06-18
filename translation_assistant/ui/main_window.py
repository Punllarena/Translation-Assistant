"""
Main application window — full Stage 5 implementation.
"""
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMenu,
    QMessageBox, QSizePolicy, QSplitter, QStatusBar, QTextEdit, QVBoxLayout, QWidget,
)

from translation_assistant._version import BUILD_DATE
from translation_assistant.settings import AppSettings
from translation_assistant.spellcheck import SpellHighlighter

_CJK_FAMILIES = ["Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "sans-serif"]
_PUNCTUATIONS = ["「」", "『』", "【】", "…", "〜", "〈〉", "《》", "ー", "♡"]
_RESOURCES = Path(__file__).parent.parent / "resources"

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
    "1.) Click the Special Punctuations menu or press F1-F9"
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


# ---------------------------------------------------------------------------
# Custom QTextEdit with double-click signal
# ---------------------------------------------------------------------------

class ReviewTextEdit(QTextEdit):
    """Read-only review panel that emits the character offset on double-click."""

    line_double_clicked = Signal(int)

    def mouseDoubleClickEvent(self, event):
        click_pos = self.cursorForPosition(event.position().toPoint()).position()
        super().mouseDoubleClickEvent(event)
        self.line_double_clicked.emit(click_pos)


# ---------------------------------------------------------------------------
# Clickable status-bar label
# ---------------------------------------------------------------------------

class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

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

        self._setup_window()
        self._setup_menubar()
        self._setup_central_widget()
        self._setup_statusbar()
        self._setup_timers()
        self._load_initial_state()

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle("Translation Assistant Tool")
        self.resize(566, 686)
        self.setMinimumSize(564, 500)
        icon_path = _RESOURCES / "TA.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _setup_menubar(self) -> None:
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("File")
        self._action_new = file_menu.addAction("New (CTRL+N)")
        self._action_new.triggered.connect(self._on_new)
        self._action_new.setShortcut("Ctrl+N")
        self._action_open = file_menu.addAction("Open (CTRL+O)")
        self._action_open.triggered.connect(self._on_open)
        self._action_open.setShortcut("Ctrl+O")
        self._action_import = file_menu.addAction("Import from file…")
        self._action_import.triggered.connect(self._on_import)
        self._action_save = file_menu.addAction("Save (CTRL+S)")
        self._action_save.triggered.connect(self._on_save)
        self._action_save.setShortcut("Ctrl+S")
        self._action_save.setEnabled(False)
        self._action_export = file_menu.addAction("Export to file…")
        self._action_export.triggered.connect(self._on_export)
        self._action_export.setEnabled(False)

        file_menu.addSeparator()
        self._action_manage_series = file_menu.addAction("Manage Series…")
        self._action_manage_series.triggered.connect(self._on_manage_series)

        file_menu.addSeparator()
        self._action_db_export = file_menu.addAction("Export Database Backup…")
        self._action_db_export.triggered.connect(self._on_db_export)
        self._action_db_import = file_menu.addAction("Import Database Backup…")
        self._action_db_import.triggered.connect(self._on_db_import)

        # Settings
        settings_menu = mb.addMenu("Settings")
        self._action_profile = settings_menu.addAction("Profile (CTRL+P)")
        self._action_profile.triggered.connect(self._on_profile)
        self._action_profile.setShortcut("Ctrl+P")
        self._action_phrase = settings_menu.addAction("Phrase (CTRL+L)")
        self._action_phrase.triggered.connect(self._on_phrase)
        self._action_phrase.setShortcut("Ctrl+L")
        self._action_progress = settings_menu.addAction("Show Progress")
        self._action_progress.setCheckable(True)
        self._action_progress.setChecked(self._settings.show_progress)
        self._action_progress.triggered.connect(self._on_toggle_progress)
        self._action_on_top = settings_menu.addAction("Always On Top")
        self._action_on_top.setCheckable(True)
        self._action_on_top.setChecked(self._settings.on_top)
        self._action_on_top.triggered.connect(self._on_toggle_on_top)
        tts_menu = QMenu("Text-To-Speech", self)
        self._action_tts_jp = tts_menu.addAction("Japanese")
        self._action_tts_jp.setCheckable(True)
        self._action_tts_jp.setEnabled(False)
        self._action_tts_jp.triggered.connect(self._on_toggle_tts_jp)
        self._action_tts_cn = tts_menu.addAction("Chinese")
        self._action_tts_cn.setCheckable(True)
        self._action_tts_cn.setEnabled(False)
        self._action_tts_cn.triggered.connect(self._on_toggle_tts_cn)
        settings_menu.addMenu(tts_menu)

        # Tools
        tools_menu = mb.addMenu("Tools")
        self._action_series_phrases = tools_menu.addAction(
            "Series Phrase Suggestions… (Ctrl+Shift+P)"
        )
        self._action_series_phrases.triggered.connect(self._on_series_phrases)
        self._action_series_phrases.setShortcut("Ctrl+Shift+P")

        # Special punctuations
        punct_menu = mb.addMenu("Special Punctuations")
        _punct_labels = [
            "Single Quote : 「　」  (F1)",
            "Double Quote : 『　』  (F2)",
            "Lenticular : 【　】  (F3)",
            "Ellipsis : …  (F4)",
            "Wave Dash : 〜  (F5)",
            "Single Title Bracket : 〈 〉  (F6)",
            "Double Title Bracket : 《 》  (F7)",
            "Long Dash : ー  (F8)",
            "Heart : ♡  (F9)",
        ]
        for i, label in enumerate(_punct_labels):
            act = punct_menu.addAction(label)
            act.setShortcut(f"F{i + 1}")
            act.triggered.connect(lambda checked, idx=i: self._insert_punctuation(idx))

        # Clipboard
        self._action_clipboard = mb.addAction("Clipboard (CTRL+I)")
        self._action_clipboard.triggered.connect(self._on_clipboard_export)
        self._action_clipboard.setShortcut("Ctrl+I")
        self._action_clipboard.setEnabled(False)

        # Help
        help_menu = mb.addMenu("Help")
        help_menu.addAction("Statistics…").triggered.connect(self._on_stats)
        help_menu.addSeparator()
        help_menu.addAction("About").triggered.connect(self._on_about)

    def _setup_central_widget(self) -> None:
        font = QFont()
        font.setFamilies(_CJK_FAMILIES)
        font.setPointSizeF(12.5)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
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

        saved = self._settings.splitter_state
        if not saved.isEmpty():
            self._splitter.restoreState(saved)
        else:
            self._splitter.setSizes([300, 52, 52, 137])

        layout.addWidget(self._splitter)

        for widget in (self._review_top, self._raw_line,
                       self._translated_line, self._review_bottom):
            widget.installEventFilter(self)

    def _setup_statusbar(self) -> None:
        sb = self.statusBar()
        self._completion_label = QLabel("0% Complete")
        self._line_label = QLabel("Line: xxxx/xxxx")
        self._word_label = QLabel("xxxx Words")
        self._filesaved_label = QLabel("")
        self._stats_label = _ClickableLabel("")
        self._stats_label.clicked.connect(self._on_stats)
        sb.addWidget(self._completion_label)
        sb.addWidget(self._line_label)
        sb.addWidget(self._word_label)
        sb.addPermanentWidget(self._stats_label)
        sb.addPermanentWidget(self._filesaved_label)
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

        # Auto-save: repeating timer; started when a file is loaded.
        # Interval is settings.auto_save minutes (default 5).
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._on_autosave_timer)

    def _load_initial_state(self) -> None:
        self._update_parse_chars()
        self._load_glossary_for_profile()
        self._load_spell_dict()
        if self._settings.on_top:
            # During __init__ the window is not yet visible, so just set the
            # flag.  Calling show() here (as _set_topmost does) would cause a
            # premature native-window creation + flash before main() shows us.
            self.setWindowFlags(
                self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
            )
        self._try_init_tts()

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
        """Attempt to initialise pyttsx3; silently disable TTS menu if unavailable."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            for v in (voices or []):
                name = getattr(v, "name", "")
                if "ja" in name.lower() or "japanese" in name.lower() or "haruka" in name.lower():
                    self._action_tts_jp.setEnabled(True)
                elif "zh" in name.lower() or "chinese" in name.lower() or "huihui" in name.lower():
                    self._action_tts_cn.setEnabled(True)
            engine.stop()
            self._tts_engine = engine
        except Exception:
            self._tts_engine = None

    # ------------------------------------------------------------------
    # Content loading
    # ------------------------------------------------------------------

    def load_content(self, text: str, *, title: str = "Untitled",
                     series_title: str = "", series_order: int = 0,
                     chapter_title: str = "") -> None:
        """Parse a SEPERATOR-format file and initialise the UI. (Public for tests.)"""
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
        """Load a document from the DB into the UI."""
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
        """Populate all UI widgets from the current _raw_lines/_translated_lines state."""
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

        self._action_save.setEnabled(True)
        self._action_export.setEnabled(True)
        self._action_clipboard.setEnabled(True)
        self._translated_line.setFocus()
        self._start_clipboard_timer()
        self._restart_autosave_timer()
        self._update_stats_label()

    def _save_to_db(self) -> None:
        """Full save of all lines to DB."""
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
            self._update_stats_label()

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
            else:
                self._write_file()

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

    def _on_new(self) -> None:
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
                )

    def _on_open(self) -> None:
        from translation_assistant.ui.dlg_open import OpenDocumentDialog
        with self._topmost_suspended():
            dlg = OpenDocumentDialog(self._db, parent=self)
            if dlg.exec() and dlg.selected_doc_id is not None:
                self.open_document(dlg.selected_doc_id)

    def _on_import(self) -> None:
        """Import a legacy TXT file into the DB."""
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

    def _on_export(self) -> None:
        """Export current document to a TXT file."""
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

    def _on_db_export(self) -> None:
        """Copy ta.db to a user-chosen backup file."""
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
        """Replace ta.db with a backup file, then reload."""
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
        # Reset document state
        self._doc_id = None
        self._raw_lines = []
        self._translated_lines = []
        self._raw_section = ""
        self._array_pointer = 0
        self._parse_sentences = []
        self._parse_pointer = -1
        # Reset UI
        self._review_top.setPlainText(_HELP_TOP)
        self._review_bottom.setPlainText(_HELP_BOTTOM)
        self._raw_line.clear()
        self._translated_line.clear()
        self._action_save.setEnabled(False)
        self._action_export.setEnabled(False)
        self._load_glossary_for_profile()
        self._filesaved_label.setText("Database imported.")
        self._filesaved_timer.start()

    def _on_manage_series(self) -> None:
        from translation_assistant.ui.dlg_series import SeriesManagerDialog
        with self._topmost_suspended():
            dlg = SeriesManagerDialog(self._db, parent=self)
            dlg.exec()

    def _on_series_phrases(self) -> None:
        from translation_assistant.ui.dlg_series_phrases import SeriesPhrasesDialog, _get_series_for_doc
        with self._topmost_suspended():
            dlg = SeriesPhrasesDialog(
                self._db, self._settings,
                current_series=_get_series_for_doc(self._db, self._doc_id),
                parent=self,
            )
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
        self._settings.show_progress = self._action_progress.isChecked()
        self._settings.save()
        self._update_progress_visibility()

    def _on_toggle_on_top(self) -> None:
        enabled = self._action_on_top.isChecked()
        self._settings.on_top = enabled
        self._settings.save()
        self._set_topmost(enabled)

    def _on_toggle_tts_jp(self) -> None:
        if self._action_tts_jp.isChecked():
            self._action_tts_cn.setChecked(False)
            self._settings.tts = True
            self._settings.tts_lang = 0
        else:
            self._settings.tts = False
        self._settings.save()

    def _on_toggle_tts_cn(self) -> None:
        if self._action_tts_cn.isChecked():
            self._action_tts_jp.setChecked(False)
            self._settings.tts = True
            self._settings.tts_lang = 1
        else:
            self._settings.tts = False
        self._settings.save()

    def _on_about(self) -> None:
        QMessageBox.about(
            self, "About",
            "Programmed by: Pun\n"
            "Port of joeglens's Translation Assistant\n"
            f"Version {BUILD_DATE}\n"
            "https://github.com/Punllarena/TranslationAssistant-PySide6-Port"
        )

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
    # Context menu for translation box
    # ------------------------------------------------------------------

    def _on_translated_context_menu(self, pos) -> None:
        menu = QMenu(self)

        # Spell suggestions for the word under the right-click point
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

        # Standard edit actions (copy, paste, undo, …)
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
        """Route key events to navigation/action handlers. Returns True if consumed."""
        key = event.key()
        mods = event.modifiers()
        ctrl = mods == Qt.KeyboardModifier.ControlModifier

        # These work without a file loaded
        if ctrl and key == Qt.Key.Key_F:
            QApplication.clipboard().setText(self._translated_line.toPlainText())
            return True

        # Navigation and editing — require a file
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
    # Window management
    # ------------------------------------------------------------------

    def _set_topmost(self, enabled: bool) -> None:
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    @contextmanager
    def _topmost_suspended(self):
        was = self._settings.on_top
        if was:
            self._set_topmost(False)
        try:
            yield
        finally:
            if was:
                self._set_topmost(True)

    def _update_stats_label(self) -> None:
        try:
            stats = self._db.get_today_stats()
            self._stats_label.setText(
                f"Today: {stats['paragraphs']} ¶ / {stats['chars']:,} chars"
            )
            self._stats_label.setVisible(True)
        except Exception:
            self._stats_label.setVisible(False)

    def _on_stats(self) -> None:
        from translation_assistant.ui.dlg_stats import StatsDialog
        with self._topmost_suspended():
            StatsDialog(self._db, self).exec()

    def closeEvent(self, event) -> None:
        self._settings.splitter_state = self._splitter.saveState()
        self._save_current_translation()
        self._settings.save()
        super().closeEvent(event)

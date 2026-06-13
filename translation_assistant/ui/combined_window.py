"""
CombinedMainWindow — Translation Assistant + Translation Aggregator in one window.
"""
from pathlib import Path

from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QIcon, QKeySequence, QAction
from PySide6.QtWidgets import QMainWindow, QMenu, QSplitter

from translation_assistant.settings import AppSettings
from translation_assistant.ui.main_widget import TranslationAssistantWidget
from ta.ui.aggregator_widget import AggregatorWidget

_RESOURCES = Path(__file__).parent.parent / "resources"


class CombinedMainWindow(QMainWindow):

    def __init__(self, _settings: AppSettings | None = None, _db=None) -> None:
        super().__init__()
        self.setWindowTitle("Translation Assistant")
        self.resize(1200, 700)
        self.setMinimumSize(900, 500)

        icon_path = _RESOURCES / "TA.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._ta_widget = TranslationAssistantWidget(_settings=_settings, _db=_db)
        self._agg_widget = AggregatorWidget()

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(self._ta_widget)
        self._splitter.addWidget(self._agg_widget)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 1)
        self.setCentralWidget(self._splitter)

        self._setup_menubar()
        self._restore_splitter()
        self._connect_bridge()

        # Apply always-on-top from TA settings on startup
        if _settings is not None and _settings.on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

    # ------------------------------------------------------------------
    # Signal bridge
    # ------------------------------------------------------------------

    def _connect_bridge(self) -> None:
        self._ta_widget.source_sentence_changed.connect(
            self._agg_widget.translate_source
        )

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------

    def _setup_menubar(self) -> None:
        ta = self._ta_widget
        agg = self._agg_widget
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("File")
        file_menu.addAction(ta.action_new_doc)
        file_menu.addAction(ta.action_new_series)
        file_menu.addAction(ta.action_open)
        file_menu.addAction(ta.action_save)
        file_menu.addSeparator()
        file_menu.addAction(ta.action_import)
        file_menu.addAction(ta.action_export)
        file_menu.addAction(ta.action_manage_series)
        file_menu.addSeparator()
        file_menu.addAction(ta.action_db_export)
        file_menu.addAction(ta.action_db_import)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Settings
        settings_menu = mb.addMenu("Settings")
        settings_menu.addAction(ta.action_profile)
        settings_menu.addAction(ta.action_phrase)
        settings_menu.addSeparator()
        agg_settings_action = QAction("Aggregator Settings…", self)
        agg_settings_action.triggered.connect(agg.show_settings)
        settings_menu.addAction(agg_settings_action)
        subs_action = QAction("Substitutions…", self)
        subs_action.triggered.connect(agg.show_substitutions)
        settings_menu.addAction(subs_action)
        settings_menu.addSeparator()
        settings_menu.addAction(ta.action_progress)
        settings_menu.addAction(ta.action_tm)
        tts_menu = QMenu("Text-To-Speech", self)
        tts_menu.addAction(ta.action_tts_jp)
        tts_menu.addAction(ta.action_tts_cn)
        settings_menu.addMenu(tts_menu)

        # Special Punctuations
        punct_menu = mb.addMenu("Special Punctuations")
        for act in ta.punct_actions:
            punct_menu.addAction(act)

        # View
        view_menu = mb.addMenu("View")
        self._action_on_top = QAction("Always on Top", self, checkable=True)
        if hasattr(ta, '_settings'):
            self._action_on_top.setChecked(ta._settings.on_top)
        self._action_on_top.triggered.connect(self._toggle_topmost)
        view_menu.addAction(self._action_on_top)
        view_menu.addAction(ta.action_go_to_line)

        # Clipboard
        mb.addAction(ta.action_clipboard)

        # Tools
        tools_menu = mb.addMenu("Tools")
        history_action = QAction("History…", self)
        history_action.triggered.connect(agg.show_history)
        tools_menu.addAction(history_action)
        tools_menu.addSeparator()
        series_phrases_action = QAction("Series Phrase Suggestions… (Ctrl+Shift+P)", self)
        series_phrases_action.setShortcut("Ctrl+Shift+P")
        series_phrases_action.triggered.connect(self._on_series_phrases)
        tools_menu.addAction(series_phrases_action)
        tools_menu.addSeparator()
        tools_menu.addAction(ta.action_about)

        # Help
        help_menu = mb.addMenu("Help")
        setup_guide_action = QAction("Setup Guide…", self)
        setup_guide_action.triggered.connect(self._open_setup_guide)
        help_menu.addAction(setup_guide_action)

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    def _on_series_phrases(self) -> None:
        from translation_assistant.ui.dlg_series_phrases import SeriesPhrasesDialog
        ta = self._ta_widget
        series = ""
        if ta._doc_id is not None:
            try:
                doc = ta._db.get_document(ta._doc_id)
                series = doc.get("series_title", "")
            except Exception:
                pass
        dlg = SeriesPhrasesDialog(ta._db, ta._settings, current_series=series, parent=self)
        dlg.exec()

    def _open_setup_guide(self) -> None:
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        SetupGuideDialog(self).exec()

    def _toggle_topmost(self) -> None:
        flags = self.windowFlags()
        if flags & Qt.WindowType.WindowStaysOnTopHint:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
            self._action_on_top.setChecked(False)
            self._ta_widget.action_on_top.setChecked(False)
            self._ta_widget._settings.on_top = False
        else:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
            self._action_on_top.setChecked(True)
            self._ta_widget.action_on_top.setChecked(True)
            self._ta_widget._settings.on_top = True
        self._ta_widget._settings.save()
        self.show()

    # ------------------------------------------------------------------
    # Layout persistence
    # ------------------------------------------------------------------

    def _restore_splitter(self) -> None:
        from PySide6.QtCore import QSettings
        qs = self._ta_widget._settings._qs
        raw = qs.value("combined/splitter")
        if raw:
            self._splitter.restoreState(QByteArray.fromBase64(raw.encode()))

    def _save_splitter(self) -> None:
        qs = self._ta_widget._settings._qs
        state = self._splitter.saveState().toBase64().data().decode()
        qs.setValue("combined/splitter", state)

    def closeEvent(self, event) -> None:
        self._save_splitter()
        self._ta_widget.save_state()
        self._agg_widget.save_layout()
        super().closeEvent(event)

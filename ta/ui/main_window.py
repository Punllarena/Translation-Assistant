from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter,
    QSizePolicy,
)

from ta.config.settings import Settings, DEFAULT_CONFIG_PATH
from ta.config.languages import Language
from ta.core.clipboard import ClipboardMonitor
from ta.core.filter import auto_filter
from ta.core.history import HistoryStore
from ta.core.substitutions import SubstitutionStore
from ta.ui.source_panel import SourcePanel
from ta.ui.panels_container import PanelsContainer
from ta.ui.translation_panel import TranslationPanel

_LAYOUT_SNAPSHOTS: dict[int, dict] = {}


def _build_translator(name: str, cfg):
    """Instantiate a translator by backend name."""
    if name == "deepl":
        from ta.translators.deepl import DeepLTranslator
        return DeepLTranslator(cfg.api_key)
    if name == "google":
        from ta.translators.google import GoogleTranslator
        return GoogleTranslator(cfg.api_key)
    if name == "bing":
        from ta.translators.bing import BingTranslator
        return BingTranslator(cfg.api_key)
    if name == "libretranslate":
        from ta.translators.libretranslate import LibreTranslator
        return LibreTranslator(url=cfg.url or "http://localhost:5000", api_key=cfg.api_key)
    if name == "mecab":
        from ta.translators.mecab import MeCabTranslator
        return MeCabTranslator()
    if name == "jparser":
        from ta.translators.jparser import JParserTranslator
        return JParserTranslator()
    return None


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = Settings.load(DEFAULT_CONFIG_PATH)
        self._history = HistoryStore(max_bytes=self._settings.history_max_bytes)
        self._subs = SubstitutionStore.load()
        self._history_current_id: int | None = None
        self._pending_translations: dict[str, str] = {}

        self.setWindowTitle("Translation Aggregator")
        self.resize(900, 700)

        self._setup_ui()
        self._setup_menu()
        self._setup_shortcuts()
        self._setup_clipboard()
        self._restore_layout()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        self._source_panel = SourcePanel()
        self._source_panel.translate_requested.connect(self._on_translate)
        self._source_panel.clipboard_toggled.connect(self._on_clipboard_toggle)
        self._source_panel.languages_changed.connect(self._on_languages_changed)
        self._source_panel.history_prev_requested.connect(self._on_history_prev)
        self._source_panel.history_next_requested.connect(self._on_history_next)
        main_layout.addWidget(self._source_panel)

        self._panels = PanelsContainer()
        self._panels.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self._panels, stretch=1)

        for name in self._settings.layout_panels:
            cfg = self._settings.translators.get(name)
            if cfg is None or not cfg.enabled:
                continue
            translator = _build_translator(name, cfg)
            if translator is None:
                continue
            translator.translation_ready.connect(
                lambda text, n=name: self._on_translation_received(n, text)
            )
            panel = TranslationPanel(translator)
            self._panels.add_panel(panel)

    def _setup_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        settings_action = QAction("&Settings…", self)
        settings_action.triggered.connect(self._show_settings)
        file_menu.addAction(settings_action)
        subs_action = QAction("S&ubstitutions…", self)
        subs_action.triggered.connect(self._show_substitutions)
        file_menu.addAction(subs_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = menubar.addMenu("&View")
        topmost_action = QAction("Always on &Top", self, checkable=True)
        topmost_action.triggered.connect(self._toggle_topmost)
        view_menu.addAction(topmost_action)

        tools_menu = menubar.addMenu("&Tools")
        history_action = QAction("&History…", self)
        history_action.triggered.connect(self._show_history)
        tools_menu.addAction(history_action)

    def _setup_shortcuts(self) -> None:
        # History navigation
        QShortcut(QKeySequence("Ctrl+Alt+Up"), self).activated.connect(self._on_history_prev)
        QShortcut(QKeySequence("Ctrl+Alt+Down"), self).activated.connect(self._on_history_next)
        QShortcut(QKeySequence("Ctrl+Alt+Prior"), self).activated.connect(self._on_history_prev)
        QShortcut(QKeySequence("Ctrl+Alt+Next"), self).activated.connect(self._on_history_next)

        # Transparency
        QShortcut(QKeySequence("Ctrl+Alt+-"), self).activated.connect(self._decrease_opacity)
        QShortcut(QKeySequence("Ctrl+Alt++"), self).activated.connect(self._increase_opacity)

        # Always on top
        QShortcut(QKeySequence("Ctrl+Alt+A"), self).activated.connect(self._toggle_topmost)

        # Layout snapshots: Shift+Alt+1..9 = save, Alt+1..9 = restore
        for i in range(1, 10):
            QShortcut(QKeySequence(f"Shift+Alt+{i}"), self).activated.connect(
                lambda n=i: self._save_layout_snapshot(n)
            )
            QShortcut(QKeySequence(f"Alt+{i}"), self).activated.connect(
                lambda n=i: self._restore_layout_snapshot(n)
            )

    def _setup_clipboard(self) -> None:
        self._clipboard = ClipboardMonitor(self._settings.max_clipboard_chars)
        self._clipboard.text_received.connect(self._on_clipboard_text)

    # ------------------------------------------------------------------
    # Translation pipeline
    # ------------------------------------------------------------------

    def _on_translate(self, text: str) -> None:
        text = self._preprocess(text)
        if not text:
            return
        self._pending_translations = {}
        self._panels.translate_all(
            text,
            self._source_panel.src_language(),
            self._source_panel.dst_language(),
        )

    def _preprocess(self, text: str) -> str:
        if self._settings.enable_substitutions:
            profile = self._subs.detect_active_profile()
            text = self._subs.apply(text, profile)
        return auto_filter(text, self._settings.filter)

    def _on_clipboard_text(self, text: str) -> None:
        self._source_panel.set_text(text)
        self._on_translate(text)

    def _on_clipboard_toggle(self, enabled: bool) -> None:
        self._clipboard.enabled = enabled

    def _on_languages_changed(self, src: Language, dst: Language) -> None:
        self._panels.set_languages(src, dst)

    def _on_translation_received(self, name: str, text: str) -> None:
        self._pending_translations[name] = text
        # Save to history once all enabled panels have responded (best-effort)
        # For simplicity, we save incrementally on each response
        source = self._source_panel.get_text()
        self._history.append(source, dict(self._pending_translations))

    # ------------------------------------------------------------------
    # History navigation
    # ------------------------------------------------------------------

    def _on_history_prev(self) -> None:
        entry = self._history.navigate(self._history_current_id, -1)
        if entry:
            self._history_current_id = entry.id
            self._source_panel.set_text(entry.source)

    def _on_history_next(self) -> None:
        entry = self._history.navigate(self._history_current_id, +1)
        if entry:
            self._history_current_id = entry.id
            self._source_panel.set_text(entry.source)

    # ------------------------------------------------------------------
    # Window controls
    # ------------------------------------------------------------------

    def _toggle_topmost(self) -> None:
        flags = self.windowFlags()
        if flags & Qt.WindowType.WindowStaysOnTopHint:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        self.show()

    def _increase_opacity(self) -> None:
        self.setWindowOpacity(min(1.0, self.windowOpacity() + 0.05))

    def _decrease_opacity(self) -> None:
        self.setWindowOpacity(max(0.1, self.windowOpacity() - 0.05))

    def _save_layout_snapshot(self, slot: int) -> None:
        _LAYOUT_SNAPSHOTS[slot] = {
            "panels": self._panels.save_layout(),
            "geometry": self.saveGeometry().toBase64().data().decode(),
        }

    def _restore_layout_snapshot(self, slot: int) -> None:
        data = _LAYOUT_SNAPSHOTS.get(slot)
        if data:
            self._panels.restore_layout(data.get("panels", {}))

    # ------------------------------------------------------------------
    # Layout persistence
    # ------------------------------------------------------------------

    def _restore_layout(self) -> None:
        path = DEFAULT_CONFIG_PATH.parent / "layout.json"
        if path.exists():
            try:
                d = json.loads(path.read_text())
                self._panels.restore_layout(d.get("panels", {}))
                if "geometry" in d:
                    from PySide6.QtCore import QByteArray
                    self.restoreGeometry(QByteArray.fromBase64(d["geometry"].encode()))
            except Exception:
                pass

    def _save_layout(self) -> None:
        path = DEFAULT_CONFIG_PATH.parent / "layout.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        d = {
            "panels": self._panels.save_layout(),
            "geometry": self.saveGeometry().toBase64().data().decode(),
        }
        path.write_text(json.dumps(d))

    def closeEvent(self, event) -> None:
        self._save_layout()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Dialogs (stubs — implemented in Phase 7)
    # ------------------------------------------------------------------

    def _show_settings(self) -> None:
        from ta.ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec():
            self._settings = dlg.apply()
            self._settings.save(DEFAULT_CONFIG_PATH)

    def _show_substitutions(self) -> None:
        from ta.ui.dialogs.substitutions_dialog import SubstitutionsDialog
        dlg = SubstitutionsDialog(self._subs, self)
        if dlg.exec():
            self._subs.save()

    def _show_history(self) -> None:
        from ta.ui.dialogs.history_dialog import HistoryDialog
        dlg = HistoryDialog(self._history, self)
        dlg.exec()

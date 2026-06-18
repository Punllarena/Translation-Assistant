from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QSizePolicy,
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


def _build_translator(name: str, cfg):
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
    if name == "ollama":
        from ta.translators.ollama import OllamaTranslator
        return OllamaTranslator(
            url=cfg.url or "http://localhost:11434",
            model=cfg.model or "",
            system_prompt=cfg.system_prompt or "",
        )
    return None


class AggregatorWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = Settings.load(DEFAULT_CONFIG_PATH)
        self._history = HistoryStore(max_bytes=self._settings.history_max_bytes)
        self._subs = SubstitutionStore.load()
        self._history_current_id: int | None = None
        self._pending_translations: dict[str, str] = {}
        self._current_source: str = ""

        self._setup_ui()
        self._setup_clipboard()
        self._restore_layout()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
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

    def _setup_clipboard(self) -> None:
        self._clipboard = ClipboardMonitor(self._settings.max_clipboard_chars)
        self._clipboard.text_received.connect(self._on_clipboard_text)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @Slot(str)
    def translate_source(self, text: str) -> None:
        """Called by CombinedMainWindow when TA navigates to a new sentence."""
        self._source_panel.set_text(text)
        self._on_translate(text)

    # ------------------------------------------------------------------
    # Translation pipeline
    # ------------------------------------------------------------------

    def _on_translate(self, text: str) -> None:
        text = self._preprocess(text)
        if not text:
            return
        self._current_source = text
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
        if not text:
            return
        self._pending_translations[name] = text
        self._history.append(self._current_source, dict(self._pending_translations))

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
    # Dialogs — callable by CombinedMainWindow menu actions
    # ------------------------------------------------------------------

    def show_settings(self) -> None:
        from ta.ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec():
            self._settings = dlg.apply()
            for name in self._settings.translators:
                if name not in self._settings.layout_panels:
                    self._settings.layout_panels.append(name)
            self._settings.save(DEFAULT_CONFIG_PATH)

    def show_substitutions(self) -> None:
        from ta.ui.dialogs.substitutions_dialog import SubstitutionsDialog
        dlg = SubstitutionsDialog(self._subs, self)
        if dlg.exec():
            self._subs.save()

    def show_history(self) -> None:
        from ta.ui.dialogs.history_dialog import HistoryDialog
        dlg = HistoryDialog(self._history, self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Layout persistence
    # ------------------------------------------------------------------

    def _restore_layout(self) -> None:
        path = DEFAULT_CONFIG_PATH.parent / "layout.json"
        if path.exists():
            try:
                d = json.loads(path.read_text())
                self._panels.restore_layout(d.get("panels", {}))
            except Exception:
                pass

    def save_layout(self) -> None:
        path = DEFAULT_CONFIG_PATH.parent / "layout.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        d = {"panels": self._panels.save_layout()}
        path.write_text(json.dumps(d))

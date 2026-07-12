from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
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
        self._mt_cache: dict[tuple[str, Language, Language], str] = {}
        self._ollama_chunks: list[str] = []
        self._ollama_debounce = QTimer(self)
        self._ollama_debounce.setSingleShot(True)
        self._ollama_debounce.setInterval(400)
        self._ollama_debounce.timeout.connect(self._fire_ollama)

        self._setup_ui()
        self._setup_clipboard()
        self._restore_layout()
        self._seed_mt_cache()

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

        self._ollama_panel: TranslationPanel | None = None
        self._ollama_translator = None
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
            if name == "ollama":
                self._ollama_translator = translator
                self._ollama_panel = TranslationPanel(translator)
                # Accumulate streamed tokens so the finished translation can
                # be cached and written to history (ready itself emits "").
                translator.translation_started.connect(self._ollama_chunks.clear)
                translator.translation_chunk.connect(self._ollama_chunks.append)
                translator.translation_ready.connect(self._on_ollama_ready)
                # Insert between source panel (0) and panels container (1)
                main_layout.insertWidget(1, self._ollama_panel)
                continue
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

    def get_translator(self, name: str):
        """Return the translator instance for a panel by name, or None."""
        if name.lower() == "ollama":
            return self._ollama_translator
        for panel in self._panels._panels:
            if panel.translator_name == name:
                return panel._translator
        return None

    # ------------------------------------------------------------------
    # Translation pipeline
    # ------------------------------------------------------------------

    def _on_translate(self, text: str) -> None:
        text = self._preprocess(text)
        if not text:
            return
        self._current_source = text
        self._pending_translations = {}
        src = self._source_panel.src_language()
        dst = self._source_panel.dst_language()
        self._panels.translate_all(text, src, dst)
        if self._ollama_panel is None:
            return
        # Abort any in-flight generation for the line we just left.
        self._ollama_translator.halt()
        cached = self._mt_cache.get((text, src, dst))
        if cached is not None:
            self._ollama_debounce.stop()
            self._ollama_panel.show_result(cached, text, src, dst)
        else:
            # Debounce so rapid line-skipping only translates where we settle.
            self._ollama_debounce.start()

    def _fire_ollama(self) -> None:
        text = self._current_source
        if not text:
            return
        src = self._source_panel.src_language()
        dst = self._source_panel.dst_language()
        self._ollama_panel.translate(text, src, dst)

    def _on_ollama_ready(self, _ignored: str) -> None:
        text = "".join(self._ollama_chunks)
        if not text:
            return
        key = self._ollama_panel.request_key()
        self._mt_cache[key] = text
        if key[0] == self._current_source:
            self._on_translation_received("ollama", text)

    def _seed_mt_cache(self) -> None:
        if self._ollama_panel is None:
            return
        # ponytail: history doesn't record languages; seed under the pair
        # active at startup. Store languages per entry if that ever bites.
        src = self._source_panel.src_language()
        dst = self._source_panel.dst_language()
        for e in self._history.all_entries():
            t = e.translations.get("ollama")
            if t:
                self._mt_cache[(e.source, src, dst)] = t

    def _preprocess(self, text: str) -> str:
        if self._settings.enable_substitutions:
            profile = self._subs.detect_active_profile()
            text = self._subs.apply(text, profile)
        return auto_filter(text, self._settings.filter)

    def _on_clipboard_text(self, text: str) -> None:
        if self._preprocess(text) == self._current_source:
            # TA's own navigation clipboard write mirrors what we just
            # translated via source_sentence_changed; skip the resend.
            return
        self._source_panel.set_text(text)
        self._on_translate(text)

    def _on_clipboard_toggle(self, enabled: bool) -> None:
        self._clipboard.enabled = enabled

    def _on_languages_changed(self, src: Language, dst: Language) -> None:
        self._panels.set_languages(src, dst)
        if self._ollama_panel is not None:
            self._ollama_panel.set_languages(src, dst)

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

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QTabWidget, QWidget,
    QFormLayout, QVBoxLayout, QHBoxLayout,
    QComboBox, QCheckBox, QLineEdit, QLabel,
    QSpinBox, QGroupBox, QScrollArea, QPushButton, QPlainTextEdit,
)
from PySide6.QtCore import Qt

from ta.config.settings import Settings, TranslatorConfig
from ta.config.languages import Language, display_names


_CHAR_REPEAT_MODES = ["none", "auto_constant", "infinite", "auto_advanced", "custom"]
_LINE_BREAK_MODES = ["remove_all", "remove_some", "keep"]

_TRANSLATOR_LABELS = {
    "deepl": "DeepL",
    "google": "Google Translate",
    "bing": "Bing/Azure",
    "libretranslate": "LibreTranslate",
    "mecab": "MeCab",
    "jparser": "JParser",
    "ollama": "Ollama (Local AI)",
}
_ENV_HINTS = {
    "deepl": "DEEPL_API_KEY",
    "google": "GOOGLE_TRANSLATE_KEY",
    "bing": "AZURE_TRANSLATOR_KEY",
}


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._translator_widgets: dict[str, tuple[QCheckBox, QLineEdit]] = {}
        self._translator_url_widgets: dict[str, QLineEdit] = {}
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self._setup_ui()
        self._load(settings)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._tabs.addTab(self._make_general_tab(), "General")
        self._tabs.addTab(self._make_translators_tab(), "Translators")
        self._tabs.addTab(self._make_filter_tab(), "Filter")
        self._tabs.addTab(self._make_fonts_tab(), "Fonts")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _make_general_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        lang_names = display_names()

        self._src_combo = QComboBox()
        self._dst_combo = QComboBox()
        for name, lang in lang_names:
            self._src_combo.addItem(name, lang)
            self._dst_combo.addItem(name, lang)
        form.addRow("Source language:", self._src_combo)
        form.addRow("Target language:", self._dst_combo)

        self._clipboard_cb = QCheckBox("Enable clipboard monitoring")
        form.addRow(self._clipboard_cb)

        self._max_clipboard_spin = QSpinBox()
        self._max_clipboard_spin.setRange(10, 5000)
        form.addRow("Max clipboard chars:", self._max_clipboard_spin)

        self._subs_cb = QCheckBox("Enable substitutions")
        form.addRow(self._subs_cb)

        return w

    def _make_translators_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        scroll.setWidget(container)
        vbox = QVBoxLayout(container)

        for name, label in _TRANSLATOR_LABELS.items():
            group = QGroupBox(label)
            form = QFormLayout(group)

            enable_cb = QCheckBox("Enabled")
            form.addRow(enable_cb)

            api_edit = QLineEdit()
            api_edit.setPlaceholderText(f"API key (or set {_ENV_HINTS.get(name, '')})")
            api_edit.setEchoMode(QLineEdit.EchoMode.Password)
            if name in ("mecab", "jparser", "ollama"):
                api_edit.setEnabled(False)
                api_edit.setPlaceholderText("No key required")
            form.addRow("API key:", api_edit)

            if name == "libretranslate":
                url_edit = QLineEdit()
                url_edit.setPlaceholderText("http://localhost:5000")
                form.addRow("Server URL:", url_edit)
                self._translator_url_widgets[name] = url_edit

            if name == "ollama":
                url_edit = QLineEdit()
                url_edit.setPlaceholderText("http://localhost:11434")
                form.addRow("Server URL:", url_edit)
                self._translator_url_widgets[name] = url_edit

                test_row_w = QWidget()
                test_row_l = QHBoxLayout(test_row_w)
                test_row_l.setContentsMargins(0, 0, 0, 0)
                self._ollama_test_btn = QPushButton("Test Connection")
                self._ollama_status_lbl = QLabel("")
                test_row_l.addWidget(self._ollama_test_btn)
                test_row_l.addWidget(self._ollama_status_lbl)
                test_row_l.addStretch()
                form.addRow(test_row_w)
                self._ollama_test_btn.clicked.connect(self._on_ollama_test)

                self._ollama_model_combo = QComboBox()
                self._ollama_model_combo.setEditable(True)
                self._ollama_model_combo.setEnabled(False)
                form.addRow("Model:", self._ollama_model_combo)

                self._ollama_prompt_edit = QPlainTextEdit()
                self._ollama_prompt_edit.setFixedHeight(120)
                form.addRow("System prompt:", self._ollama_prompt_edit)

            self._translator_widgets[name] = (enable_cb, api_edit)
            vbox.addWidget(group)

        vbox.addStretch()
        return scroll

    def _make_filter_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._char_repeat_combo = QComboBox()
        for mode in _CHAR_REPEAT_MODES:
            self._char_repeat_combo.addItem(mode, mode)
        form.addRow("Char repeat mode:", self._char_repeat_combo)

        self._line_break_combo = QComboBox()
        for mode in _LINE_BREAK_MODES:
            self._line_break_combo.addItem(mode, mode)
        form.addRow("Line break mode:", self._line_break_combo)

        self._phrase_repeat_cb = QCheckBox("Enable phrase repeat filter")
        form.addRow(self._phrase_repeat_cb)

        self._phrase_min_spin = QSpinBox()
        self._phrase_min_spin.setRange(1, 50)
        form.addRow("Phrase min length:", self._phrase_min_spin)

        self._phrase_max_spin = QSpinBox()
        self._phrase_max_spin.setRange(10, 500)
        form.addRow("Phrase max length:", self._phrase_max_spin)

        return w

    def _make_fonts_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._font_face_edit = QLineEdit()
        form.addRow("Font face:", self._font_face_edit)

        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(6, 72)
        form.addRow("Font size:", self._font_size_spin)

        self._font_bold_cb = QCheckBox("Bold")
        self._font_italic_cb = QCheckBox("Italic")
        form.addRow(self._font_bold_cb)
        form.addRow(self._font_italic_cb)

        return w

    def _on_ollama_test(self) -> None:
        import httpx
        self._ollama_test_btn.setEnabled(False)
        self._ollama_status_lbl.setText("Testing…")
        url = self._translator_url_widgets["ollama"].text().rstrip("/")
        prev_model = self._ollama_model_combo.currentText()
        try:
            resp = httpx.get(f"{url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            self._ollama_model_combo.clear()
            for m in models:
                self._ollama_model_combo.addItem(m)
            self._ollama_model_combo.setEnabled(True)
            self._ollama_status_lbl.setText("Connected ✓")
            if prev_model:
                idx = self._ollama_model_combo.findText(prev_model)
                if idx >= 0:
                    self._ollama_model_combo.setCurrentIndex(idx)
                else:
                    self._ollama_model_combo.insertItem(0, prev_model)
                    self._ollama_model_combo.setCurrentIndex(0)
        except Exception as exc:
            self._ollama_status_lbl.setText(f"Error: {exc}")
            self._ollama_model_combo.clear()
            self._ollama_model_combo.setEnabled(False)
        finally:
            self._ollama_test_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Load / apply
    # ------------------------------------------------------------------

    def _load(self, s: Settings) -> None:
        self._set_combo_by_data(self._src_combo, s.src_language)
        self._set_combo_by_data(self._dst_combo, s.dst_language)
        self._clipboard_cb.setChecked(s.auto_clipboard)
        self._max_clipboard_spin.setValue(s.max_clipboard_chars)
        self._subs_cb.setChecked(s.enable_substitutions)

        for name, (cb, edit) in self._translator_widgets.items():
            cfg = s.translators.get(name)
            if cfg:
                cb.setChecked(cfg.enabled)
                edit.setText(cfg.api_key)
                if name in self._translator_url_widgets:
                    self._translator_url_widgets[name].setText(cfg.url)
            if name == "ollama":
                from ta.config.settings import DEFAULT_OLLAMA_SYSTEM_PROMPT
                if cfg and cfg.model:
                    self._ollama_model_combo.addItem(cfg.model)
                    self._ollama_model_combo.setCurrentIndex(0)
                    self._ollama_model_combo.setEnabled(True)
                self._ollama_prompt_edit.setPlainText(
                    cfg.system_prompt if cfg and cfg.system_prompt
                    else DEFAULT_OLLAMA_SYSTEM_PROMPT
                )

        self._set_combo_by_data(self._char_repeat_combo, s.filter.char_repeat_mode)
        self._set_combo_by_data(self._line_break_combo, s.filter.line_break_mode)
        self._phrase_repeat_cb.setChecked(s.filter.phrase_repeat)
        self._phrase_min_spin.setValue(s.filter.phrase_min)
        self._phrase_max_spin.setValue(s.filter.phrase_max)

        self._font_face_edit.setText(s.font.face)
        self._font_size_spin.setValue(s.font.size)
        self._font_bold_cb.setChecked(s.font.bold)
        self._font_italic_cb.setChecked(s.font.italic)

    def apply(self) -> Settings:
        """Return a new Settings with current dialog values."""
        import copy
        s = copy.deepcopy(self._settings)

        s.src_language = self._src_combo.currentData()
        s.dst_language = self._dst_combo.currentData()
        s.auto_clipboard = self._clipboard_cb.isChecked()
        s.max_clipboard_chars = self._max_clipboard_spin.value()
        s.enable_substitutions = self._subs_cb.isChecked()

        for name, (cb, edit) in self._translator_widgets.items():
            if name not in s.translators:
                s.translators[name] = TranslatorConfig()
            s.translators[name].enabled = cb.isChecked()
            s.translators[name].api_key = edit.text()
            if name in self._translator_url_widgets:
                s.translators[name].url = self._translator_url_widgets[name].text()
            if name == "ollama":
                s.translators[name].model = self._ollama_model_combo.currentText()
                s.translators[name].system_prompt = self._ollama_prompt_edit.toPlainText()

        s.filter.char_repeat_mode = self._char_repeat_combo.currentData()
        s.filter.line_break_mode = self._line_break_combo.currentData()
        s.filter.phrase_repeat = self._phrase_repeat_cb.isChecked()
        s.filter.phrase_min = self._phrase_min_spin.value()
        s.filter.phrase_max = self._phrase_max_spin.value()

        s.font.face = self._font_face_edit.text()
        s.font.size = self._font_size_spin.value()
        s.font.bold = self._font_bold_cb.isChecked()
        s.font.italic = self._font_italic_cb.isChecked()

        return s

    def _on_ok(self) -> None:
        self._accepted_settings = self.apply()
        self.accept()

    # ------------------------------------------------------------------
    # Test-facing accessors
    # ------------------------------------------------------------------

    def src_language(self) -> Language:
        return self._src_combo.currentData()

    def dst_language(self) -> Language:
        return self._dst_combo.currentData()

    def auto_clipboard(self) -> bool:
        return self._clipboard_cb.isChecked()

    def char_repeat_mode(self) -> str:
        return self._char_repeat_combo.currentData()

    def translator_enabled(self, name: str) -> bool:
        cb, _ = self._translator_widgets.get(name, (None, None))
        return cb.isChecked() if cb else False

    def translator_api_key(self, name: str) -> str:
        _, edit = self._translator_widgets.get(name, (None, None))
        return edit.text() if edit else ""

    def set_translator_enabled(self, name: str, enabled: bool) -> None:
        cb, _ = self._translator_widgets.get(name, (None, None))
        if cb:
            cb.setChecked(enabled)

    def set_translator_api_key(self, name: str, key: str) -> None:
        _, edit = self._translator_widgets.get(name, (None, None))
        if edit:
            edit.setText(key)

    def translator_url(self, name: str) -> str:
        edit = self._translator_url_widgets.get(name)
        return edit.text() if edit else ""

    def set_translator_url(self, name: str, url: str) -> None:
        edit = self._translator_url_widgets.get(name)
        if edit:
            edit.setText(url)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, data) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == data:
                combo.setCurrentIndex(i)
                return

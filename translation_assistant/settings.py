"""
Application settings backed by QSettings (ini file per user).
"""
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings


def _get_app_root() -> Path:
    """Return the project root in dev mode, or the bundle directory when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# AppSettings
# ---------------------------------------------------------------------------

class AppSettings:
    """
    Typed wrapper around QSettings.
    All defaults match the original VB app's My.Settings values.

    The optional `_qs` parameter is a test seam — pass a temp-file-backed
    QSettings instance to avoid writing to the real user config during tests.
    """

    _DEFAULTS: dict = {
        "ParseChar": "、 。 ？ ！ 「 」 …… ",
        "ProfileUsed": "Default",
        "ShowProgress": True,
        "AutoSave": 5,
        "OnTop": True,
        "TTS": False,
        "TTSLang": 0,
    }

    def __init__(self, _qs: QSettings | None = None) -> None:
        self._qs = _qs if _qs is not None else QSettings("joeglens", "TranslationAssistant")

    @property
    def db_path(self) -> Path:
        """Path to ta.db next to the executable (or repo root in dev)."""
        return _get_app_root() / "ta.db"

    # --- parse characters ---

    @property
    def parse_char(self) -> str:
        return self._qs.value("ParseChar", self._DEFAULTS["ParseChar"])

    @parse_char.setter
    def parse_char(self, value: str) -> None:
        self._qs.setValue("ParseChar", value)

    # --- active profile name ---

    @property
    def profile_used(self) -> str:
        return self._qs.value("ProfileUsed", self._DEFAULTS["ProfileUsed"])

    @profile_used.setter
    def profile_used(self, value: str) -> None:
        self._qs.setValue("ProfileUsed", value)

    # --- show progress ---

    @property
    def show_progress(self) -> bool:
        return self._qs.value("ShowProgress", self._DEFAULTS["ShowProgress"], type=bool)

    @show_progress.setter
    def show_progress(self, value: bool) -> None:
        self._qs.setValue("ShowProgress", value)

    # --- auto-save interval (minutes) ---

    @property
    def auto_save(self) -> int:
        return self._qs.value("AutoSave", self._DEFAULTS["AutoSave"], type=int)

    @auto_save.setter
    def auto_save(self, value: int) -> None:
        self._qs.setValue("AutoSave", value)

    # --- always on top ---

    @property
    def on_top(self) -> bool:
        return self._qs.value("OnTop", self._DEFAULTS["OnTop"], type=bool)

    @on_top.setter
    def on_top(self, value: bool) -> None:
        self._qs.setValue("OnTop", value)

    # --- TTS enabled ---

    @property
    def tts(self) -> bool:
        return self._qs.value("TTS", self._DEFAULTS["TTS"], type=bool)

    @tts.setter
    def tts(self, value: bool) -> None:
        self._qs.setValue("TTS", value)

    # --- TTS language (0 = Japanese, 1 = Chinese) ---

    @property
    def tts_lang(self) -> int:
        return self._qs.value("TTSLang", self._DEFAULTS["TTSLang"], type=int)

    @tts_lang.setter
    def tts_lang(self, value: int) -> None:
        self._qs.setValue("TTSLang", value)

    # --- splitter layout state ---

    @property
    def splitter_state(self) -> QByteArray:
        return self._qs.value("SplitterState", QByteArray())

    @splitter_state.setter
    def splitter_state(self, value: QByteArray) -> None:
        self._qs.setValue("SplitterState", value)

    # --- translation memory visible ---

    @property
    def tm_visible(self) -> bool:
        return self._qs.value("TMVisible", True, type=bool)

    @tm_visible.setter
    def tm_visible(self, value: bool) -> None:
        self._qs.setValue("TMVisible", value)

    # --- setup wizard shown ---

    @property
    def setup_wizard_shown(self) -> bool:
        return self._qs.value("SetupWizardShown", False, type=bool)

    @setup_wizard_shown.setter
    def setup_wizard_shown(self, value: bool) -> None:
        self._qs.setValue("SetupWizardShown", value)

    # --- last opened document id ---

    @property
    def last_doc_id(self) -> int | None:
        val = self._qs.value("LastDocId", None)
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    @last_doc_id.setter
    def last_doc_id(self, value: int | None) -> None:
        if value is None:
            self._qs.remove("LastDocId")
        else:
            self._qs.setValue("LastDocId", value)

    def save(self) -> None:
        """Flush settings to disk immediately."""
        self._qs.sync()

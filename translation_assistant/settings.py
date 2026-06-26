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
        "FontSize": 12.5,
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

    # --- editor font size ---

    @property
    def font_size(self) -> float:
        return self._qs.value("FontSize", self._DEFAULTS["FontSize"], type=float)

    @font_size.setter
    def font_size(self, value: float) -> None:
        self._qs.setValue("FontSize", value)

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

    # --- WordPress endpoint URL ---

    @property
    def wp_endpoint_url(self) -> str:
        return self._qs.value("WPEndpointUrl", "")

    @wp_endpoint_url.setter
    def wp_endpoint_url(self, value: str) -> None:
        self._qs.setValue("WPEndpointUrl", value)

    # --- WordPress API key ---

    @property
    def wp_api_key(self) -> str:
        return self._qs.value("WPApiKey", "")

    @wp_api_key.setter
    def wp_api_key(self, value: str) -> None:
        self._qs.setValue("WPApiKey", value)

    def save(self) -> None:
        """Flush settings to disk immediately."""
        self._qs.sync()

    # --- keyboard shortcuts ---

    def get_shortcut(self, key: str) -> str | None:
        return self._qs.value(f"shortcuts/{key}", None)

    def set_shortcut(self, key: str, value: str) -> None:
        self._qs.setValue(f"shortcuts/{key}", value)

    def clear_shortcut(self, key: str) -> None:
        self._qs.remove(f"shortcuts/{key}")

    def clear_shortcuts(self) -> None:
        self._qs.remove("shortcuts")

    # --- recent documents (list of doc IDs, most-recent first, max 10) ---

    @property
    def recent_doc_ids(self) -> list[int]:
        import json
        raw = self._qs.value("RecentDocIds", "[]")
        try:
            return list(json.loads(raw))
        except Exception:
            return []

    def add_to_recent(self, doc_id: int) -> None:
        import json
        ids = self.recent_doc_ids
        if doc_id in ids:
            ids.remove(doc_id)
        ids.insert(0, doc_id)
        self._qs.setValue("RecentDocIds", json.dumps(ids[:10]))

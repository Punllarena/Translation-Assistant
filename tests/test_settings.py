"""
Tests for translation_assistant.settings.
"""
import pytest
from pathlib import Path
from PySide6.QtCore import QSettings

from translation_assistant.settings import AppSettings, _get_app_root


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

def test_default_parse_char(tmp_settings):
    assert tmp_settings.parse_char == "、 。 ？ ！ 「 」 …… "


def test_default_profile_used(tmp_settings):
    assert tmp_settings.profile_used == "Default"


def test_default_show_progress(tmp_settings):
    assert tmp_settings.show_progress is True


def test_default_auto_save(tmp_settings):
    assert tmp_settings.auto_save == 5


def test_default_on_top(tmp_settings):
    assert tmp_settings.on_top is True


# ---------------------------------------------------------------------------
# Persistence — write in one instance, read back from a new instance
# ---------------------------------------------------------------------------

def test_persistence_profile_used(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")

    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.profile_used = "MyProfile"
    s1.save()

    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.profile_used == "MyProfile"


def test_persistence_bool_on_top(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")

    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.on_top = False
    s1.save()

    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.on_top is False


def test_persistence_multiple_values(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")

    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.profile_used = "JP_Novel"
    s1.show_progress = False
    s1.auto_save = 10
    s1.parse_char = "。 ？"
    s1.save()

    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.profile_used == "JP_Novel"
    assert s2.show_progress is False
    assert s2.auto_save == 10
    assert s2.parse_char == "。 ？"


# ---------------------------------------------------------------------------
# db_path — Stage B
# ---------------------------------------------------------------------------

def test_db_path_returns_path_ending_in_ta_db(tmp_settings):
    p = tmp_settings.db_path
    assert isinstance(p, Path)
    assert p.name == "ta.db"


def test_db_path_is_next_to_app_root(tmp_settings):
    """db_path must sit directly inside _get_app_root() (next to the executable)."""
    assert tmp_settings.db_path == _get_app_root() / "ta.db"


# ---------------------------------------------------------------------------
# tm_visible
# ---------------------------------------------------------------------------

def test_default_tm_visible(tmp_settings):
    assert tmp_settings.tm_visible is True


def test_tm_visible_roundtrip(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")
    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.tm_visible = False
    s1.save()
    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.tm_visible is False


# ---------------------------------------------------------------------------
# setup_wizard_shown
# ---------------------------------------------------------------------------

def test_default_setup_wizard_shown(tmp_settings):
    assert tmp_settings.setup_wizard_shown is False


def test_setup_wizard_shown_roundtrip(tmp_settings):
    tmp_settings.setup_wizard_shown = True
    assert tmp_settings.setup_wizard_shown is True


def test_setup_wizard_shown_reset(tmp_settings):
    tmp_settings.setup_wizard_shown = True
    tmp_settings.setup_wizard_shown = False
    assert tmp_settings.setup_wizard_shown is False


# ---------------------------------------------------------------------------
# last_doc_id
# ---------------------------------------------------------------------------

def test_default_last_doc_id(tmp_settings):
    assert tmp_settings.last_doc_id is None


def test_last_doc_id_roundtrip(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")
    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.last_doc_id = 42
    s1.save()
    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.last_doc_id == 42


def test_last_doc_id_none_clears(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")
    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.last_doc_id = 7
    s1.last_doc_id = None
    s1.save()
    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.last_doc_id is None


# ---------------------------------------------------------------------------
# WordPress settings
# ---------------------------------------------------------------------------

def test_wp_endpoint_url_default(tmp_settings):
    assert tmp_settings.wp_endpoint_url == ""


def test_wp_endpoint_url_roundtrip(tmp_settings):
    tmp_settings.wp_endpoint_url = "https://mysite.com/wp-json/ta-publisher/v1/publish"
    assert tmp_settings.wp_endpoint_url == "https://mysite.com/wp-json/ta-publisher/v1/publish"


def test_wp_api_key_default(tmp_settings):
    assert tmp_settings.wp_api_key == ""


def test_wp_api_key_roundtrip(tmp_settings):
    tmp_settings.wp_api_key = "secret123"
    assert tmp_settings.wp_api_key == "secret123"


def test_wp_password_enabled_default(tmp_settings):
    assert tmp_settings.wp_password_enabled is False


def test_wp_password_enabled_roundtrip(tmp_settings):
    tmp_settings.wp_password_enabled = True
    assert tmp_settings.wp_password_enabled is True
    tmp_settings.wp_password_enabled = False
    assert tmp_settings.wp_password_enabled is False


def test_wp_unlock_after_default(tmp_settings):
    assert tmp_settings.wp_unlock_after == 3


def test_wp_unlock_after_roundtrip(tmp_settings):
    tmp_settings.wp_unlock_after = 7
    assert tmp_settings.wp_unlock_after == 7


def test_wp_default_schedule_time_default(tmp_settings):
    assert tmp_settings.wp_default_schedule_time == ""


def test_wp_default_schedule_time_roundtrip(tmp_settings):
    tmp_settings.wp_default_schedule_time = "20:00"
    assert tmp_settings.wp_default_schedule_time == "20:00"


# ---------------------------------------------------------------------------
# Keyboard shortcuts
# ---------------------------------------------------------------------------

class TestShortcutPersistence:
    def test_get_shortcut_returns_none_when_unset(self, tmp_path):
        from PySide6.QtCore import QSettings
        from translation_assistant.settings import AppSettings
        qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        s = AppSettings(_qs=qs)
        assert s.get_shortcut("new_doc") is None

    def test_set_and_get_shortcut(self, tmp_path):
        from PySide6.QtCore import QSettings
        from translation_assistant.settings import AppSettings
        qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        s = AppSettings(_qs=qs)
        s.set_shortcut("new_doc", "Ctrl+Z")
        assert s.get_shortcut("new_doc") == "Ctrl+Z"

    def test_clear_shortcuts(self, tmp_path):
        from PySide6.QtCore import QSettings
        from translation_assistant.settings import AppSettings
        qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        s = AppSettings(_qs=qs)
        s.set_shortcut("new_doc", "Ctrl+Z")
        s.set_shortcut("open", "Ctrl+Y")
        s.clear_shortcuts()
        assert s.get_shortcut("new_doc") is None
        assert s.get_shortcut("open") is None


# ---------------------------------------------------------------------------
# font_size
# ---------------------------------------------------------------------------

def test_default_font_size(tmp_settings):
    assert tmp_settings.font_size == 12.5


def test_font_size_persists(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")
    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.font_size = 16.0
    s1.save()
    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.font_size == 16.0


# ---------------------------------------------------------------------------
# open_dialog_last_series
# ---------------------------------------------------------------------------

def test_open_dialog_last_series_default(tmp_settings):
    assert tmp_settings.open_dialog_last_series == ""


def test_open_dialog_last_series_roundtrip(tmp_settings):
    tmp_settings.open_dialog_last_series = "My Novel"
    assert tmp_settings.open_dialog_last_series == "My Novel"

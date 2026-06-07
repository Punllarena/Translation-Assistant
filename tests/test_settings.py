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


def test_default_tts(tmp_settings):
    assert tmp_settings.tts is False


def test_default_tts_lang(tmp_settings):
    assert tmp_settings.tts_lang == 0


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


def test_persistence_int_tts_lang(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")

    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.tts_lang = 1
    s1.save()

    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.tts_lang == 1


def test_persistence_multiple_values(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")

    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.profile_used = "JP_Novel"
    s1.tts = True
    s1.tts_lang = 0
    s1.show_progress = False
    s1.auto_save = 10
    s1.parse_char = "。 ？"
    s1.save()

    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.profile_used == "JP_Novel"
    assert s2.tts is True
    assert s2.tts_lang == 0
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

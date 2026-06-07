"""
Shared pytest fixtures.
"""
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

from translation_assistant.settings import AppSettings


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for the entire test session."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tmp_settings(qapp, tmp_path):
    """AppSettings backed by a temp INI file so nothing is written to the real user config."""
    qs = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return AppSettings(_qs=qs)

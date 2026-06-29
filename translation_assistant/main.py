"""
Application entry point.
"""
import sys
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from translation_assistant.db import Database
from translation_assistant.migration import run_startup_migration
from translation_assistant.settings import AppSettings, _get_app_root
from translation_assistant.ui.combined_window import CombinedMainWindow

_RESOURCES = (
    Path(sys._MEIPASS) / "translation_assistant" / "resources"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent / "resources"
)


def _load_qss() -> str:
    p = _RESOURCES / "style.qss"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _load_fonts() -> None:
    fonts_dir = _RESOURCES / "fonts"
    if fonts_dir.is_dir():
        for ttf in fonts_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(ttf))


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Translation Assistant")
    app.setOrganizationName("Pun")
    app.setStyle("Fusion")

    _load_fonts()
    app.setStyleSheet(_load_qss())

    settings = AppSettings()
    db = Database(settings.db_path)
    run_startup_migration(profile_dir=_get_app_root() / "Profile", db=db)

    window = CombinedMainWindow(_settings=settings, _db=db)
    window.show()

    if not settings.setup_wizard_shown:
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        settings.setup_wizard_shown = True
        SetupGuideDialog(window).exec()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

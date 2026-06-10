"""
Application entry point.
"""
import sys

from PySide6.QtWidgets import QApplication

from translation_assistant.db import Database
from translation_assistant.migration import run_startup_migration
from translation_assistant.settings import AppSettings, _get_app_root
from translation_assistant.ui.combined_window import CombinedMainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Translation Assistant")
    app.setOrganizationName("joeglens")

    settings = AppSettings()
    db = Database(settings.db_path)
    run_startup_migration(profile_dir=_get_app_root() / "Profile", db=db)

    window = CombinedMainWindow(_settings=settings, _db=db)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

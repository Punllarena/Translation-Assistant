"""
One-time filesystem → SQLite migration helper.
Called from main.py at startup before the main window opens.
"""
from pathlib import Path

from translation_assistant.db import Database, migrate_files_to_db


def run_startup_migration(*, profile_dir: Path, db: Database) -> None:
    """
    Import legacy Profile/ CSV and LEX files into the database.
    Safe to call on every startup — migrate_files_to_db is idempotent.
    No-op when profile_dir does not exist or contains no CSV files.
    """
    if not profile_dir.exists():
        return
    migrate_files_to_db(profile_dir, db)

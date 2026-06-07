"""
Tests for the one-time filesystem→SQLite migration (Stage C).
Covers migrate_files_to_db() edge cases and the startup wiring helper.
"""
import sqlite3
import csv
import pytest
from pathlib import Path

from translation_assistant.db import Database, migrate_files_to_db
from translation_assistant.migration import run_startup_migration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    return Database(":memory:", _conn=conn)


def _make_profile_dir(tmp_path: Path) -> Path:
    d = tmp_path / "Profile"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# migrate_files_to_db — edge cases
# ---------------------------------------------------------------------------

def test_migrate_multiple_profiles(tmp_path, mem_db):
    pd = _make_profile_dir(tmp_path)
    for name, rows in [("Default", [("A", "a")]), ("JP_Novel", [("B", "b")])]:
        with (pd / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)

    migrate_files_to_db(pd, mem_db)

    profiles = mem_db.list_profiles()
    assert "Default" in profiles
    assert "JP_Novel" in profiles
    assert mem_db.get_glossary("Default") == [("A", "a")]
    assert mem_db.get_glossary("JP_Novel") == [("B", "b")]


def test_migrate_empty_csv(tmp_path, mem_db):
    pd = _make_profile_dir(tmp_path)
    (pd / "Empty.csv").write_text("", encoding="utf-8")

    migrate_files_to_db(pd, mem_db)

    assert "Empty" in mem_db.list_profiles()
    assert mem_db.get_glossary("Empty") == []


def test_migrate_csv_comma_in_translation_preserved(tmp_path, mem_db):
    # core.load_glossary splits on first comma only — comma in translation is kept
    pd = _make_profile_dir(tmp_path)
    (pd / "Default.csv").write_text("A,a,extra_note\nB,b\n", encoding="utf-8")

    migrate_files_to_db(pd, mem_db)

    assert mem_db.get_glossary("Default") == [("A", "a,extra_note"), ("B", "b")]


def test_migrate_csv_phrase_without_comma_gets_empty_translation(tmp_path, mem_db):
    # core.load_glossary: no comma → translation="" (valid pending-translation row)
    pd = _make_profile_dir(tmp_path)
    (pd / "Default.csv").write_text("untranslated_phrase\nA,a\n", encoding="utf-8")

    migrate_files_to_db(pd, mem_db)

    glossary = mem_db.get_glossary("Default")
    assert ("A", "a") in glossary
    assert ("untranslated_phrase", "") in glossary


def test_migrate_lex_strips_blank_lines(tmp_path, mem_db):
    pd = _make_profile_dir(tmp_path)
    (pd / "Default.csv").write_text("", encoding="utf-8")
    (pd / "Default.lex").write_text("#LID 1033\nTanaka\n\nYamamoto\n\n", encoding="utf-8")

    migrate_files_to_db(pd, mem_db)

    words = mem_db.get_custom_words("Default")
    assert "Tanaka" in words
    assert "Yamamoto" in words
    assert "" not in words


def test_migrate_lex_skips_comment_lines(tmp_path, mem_db):
    pd = _make_profile_dir(tmp_path)
    (pd / "Default.csv").write_text("", encoding="utf-8")
    (pd / "Default.lex").write_text("# comment\nRealWord\n", encoding="utf-8")

    migrate_files_to_db(pd, mem_db)

    words = mem_db.get_custom_words("Default")
    assert "RealWord" in words
    assert "# comment" not in words


def test_migrate_default_profile_gets_is_default_flag(tmp_path, mem_db):
    pd = _make_profile_dir(tmp_path)
    (pd / "Default.csv").write_text("", encoding="utf-8")

    migrate_files_to_db(pd, mem_db)

    row = mem_db._conn.execute(
        "SELECT is_default FROM profiles WHERE name = 'Default'"
    ).fetchone()
    assert row[0] == 1


def test_migrate_non_default_profile_no_is_default_flag(tmp_path, mem_db):
    pd = _make_profile_dir(tmp_path)
    (pd / "Other.csv").write_text("", encoding="utf-8")

    migrate_files_to_db(pd, mem_db)

    row = mem_db._conn.execute(
        "SELECT is_default FROM profiles WHERE name = 'Other'"
    ).fetchone()
    assert row[0] == 0


def test_migrate_preserves_sort_order(tmp_path, mem_db):
    pd = _make_profile_dir(tmp_path)
    rows = [("Z", "z"), ("A", "a"), ("M", "m")]
    with (pd / "Default.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

    migrate_files_to_db(pd, mem_db)

    assert mem_db.get_glossary("Default") == rows


def test_migrate_no_csv_files_no_error(tmp_path, mem_db):
    pd = _make_profile_dir(tmp_path)
    migrate_files_to_db(pd, mem_db)  # must not raise
    assert mem_db.list_profiles() == []


def test_migrate_nonexistent_profile_dir_no_error(tmp_path, mem_db):
    pd = tmp_path / "NoSuchDir"
    migrate_files_to_db(pd, mem_db)  # must not raise
    assert mem_db.list_profiles() == []


# ---------------------------------------------------------------------------
# run_startup_migration — one-time wiring helper
# ---------------------------------------------------------------------------

def test_startup_migration_runs_when_profile_dir_has_csvs(tmp_path, mem_db, monkeypatch):
    pd = _make_profile_dir(tmp_path)
    (pd / "Default.csv").write_text("A,a\n", encoding="utf-8")

    run_startup_migration(profile_dir=pd, db=mem_db)

    assert "Default" in mem_db.list_profiles()


def test_startup_migration_idempotent_across_calls(tmp_path, mem_db):
    pd = _make_profile_dir(tmp_path)
    (pd / "Default.csv").write_text("A,a\n", encoding="utf-8")

    run_startup_migration(profile_dir=pd, db=mem_db)
    run_startup_migration(profile_dir=pd, db=mem_db)

    assert mem_db.list_profiles().count("Default") == 1


def test_startup_migration_no_op_when_dir_missing(tmp_path, mem_db):
    pd = tmp_path / "NoSuchDir"
    run_startup_migration(profile_dir=pd, db=mem_db)  # must not raise
    assert mem_db.list_profiles() == []

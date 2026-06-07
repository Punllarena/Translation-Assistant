"""
Tests for Database (db.py) — Stage A of the SQLite migration.
All tests use an in-memory connection via the _conn injection seam.
"""
import sqlite3
import pytest

from translation_assistant.db import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    return Database(":memory:", _conn=conn)


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

def _tables(db: Database) -> set[str]:
    rows = db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r[0] for r in rows}


def test_schema_tables_created(db):
    tables = _tables(db)
    assert "profiles" in tables
    assert "glossary" in tables
    assert "custom_words" in tables
    assert "documents" in tables
    assert "lines" in tables
    assert "schema_version" in tables


def test_schema_version_is_1(db):
    version = db._conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert version == 1


def test_foreign_keys_enabled(db):
    result = db._conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert result == 1


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------

def test_list_profiles_empty(db):
    assert db.list_profiles() == []


def test_create_profile_returns_id(db):
    pid = db.create_profile("Default")
    assert isinstance(pid, int)
    assert pid > 0


def test_create_profile_appears_in_list(db):
    db.create_profile("Default")
    assert "Default" in db.list_profiles()


def test_list_profiles_multiple(db):
    db.create_profile("Alpha")
    db.create_profile("Beta")
    profiles = db.list_profiles()
    assert "Alpha" in profiles
    assert "Beta" in profiles


def test_get_profile_id_existing(db):
    pid = db.create_profile("Default")
    assert db.get_profile_id("Default") == pid


def test_get_profile_id_missing(db):
    assert db.get_profile_id("NoSuch") is None


def test_rename_profile(db):
    db.create_profile("Old")
    db.rename_profile("Old", "New")
    assert "New" in db.list_profiles()
    assert "Old" not in db.list_profiles()


def test_delete_profile_removes_it(db):
    db.create_profile("Temp")
    db.delete_profile("Temp")
    assert "Temp" not in db.list_profiles()


def test_delete_default_profile_raises(db):
    db.create_profile("Default", is_default=True)
    with pytest.raises(ValueError, match="default"):
        db.delete_profile("Default")


def test_create_duplicate_profile_raises(db):
    db.create_profile("Alpha")
    with pytest.raises(Exception):
        db.create_profile("Alpha")


# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------

def test_get_glossary_empty(db):
    db.create_profile("Default")
    assert db.get_glossary("Default") == []


def test_set_and_get_glossary_round_trip(db):
    db.create_profile("Default")
    rows = [("彼女", "she"), ("彼", "he"), ("私", "I")]
    db.set_glossary("Default", rows)
    result = db.get_glossary("Default")
    assert result == rows


def test_set_glossary_replaces_all(db):
    db.create_profile("Default")
    db.set_glossary("Default", [("A", "a"), ("B", "b")])
    db.set_glossary("Default", [("C", "c")])
    assert db.get_glossary("Default") == [("C", "c")]


def test_add_phrase_appends(db):
    db.create_profile("Default")
    db.set_glossary("Default", [("A", "a")])
    db.add_phrase("Default", "B", "b")
    result = db.get_glossary("Default")
    assert ("B", "b") in result


def test_delete_phrase(db):
    db.create_profile("Default")
    db.set_glossary("Default", [("A", "a"), ("B", "b")])
    db.delete_phrase("Default", "A")
    result = db.get_glossary("Default")
    assert ("A", "a") not in result
    assert ("B", "b") in result


def test_glossary_isolated_per_profile(db):
    db.create_profile("P1")
    db.create_profile("P2")
    db.set_glossary("P1", [("X", "x")])
    db.set_glossary("P2", [("Y", "y")])
    assert db.get_glossary("P1") == [("X", "x")]
    assert db.get_glossary("P2") == [("Y", "y")]


# ---------------------------------------------------------------------------
# Custom words
# ---------------------------------------------------------------------------

def test_get_custom_words_empty(db):
    db.create_profile("Default")
    assert db.get_custom_words("Default") == []


def test_add_word(db):
    db.create_profile("Default")
    db.add_word("Default", "Tanaka")
    assert "Tanaka" in db.get_custom_words("Default")


def test_add_word_idempotent(db):
    db.create_profile("Default")
    db.add_word("Default", "Tanaka")
    db.add_word("Default", "Tanaka")
    words = db.get_custom_words("Default")
    assert words.count("Tanaka") == 1


def test_custom_words_isolated_per_profile(db):
    db.create_profile("P1")
    db.create_profile("P2")
    db.add_word("P1", "Foo")
    assert "Foo" not in db.get_custom_words("P2")


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def test_list_documents_empty(db):
    assert db.list_documents() == []


def test_create_document_returns_id(db):
    doc_id = db.create_document("My Story")
    assert isinstance(doc_id, int)
    assert doc_id > 0


def test_create_document_appears_in_list(db):
    db.create_document("My Story")
    docs = db.list_documents()
    assert len(docs) == 1
    assert docs[0]["title"] == "My Story"


def test_list_documents_has_required_keys(db):
    db.create_document("Story")
    doc = db.list_documents()[0]
    assert "id" in doc
    assert "title" in doc
    assert "updated_at" in doc
    assert "last_position" in doc


def test_get_document(db):
    doc_id = db.create_document("Novel")
    doc = db.get_document(doc_id)
    assert doc["title"] == "Novel"
    assert doc["last_position"] == 0


def test_delete_document(db):
    doc_id = db.create_document("Draft")
    db.delete_document(doc_id)
    assert db.list_documents() == []


def test_delete_document_cascades_to_lines(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Hello", "translated_text": ""}
    ])
    db.delete_document(doc_id)
    # Lines table should be empty
    rows = db._conn.execute("SELECT * FROM lines").fetchall()
    assert rows == []


def test_set_last_position(db):
    doc_id = db.create_document("Story")
    db.set_last_position(doc_id, 42)
    doc = db.get_document(doc_id)
    assert doc["last_position"] == 42


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------

def test_get_lines_empty(db):
    doc_id = db.create_document("Story")
    assert db.get_lines(doc_id) == []


def test_save_and_get_lines_round_trip(db):
    doc_id = db.create_document("Story")
    lines = [
        {"line_number": 0, "prefix": "%", "raw_text": "Line one", "translated_text": ""},
        {"line_number": 1, "prefix": "$", "raw_text": "Line two", "translated_text": "Two"},
    ]
    db.save_lines(doc_id, lines)
    result = db.get_lines(doc_id)
    assert len(result) == 2
    assert result[0]["line_number"] == 0
    assert result[0]["prefix"] == "%"
    assert result[0]["raw_text"] == "Line one"
    assert result[0]["translated_text"] == ""
    assert result[1]["line_number"] == 1
    assert result[1]["prefix"] == "$"
    assert result[1]["raw_text"] == "Line two"
    assert result[1]["translated_text"] == "Two"


def test_save_lines_replaces_all(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Old", "translated_text": ""},
    ])
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "New", "translated_text": ""},
    ])
    result = db.get_lines(doc_id)
    assert len(result) == 1
    assert result[0]["raw_text"] == "New"


def test_save_lines_updates_document_updated_at(db):
    doc_id = db.create_document("Story")
    before = db.get_document(doc_id)["updated_at"]
    import time; time.sleep(1.1)
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "x", "translated_text": ""},
    ])
    after = db.get_document(doc_id)["updated_at"]
    assert after >= before


def test_save_translation_updates_one_cell(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "B", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "Translated A")
    result = db.get_lines(doc_id)
    assert result[0]["translated_text"] == "Translated A"
    assert result[1]["translated_text"] == ""


def test_get_lines_ordered_by_line_number(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 2, "prefix": "%", "raw_text": "Third", "translated_text": ""},
        {"line_number": 0, "prefix": "%", "raw_text": "First", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "Second", "translated_text": ""},
    ])
    result = db.get_lines(doc_id)
    assert [r["line_number"] for r in result] == [0, 1, 2]


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------

def test_close_does_not_raise(db):
    db.close()  # should not throw


# ---------------------------------------------------------------------------
# Migration helper (tested with real tmp files)
# ---------------------------------------------------------------------------

def test_migrate_imports_csv_and_lex(tmp_path):
    import sqlite3, csv
    from translation_assistant.db import Database, migrate_files_to_db

    profile_dir = tmp_path / "Profile"
    profile_dir.mkdir()

    csv_path = profile_dir / "Default.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["彼女", "she"])
        writer.writerow(["彼", "he"])

    lex_path = profile_dir / "Default.lex"
    lex_path.write_text("#LID 1033\nTanaka\nYamamoto\n", encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    database = Database(":memory:", _conn=conn)
    migrate_files_to_db(profile_dir, database)

    assert "Default" in database.list_profiles()
    glossary = database.get_glossary("Default")
    assert ("彼女", "she") in glossary
    assert ("彼", "he") in glossary
    words = database.get_custom_words("Default")
    assert "Tanaka" in words
    assert "Yamamoto" in words


def test_migrate_idempotent(tmp_path):
    import sqlite3, csv
    from translation_assistant.db import Database, migrate_files_to_db

    profile_dir = tmp_path / "Profile"
    profile_dir.mkdir()
    (profile_dir / "Default.csv").write_text("A,a\n", encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    database = Database(":memory:", _conn=conn)
    migrate_files_to_db(profile_dir, database)
    migrate_files_to_db(profile_dir, database)  # second call must not fail/duplicate

    assert database.list_profiles().count("Default") == 1


def test_migrate_skips_lex_if_absent(tmp_path):
    import sqlite3
    from translation_assistant.db import Database, migrate_files_to_db

    profile_dir = tmp_path / "Profile"
    profile_dir.mkdir()
    (profile_dir / "Default.csv").write_text("", encoding="utf-8")
    # no lex file

    conn = sqlite3.connect(":memory:")
    database = Database(":memory:", _conn=conn)
    migrate_files_to_db(profile_dir, database)  # must not raise
    assert "Default" in database.list_profiles()

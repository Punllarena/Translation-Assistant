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


# ---------------------------------------------------------------------------
# Stage H — document metadata (series_title, series_order, chapter_title)
# ---------------------------------------------------------------------------

def _doc_columns(db: Database) -> set[str]:
    rows = db._conn.execute("PRAGMA table_info(documents)").fetchall()
    return {r[1] for r in rows}


def test_series_columns_exist(db):
    cols = _doc_columns(db)
    assert "series_title" in cols
    assert "series_order" in cols
    assert "chapter_title" in cols


def test_create_document_with_metadata(db):
    doc_id = db.create_document(
        "Ch1", series_title="My Novel", series_order=1, chapter_title="The Beginning"
    )
    doc = db.get_document(doc_id)
    assert doc["series_title"] == "My Novel"
    assert doc["series_order"] == 1
    assert doc["chapter_title"] == "The Beginning"


def test_create_document_metadata_defaults_to_empty(db):
    doc_id = db.create_document("Untitled")
    doc = db.get_document(doc_id)
    assert doc["series_title"] == ""
    assert doc["series_order"] == 0
    assert doc["chapter_title"] == ""


# ---------------------------------------------------------------------------
# source_url column and replace_raw_content
# ---------------------------------------------------------------------------

def test_source_url_column_exists(db):
    cols = _doc_columns(db)
    assert "source_url" in cols


def test_create_document_stores_source_url(db):
    doc_id = db.create_document("Story", source_url="https://ncode.syosetu.com/n1234ab/1/")
    doc = db.get_document(doc_id)
    assert doc["source_url"] == "https://ncode.syosetu.com/n1234ab/1/"


def test_create_document_source_url_defaults_empty(db):
    doc_id = db.create_document("Story")
    doc = db.get_document(doc_id)
    assert doc["source_url"] == ""


def test_list_documents_includes_source_url(db):
    db.create_document("Story", source_url="https://ncode.syosetu.com/n1234ab/1/")
    docs = db.list_documents()
    assert "source_url" in docs[0]
    assert docs[0]["source_url"] == "https://ncode.syosetu.com/n1234ab/1/"


def test_replace_raw_content_replaces_lines(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Old A", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "Old B", "translated_text": ""},
    ])
    db.replace_raw_content(doc_id, ["%New A", "%New B"])
    lines = db.get_lines(doc_id)
    assert lines[0]["raw_text"] == "New A"
    assert lines[1]["raw_text"] == "New B"


def test_replace_raw_content_preserves_translations_by_index(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Old A", "translated_text": "Trans A"},
        {"line_number": 1, "prefix": "%", "raw_text": "Old B", "translated_text": "Trans B"},
    ])
    db.replace_raw_content(doc_id, ["%New A", "%New B"])
    lines = db.get_lines(doc_id)
    assert lines[0]["translated_text"] == "Trans A"
    assert lines[1]["translated_text"] == "Trans B"


def test_replace_raw_content_extra_new_lines_get_empty_translation(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Old", "translated_text": "Trans"},
    ])
    db.replace_raw_content(doc_id, ["%Old", "%Brand New Line"])
    lines = db.get_lines(doc_id)
    assert lines[0]["translated_text"] == "Trans"
    assert lines[1]["translated_text"] == ""


def test_replace_raw_content_fewer_new_lines_drops_excess_translations(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Trans A"},
        {"line_number": 1, "prefix": "%", "raw_text": "B", "translated_text": "Trans B"},
    ])
    db.replace_raw_content(doc_id, ["%A"])
    lines = db.get_lines(doc_id)
    assert len(lines) == 1
    assert lines[0]["translated_text"] == "Trans A"


def test_replace_raw_content_handles_prefix_variants(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Old", "translated_text": "T"},
    ])
    db.replace_raw_content(doc_id, ["$Continuation line"])
    lines = db.get_lines(doc_id)
    assert lines[0]["prefix"] == "$"
    assert lines[0]["raw_text"] == "Continuation line"


def test_update_document_metadata(db):
    doc_id = db.create_document("Old")
    db.update_document_metadata(
        doc_id, series_title="Series A", series_order=3, chapter_title="New Chapter"
    )
    doc = db.get_document(doc_id)
    assert doc["series_title"] == "Series A"
    assert doc["series_order"] == 3
    assert doc["chapter_title"] == "New Chapter"


def test_get_series_list_returns_distinct_sorted(db):
    db.create_document("a", series_title="Zebra")
    db.create_document("b", series_title="Alpha")
    db.create_document("c", series_title="Zebra")  # duplicate
    db.create_document("d", series_title="")        # empty — excluded
    assert db.get_series_list() == ["Alpha", "Zebra"]


def test_list_documents_includes_progress(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Translated"},
        {"line_number": 1, "prefix": "%", "raw_text": "B", "translated_text": ""},
    ])
    docs = db.list_documents()
    assert "progress" in docs[0]
    assert docs[0]["progress"] == 50


def test_list_documents_progress_zero_for_empty_doc(db):
    db.create_document("Empty")
    docs = db.list_documents()
    assert docs[0]["progress"] == 0


def test_list_documents_progress_ignores_blank_lines(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Translated"},
        {"line_number": 1, "prefix": "",  "raw_text": "",  "translated_text": ""},  # blank
        {"line_number": 2, "prefix": "%", "raw_text": "B", "translated_text": "Translated"},
    ])
    docs = db.list_documents()
    assert docs[0]["progress"] == 100


def test_list_documents_includes_metadata_fields(db):
    db.create_document("Ch1", series_title="S", series_order=2, chapter_title="C")
    doc = db.list_documents()[0]
    assert doc["series_title"] == "S"
    assert doc["series_order"] == 2
    assert doc["chapter_title"] == "C"


def test_migration_adds_columns_to_existing_db(tmp_path):
    """A DB created without the new columns gets them added by _apply_schema."""
    import sqlite3 as _sqlite3
    db_path = tmp_path / "old.db"
    # Create a minimal DB missing the new columns
    old_conn = _sqlite3.connect(str(db_path))
    old_conn.execute(
        "CREATE TABLE documents "
        "(id INTEGER PRIMARY KEY, title TEXT NOT NULL, "
        "source_language TEXT NOT NULL DEFAULT 'ja', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "updated_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "last_position INTEGER NOT NULL DEFAULT 0)"
    )
    old_conn.execute("INSERT INTO documents (title) VALUES ('old')")
    old_conn.commit()
    old_conn.close()

    # Re-open with Database — should add the new columns without error
    db2 = Database(db_path)
    cols = _doc_columns(db2)
    assert "series_title" in cols
    assert "series_order" in cols
    assert "chapter_title" in cols
    # Existing row survived
    docs = db2.list_documents()
    assert len(docs) == 1
    assert docs[0]["title"] == "old"
    assert docs[0]["series_title"] == ""
    db2.close()


# ---------------------------------------------------------------------------
# Series-profile linking
# ---------------------------------------------------------------------------

def test_series_profiles_table_exists(db):
    assert "series_profiles" in _tables(db)

def test_get_series_profile_returns_empty_for_unknown(db):
    assert db.get_series_profile("Unknown Series") == ""

def test_set_series_profile_stores_link(db):
    db.create_profile("JP")
    db.set_series_profile("My Novel", "JP")
    assert db.get_series_profile("My Novel") == "JP"

def test_set_series_profile_upserts(db):
    db.create_profile("JP")
    db.create_profile("CN")
    db.set_series_profile("My Novel", "JP")
    db.set_series_profile("My Novel", "CN")
    assert db.get_series_profile("My Novel") == "CN"

def test_set_series_profile_empty_string_clears_link(db):
    db.create_profile("JP")
    db.set_series_profile("My Novel", "JP")
    db.set_series_profile("My Novel", "")
    assert db.get_series_profile("My Novel") == ""

def test_get_next_series_order_returns_1_for_new_series(db):
    assert db.get_next_series_order("Brand New") == 1

def test_get_next_series_order_returns_max_plus_one(db):
    db.create_document("C1", series_title="Novel", series_order=3)
    db.create_document("C2", series_title="Novel", series_order=7)
    assert db.get_next_series_order("Novel") == 8

def test_get_next_series_order_ignores_other_series(db):
    db.create_document("C1", series_title="Novel A", series_order=5)
    assert db.get_next_series_order("Novel B") == 1


# ---------------------------------------------------------------------------
# Series URL
# ---------------------------------------------------------------------------

def test_get_series_url_missing(db):
    assert db.get_series_url("NoSeries") == ""


def test_set_and_get_series_url(db):
    db.set_series_url("My Series", "https://ncode.syosetu.com/n1234ab/")
    assert db.get_series_url("My Series") == "https://ncode.syosetu.com/n1234ab/"


def test_set_series_url_overwrites(db):
    db.set_series_url("My Series", "https://ncode.syosetu.com/n1234ab/")
    db.set_series_url("My Series", "https://ncode.syosetu.com/n9999zz/")
    assert db.get_series_url("My Series") == "https://ncode.syosetu.com/n9999zz/"


def test_set_series_url_empty_clears(db):
    db.set_series_url("My Series", "https://ncode.syosetu.com/n1234ab/")
    db.set_series_url("My Series", "")
    assert db.get_series_url("My Series") == ""


# ---------------------------------------------------------------------------
# Series chapters (existing series_order values)
# ---------------------------------------------------------------------------

def test_get_series_chapters_empty(db):
    assert db.get_series_chapters("Nonexistent") == []


def test_get_series_chapters_returns_orders(db):
    db.create_document("Doc A", series_title="S", series_order=1, chapter_title="")
    db.create_document("Doc B", series_title="S", series_order=2, chapter_title="")
    db.create_document("Doc C", series_title="S", series_order=5, chapter_title="")
    assert db.get_series_chapters("S") == [1, 2, 5]


# ---------------------------------------------------------------------------
# get_series_list_full
# ---------------------------------------------------------------------------

def test_get_series_list_full_empty(db):
    assert db.get_series_list_full() == []


def test_get_series_list_full_basic(db):
    db.create_document("D1", series_title="Alpha", series_order=1, chapter_title="")
    db.create_document("D2", series_title="Alpha", series_order=2, chapter_title="")
    db.create_document("D3", series_title="Beta",  series_order=1, chapter_title="")
    db.set_series_url("Alpha", "https://ncode.syosetu.com/n0001aa/")
    result = db.get_series_list_full()
    titles = [r["title"] for r in result]
    assert titles == ["Alpha", "Beta"]
    alpha = next(r for r in result if r["title"] == "Alpha")
    assert alpha["url"] == "https://ncode.syosetu.com/n0001aa/"
    assert alpha["chapter_count"] == 2
    beta = next(r for r in result if r["title"] == "Beta")
    assert beta["url"] == ""
    assert beta["chapter_count"] == 1


def test_get_series_list_full_excludes_no_series(db):
    db.create_document("Standalone", series_title="", series_order=0, chapter_title="")
    assert db.get_series_list_full() == []


def test_get_series_list_full_includes_profile_only_series(db):
    """Series registered via set_series_url (no documents) must appear."""
    db.set_series_url("Ghost Series", "https://ncode.syosetu.com/n0001aa/")
    result = db.get_series_list_full()
    assert len(result) == 1
    assert result[0]["title"] == "Ghost Series"
    assert result[0]["url"] == "https://ncode.syosetu.com/n0001aa/"
    assert result[0]["chapter_count"] == 0


def test_get_series_list_full_mixed_document_and_profile_only(db):
    """Series with documents and profile-only series both appear, sorted."""
    db.create_document("D1", series_title="Beta", series_order=1, chapter_title="")
    db.set_series_url("Alpha", "https://ncode.syosetu.com/n0001aa/")
    result = db.get_series_list_full()
    titles = [r["title"] for r in result]
    assert titles == ["Alpha", "Beta"]
    alpha = next(r for r in result if r["title"] == "Alpha")
    assert alpha["chapter_count"] == 0
    beta = next(r for r in result if r["title"] == "Beta")
    assert beta["chapter_count"] == 1


def test_get_series_list_includes_profile_only_series(db):
    """get_series_list() must include series from series_profiles with no documents."""
    db.set_series_url("Ghost Series", "")
    result = db.get_series_list()
    assert "Ghost Series" in result


def test_get_series_list_no_duplicates_when_both_exist(db):
    """Series appearing in both documents and series_profiles shows once."""
    db.create_document("D1", series_title="Alpha", series_order=1, chapter_title="")
    db.set_series_url("Alpha", "https://ncode.syosetu.com/n0001aa/")
    result = db.get_series_list()
    assert result.count("Alpha") == 1


# ---------------------------------------------------------------------------
# Translation Memory
# ---------------------------------------------------------------------------

def _make_doc_with_line(db: Database, title: str, raw: str, translation: str) -> int:
    doc_id = db.create_document(title)
    db.save_lines(doc_id, [{"line_number": 0, "prefix": "%", "raw_text": raw, "translated_text": translation}])
    return doc_id


def test_find_tm_matches_exact(db):
    _make_doc_with_line(db, "Doc A", "猫が鳴いた", "The cat meowed")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=None)
    assert len(matches) == 1
    assert matches[0]["translated_text"] == "The cat meowed"
    assert matches[0]["doc_title"] == "Doc A"


def test_find_tm_matches_excludes_current_doc(db):
    doc_id = _make_doc_with_line(db, "Current", "猫が鳴いた", "The cat meowed")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=doc_id)
    assert matches == []


def test_find_tm_matches_excludes_empty_translation(db):
    _make_doc_with_line(db, "Doc A", "猫が鳴いた", "")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=None)
    assert matches == []


def test_find_tm_matches_no_match(db):
    _make_doc_with_line(db, "Doc A", "犬が吠えた", "The dog barked")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=None)
    assert matches == []


def test_find_tm_matches_limit(db):
    for i in range(7):
        _make_doc_with_line(db, f"Doc {i}", "猫が鳴いた", f"Translation {i}")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=None, limit=5)
    assert len(matches) == 5


def test_find_tm_matches_returns_doc_title_and_updated_at(db):
    _make_doc_with_line(db, "My Novel Ch1", "猫が鳴いた", "The cat meowed")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=None)
    assert "doc_title" in matches[0]
    assert "updated_at" in matches[0]


# ---------------------------------------------------------------------------
# get_document_ids_by_series
# ---------------------------------------------------------------------------

def test_get_document_ids_by_series_returns_matching_ids(db):
    db.create_profile("Default", is_default=True)
    id1 = db.create_document("Ch1", series_title="Isekai")
    id2 = db.create_document("Ch2", series_title="Isekai")
    _other = db.create_document("Other", series_title="Romance")
    result = db.get_document_ids_by_series("Isekai")
    assert set(result) == {id1, id2}


def test_get_document_ids_by_series_empty_when_no_match(db):
    db.create_profile("Default", is_default=True)
    db.create_document("Ch1", series_title="Isekai")
    result = db.get_document_ids_by_series("Nonexistent")
    assert result == []


# ---------------------------------------------------------------------------
# Usage statistics
# ---------------------------------------------------------------------------

def test_stats_empty(db):
    stats = db.get_today_stats()
    assert stats == {"paragraphs": 0, "chars": 0}


def test_stats_accumulate(db):
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "こんにちは", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "さようなら", "translated_text": ""},
        {"line_number": 2, "prefix": "%", "raw_text": "ありがとう", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "Hello")
    db.save_translation(doc_id, 1, "Goodbye")
    db.save_translation(doc_id, 2, "Thank you")
    stats = db.get_today_stats()
    assert stats["paragraphs"] == 3
    assert stats["chars"] == 15  # 5 chars each


def test_stats_cleared(db):
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "こんにちは", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "さようなら", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "Hello")
    db.save_translation(doc_id, 1, "Goodbye")
    db.save_translation(doc_id, 1, "")  # clear
    stats = db.get_today_stats()
    assert stats["paragraphs"] == 1
    assert stats["chars"] == 5  # only "こんにちは"


def test_daily_stats_multi_day(db):
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "い", "translated_text": ""},
        {"line_number": 2, "prefix": "%", "raw_text": "う", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "a")
    db._conn.execute(
        "UPDATE lines SET translated_at = '2026-06-01 10:00:00' "
        "WHERE document_id = ? AND line_number = 0",
        (doc_id,),
    )
    db.save_translation(doc_id, 1, "i")
    db._conn.execute(
        "UPDATE lines SET translated_at = '2026-06-01 11:00:00' "
        "WHERE document_id = ? AND line_number = 1",
        (doc_id,),
    )
    db.save_translation(doc_id, 2, "u")
    db._conn.execute(
        "UPDATE lines SET translated_at = '2026-06-02 10:00:00' "
        "WHERE document_id = ? AND line_number = 2",
        (doc_id,),
    )
    db._conn.commit()
    rows = db.get_daily_stats(days=365)
    by_date = {r["date"]: r for r in rows}
    assert by_date["2026-06-01"]["paragraphs"] == 2
    assert by_date["2026-06-01"]["chars"] == 2   # "あ" + "い"
    assert by_date["2026-06-02"]["paragraphs"] == 1
    assert by_date["2026-06-02"]["chars"] == 1   # "う"


def test_save_lines_preserves_translated_at(db):
    """Ctrl+S / autosave must not wipe translated_at timestamps."""
    doc_id = db.create_document("Test")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "あ", "translated_text": ""},
    ])
    db.save_translation(doc_id, 0, "a")
    # simulate autosave: re-save all lines
    current_lines = db.get_lines(doc_id)
    db.save_lines(doc_id, current_lines)
    stats = db.get_today_stats()
    assert stats["paragraphs"] == 1  # timestamp must survive the bulk-save

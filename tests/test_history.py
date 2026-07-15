"""
Tests for ta.core.history.HistoryStore (SQLite-backed).
"""
import json
import sqlite3

from ta.core.history import HistoryStore


def make_store(tmp_path, **kw):
    return HistoryStore(path=tmp_path / "history.db", **kw)


def test_append_and_get(tmp_path):
    store = make_store(tmp_path)
    eid = store.append("こんにちは", {"google": "hello"}, "Japanese", "English")
    e = store.get(eid)
    assert e.source == "こんにちは"
    assert e.translations == {"google": "hello"}
    assert e.src_lang == "Japanese"
    assert e.dst_lang == "English"


def test_append_upserts_same_source_and_langs(tmp_path):
    store = make_store(tmp_path)
    id1 = store.append("line", {"google": "g"}, "Japanese", "English")
    id2 = store.append("line", {"ollama": "o"}, "Japanese", "English", "trace")
    assert id1 == id2
    assert len(store.all_entries()) == 1
    e = store.get(id1)
    assert e.translations == {"google": "g", "ollama": "o"}
    assert e.thinking == "trace"


def test_upsert_keeps_thinking_when_new_is_empty(tmp_path):
    store = make_store(tmp_path)
    store.append("line", {"ollama": "o"}, "Japanese", "English", "trace")
    store.append("line", {"google": "g"}, "Japanese", "English")
    assert store.find("line", "Japanese", "English") == ("o", "trace")


def test_different_langs_are_separate_entries(tmp_path):
    store = make_store(tmp_path)
    store.append("line", {"ollama": "en"}, "Japanese", "English")
    store.append("line", {"ollama": "de"}, "Japanese", "German")
    assert len(store.all_entries()) == 2
    assert store.find("line", "Japanese", "German") == ("de", "")


def test_find_missing_returns_none(tmp_path):
    store = make_store(tmp_path)
    store.append("line", {"google": "g"}, "Japanese", "English")  # no ollama key
    assert store.find("line", "Japanese", "English") is None
    assert store.find("other", "Japanese", "English") is None


def test_find_falls_back_to_legacy_empty_langs(tmp_path):
    store = make_store(tmp_path)
    store.append("old line", {"ollama": "old"})  # imported pre-migration shape
    assert store.find("old line", "Japanese", "English") == ("old", "")


def test_navigate_matches_old_semantics(tmp_path):
    store = make_store(tmp_path)
    ids = [store.append(f"s{i}", {}) for i in range(3)]
    assert store.navigate(None, -1).id == ids[-1]
    assert store.navigate(None, +1).id == ids[0]
    assert store.navigate(ids[1], -1).id == ids[0]
    assert store.navigate(ids[1], +1).id == ids[2]
    assert store.navigate(ids[0], -1) is None
    assert store.navigate(999, -1).id == ids[-1]  # unknown id -> newest
    assert make_store(tmp_path / "empty").navigate(None, -1) is None


def test_clear_empties_and_reports_freed(tmp_path):
    store = make_store(tmp_path)
    for i in range(50):
        store.append(f"source {i}", {"ollama": "x" * 1000})
    assert store.size_bytes() > 0
    freed = store.clear()
    assert freed >= 0
    assert store.all_entries() == []
    assert store.find("source 1", "", "") is None


def test_trim_deletes_oldest_when_over_cap(tmp_path):
    store = make_store(tmp_path, max_bytes=20_000)
    for i in range(100):
        store.append(f"source {i}", {"ollama": "x" * 500})
    sources = [e.source for e in store.all_entries()]
    assert len(sources) < 100          # trimmed
    assert "source 99" in sources      # newest survives
    assert "source 0" not in sources   # oldest went first
    assert store.size_bytes() <= 20_000 * 2  # VACUUM keeps file near cap


def test_migrates_legacy_jsonl(tmp_path):
    legacy = tmp_path / "history.jsonl"
    lines = [
        {"id": 1, "timestamp": "2026-07-03T00:00:00", "source": "a",
         "translations": {"ollama": "A1"}},
        {"id": 2, "timestamp": "2026-07-03T00:00:01", "source": "a",
         "translations": {"ollama": "A2", "google": "GA"}},  # dup source merges
        {"id": 3, "timestamp": "2026-07-03T00:00:02", "source": "b",
         "translations": {"google": "GB"}},
    ]
    legacy.write_text("\n".join(json.dumps(d) for d in lines) + "\n")
    store = make_store(tmp_path)
    assert [e.source for e in store.all_entries()] == ["a", "b"]
    assert store.find("a", "Japanese", "English") == ("A2", "")  # legacy fallback
    assert not legacy.exists()
    assert (tmp_path / "history.jsonl.bak").exists()
    # Second startup: .bak is not re-imported
    store2 = make_store(tmp_path)
    assert len(store2.all_entries()) == 2


def test_migration_skips_bad_lines(tmp_path):
    legacy = tmp_path / "history.jsonl"
    legacy.write_bytes(
        b'{"id": 1, "timestamp": "t", "source": "ok", "translations": {}}\n'
        b'{"id": 2, "source": "torn write \xe3\x81'  # truncated multibyte
    )
    store = make_store(tmp_path)
    assert [e.source for e in store.all_entries()] == ["ok"]


def test_corrupt_db_renamed_and_fresh_start(tmp_path):
    p = tmp_path / "history.db"
    p.write_bytes(b"this is not a sqlite database at all" * 100)
    store = HistoryStore(path=p)
    assert store.all_entries() == []
    store.append("works", {})
    assert (tmp_path / "history.db.corrupt").exists()


def test_conn_injection_seam():
    conn = sqlite3.connect(":memory:")
    store = HistoryStore(":memory:", _conn=conn)
    store.append("x", {"ollama": "y"})
    assert store.find("x", "", "") == ("y", "")
    assert store.size_bytes() == 0  # no file

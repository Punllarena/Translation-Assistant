"""
Tests for ta.core.history.HistoryStore.
"""
from ta.core.history import HistoryStore


def test_load_survives_invalid_utf8(tmp_path):
    p = tmp_path / "history.jsonl"
    p.write_bytes(
        b'{"id": 1, "timestamp": "2026-07-03T00:00:00", "source": "ok", "translations": {}}\n'
        b'{"id": 2, "source": "torn write \xe3\x81'  # truncated multibyte, no newline
    )
    store = HistoryStore(path=p)
    assert [e.id for e in store.all_entries()] == [1]

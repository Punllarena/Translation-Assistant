from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "ta-python"
DEFAULT_DB_PATH = _DATA_DIR / "history.db"
DEFAULT_MAX_BYTES = 20 * 1024 * 1024  # 20 MB

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id           INTEGER PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    source       TEXT NOT NULL,
    src_lang     TEXT NOT NULL DEFAULT '',
    dst_lang     TEXT NOT NULL DEFAULT '',
    translations TEXT NOT NULL DEFAULT '{}',
    thinking     TEXT NOT NULL DEFAULT '',
    UNIQUE(source, src_lang, dst_lang)
)
"""

_COLS = "id, timestamp, source, src_lang, dst_lang, translations, thinking"


@dataclass
class HistoryEntry:
    id: int
    timestamp: str
    source: str
    translations: dict[str, str]
    src_lang: str = ""
    dst_lang: str = ""
    thinking: str = ""


class HistoryStore:
    """Translation history + Ollama MT cache in one SQLite file.

    History is a cache: any storage-level failure at startup falls back to a
    fresh store rather than blocking the app.
    """

    def __init__(self, path: Path | str = DEFAULT_DB_PATH,
                 max_bytes: int = DEFAULT_MAX_BYTES, *,
                 legacy_jsonl: Path | None = None,
                 _conn: sqlite3.Connection | None = None):
        self._path = Path(path)
        self._max_bytes = max_bytes
        if _conn is not None:
            self._conn = _conn
            self._conn.execute(_SCHEMA)
            self._conn.commit()
        else:
            self._conn = self._open()
        legacy = Path(legacy_jsonl) if legacy_jsonl else self._path.with_suffix(".jsonl")
        self._migrate_jsonl(legacy)
        self._trim_if_needed()

    def _open(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path))
        try:
            conn.execute(_SCHEMA)
            conn.commit()
        except sqlite3.DatabaseError:
            conn.close()
            self._path.rename(self._path.with_name(self._path.name + ".corrupt"))
            conn = sqlite3.connect(str(self._path))
            conn.execute(_SCHEMA)
            conn.commit()
        return conn

    # ------------------------------------------------------------------
    # Legacy JSONL import (one-time)
    # ------------------------------------------------------------------

    def _migrate_jsonl(self, legacy: Path) -> None:
        if legacy == self._path or not legacy.exists():
            return
        if self._conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]:
            return
        # errors="replace": a torn write must not crash startup; the mangled
        # line just fails json.loads below and is skipped
        with open(legacy, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    self._upsert(d["source"], d.get("translations", {}),
                                 "", "", "", d.get("timestamp", ""))
                except Exception:
                    continue
        self._conn.commit()
        legacy.rename(legacy.with_name(legacy.name + ".bak"))

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def _upsert(self, source: str, translations: dict[str, str],
                src_lang: str, dst_lang: str, thinking: str,
                timestamp: str) -> int:
        row = self._conn.execute(
            "SELECT id, translations, thinking FROM entries "
            "WHERE source = ? AND src_lang = ? AND dst_lang = ?",
            (source, src_lang, dst_lang)).fetchone()
        if row:
            merged = json.loads(row[1])
            merged.update(translations)
            self._conn.execute(
                "UPDATE entries SET timestamp = ?, translations = ?, thinking = ? "
                "WHERE id = ?",
                (timestamp, json.dumps(merged, ensure_ascii=False),
                 thinking or row[2], row[0]))
            return row[0]
        cur = self._conn.execute(
            "INSERT INTO entries (timestamp, source, src_lang, dst_lang, "
            "translations, thinking) VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, source, src_lang, dst_lang,
             json.dumps(translations, ensure_ascii=False), thinking))
        return cur.lastrowid

    def append(self, source: str, translations: dict[str, str],
               src_lang: str = "", dst_lang: str = "",
               thinking: str = "") -> int:
        entry_id = self._upsert(source, translations, src_lang, dst_lang,
                                thinking, time.strftime("%Y-%m-%dT%H:%M:%S"))
        self._conn.commit()
        self._trim_if_needed()
        return entry_id

    def clear(self) -> int:
        """Delete everything. Returns bytes freed on disk."""
        before = self.size_bytes()
        self._conn.execute("DELETE FROM entries")
        self._conn.commit()
        self._conn.execute("VACUUM")
        return max(0, before - self.size_bytes())

    def _trim_if_needed(self) -> None:
        if not self._path.exists() or self._path.stat().st_size <= self._max_bytes:
            return
        # Remove oldest 10% of entries
        n = self._conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        cut = max(1, n // 10)
        self._conn.execute(
            "DELETE FROM entries WHERE id IN "
            "(SELECT id FROM entries ORDER BY id LIMIT ?)", (cut,))
        self._conn.commit()
        self._conn.execute("VACUUM")

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def find(self, source: str, src_lang: str, dst_lang: str) -> tuple[str, str] | None:
        """MT-cache lookup: (ollama translation, thinking trace) or None.

        Falls back to legacy rows with empty languages (pre-migration import
        didn't know the pair)."""
        for sl, dl in ((src_lang, dst_lang), ("", "")):
            row = self._conn.execute(
                "SELECT translations, thinking FROM entries "
                "WHERE source = ? AND src_lang = ? AND dst_lang = ?",
                (source, sl, dl)).fetchone()
            if row:
                text = json.loads(row[0]).get("ollama")
                if text:
                    return (text, row[1])
        return None

    def get(self, entry_id: int) -> HistoryEntry | None:
        row = self._conn.execute(
            f"SELECT {_COLS} FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return self._entry(row) if row else None

    def navigate(self, current_id: int | None, direction: int) -> HistoryEntry | None:
        """direction: -1 = back (older), +1 = forward (newer)."""
        # ponytail: loads the full id list per call; fine below ~100k rows,
        # switch to WHERE id </> queries if it ever shows up in a profile
        ids = [r[0] for r in self._conn.execute("SELECT id FROM entries ORDER BY id")]
        if not ids:
            return None
        if current_id is None:
            return self.get(ids[-1] if direction < 0 else ids[0])
        try:
            idx = ids.index(current_id)
        except ValueError:
            return self.get(ids[-1])
        new_idx = idx + direction
        if 0 <= new_idx < len(ids):
            return self.get(ids[new_idx])
        return None

    def all_entries(self) -> list[HistoryEntry]:
        rows = self._conn.execute(f"SELECT {_COLS} FROM entries ORDER BY id")
        return [self._entry(r) for r in rows]

    def size_bytes(self) -> int:
        try:
            return self._path.stat().st_size
        except OSError:
            return 0

    @staticmethod
    def _entry(row) -> HistoryEntry:
        return HistoryEntry(id=row[0], timestamp=row[1], source=row[2],
                            src_lang=row[3], dst_lang=row[4],
                            translations=json.loads(row[5]), thinking=row[6])

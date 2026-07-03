from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

_DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "ta-python"
DEFAULT_HISTORY_PATH = _DATA_DIR / "history.jsonl"
DEFAULT_MAX_BYTES = 20 * 1024 * 1024  # 20 MB


@dataclass
class HistoryEntry:
    id: int
    timestamp: str
    source: str
    translations: dict[str, str]


class HistoryStore:
    def __init__(self, path: Path = DEFAULT_HISTORY_PATH, max_bytes: int = DEFAULT_MAX_BYTES):
        self._path = path
        self._max_bytes = max_bytes
        self._entries: list[HistoryEntry] = []
        self._next_id = 1
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        # errors="replace": a torn/concurrent write must not crash startup;
        # the mangled line just fails json.loads below and is skipped
        with open(self._path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    self._entries.append(HistoryEntry(
                        id=d["id"],
                        timestamp=d["timestamp"],
                        source=d["source"],
                        translations=d.get("translations", {}),
                    ))
                    self._next_id = max(self._next_id, d["id"] + 1)
                except Exception:
                    continue

    def append(self, source: str, translations: dict[str, str]) -> int:
        entry = HistoryEntry(
            id=self._next_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            source=source,
            translations=translations,
        )
        self._next_id += 1
        self._entries.append(entry)
        self._flush()
        self._trim_if_needed()
        return entry.id

    def get(self, entry_id: int) -> HistoryEntry | None:
        for e in self._entries:
            if e.id == entry_id:
                return e
        return None

    def navigate(self, current_id: int | None, direction: int) -> HistoryEntry | None:
        """direction: -1 = back (older), +1 = forward (newer)."""
        if not self._entries:
            return None
        if current_id is None:
            return self._entries[-1] if direction < 0 else self._entries[0]
        ids = [e.id for e in self._entries]
        try:
            idx = ids.index(current_id)
        except ValueError:
            return self._entries[-1]
        new_idx = idx + direction
        if 0 <= new_idx < len(self._entries):
            return self._entries[new_idx]
        return None

    def all_entries(self) -> list[HistoryEntry]:
        return list(self._entries)

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(json.dumps({
                    "id": entry.id,
                    "timestamp": entry.timestamp,
                    "source": entry.source,
                    "translations": entry.translations,
                }, ensure_ascii=False) + "\n")

    def _trim_if_needed(self) -> None:
        if self._path.exists() and self._path.stat().st_size > self._max_bytes:
            # Remove oldest 10% of entries
            cut = max(1, len(self._entries) // 10)
            self._entries = self._entries[cut:]
            self._flush()

# Aggregator History → SQLite + Clear Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the JSONL-backed aggregator history/MT-cache with a standalone SQLite store and add a "Clear Translation Cache…" menu action.

**Architecture:** `ta/core/history.py` becomes a SQLite-backed `HistoryStore` (own file `~/.local/share/ta-python/history.db`, one-time JSONL import). `AggregatorWidget` drops its in-memory `_mt_cache`/`_pending_translations` and reads/writes the store directly. `CombinedMainWindow` gains a Tools-menu clear action.

**Tech Stack:** Python 3.12, sqlite3 stdlib, PySide6, pytest.

**Spec:** `docs/superpowers/specs/2026-07-15-aggregator-history-sqlite-design.md`

## Global Constraints

- Activate venv first: `source .venv/bin/activate`
- `history_max_bytes` setting keeps its name and default `20_971_520` (20 MB).
- Legacy JSONL is imported then renamed to `history.jsonl.bak` — never deleted.
- `ta.db` / `translation_assistant/db.py` untouched.
- Corrupt `history.db` must never block startup (rename to `.corrupt`, start fresh).
- Language pair stored as `Language.name` strings (e.g. `"Japanese"`); empty string = legacy/unknown.
- Store methods take plain `str` languages; only the widget converts `Language` enums via `.name`.

---

### Task 1: SQLite-backed HistoryStore

**Files:**
- Rewrite: `ta/core/history.py`
- Rewrite: `tests/test_history.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (used by Tasks 2–3):
  - `HistoryStore(path=DEFAULT_DB_PATH, max_bytes=DEFAULT_MAX_BYTES, *, legacy_jsonl=None, _conn=None)`
  - `append(source: str, translations: dict[str, str], src_lang: str = "", dst_lang: str = "", thinking: str = "") -> int` (upsert)
  - `find(source: str, src_lang: str, dst_lang: str) -> tuple[str, str] | None` — `(ollama_text, thinking)`; falls back to legacy empty-lang rows
  - `get(entry_id) -> HistoryEntry | None`, `navigate(current_id, direction) -> HistoryEntry | None`, `all_entries() -> list[HistoryEntry]` — same semantics as today
  - `clear() -> int` (bytes freed), `size_bytes() -> int`
  - `HistoryEntry` dataclass gains `src_lang: str = ""`, `dst_lang: str = ""`, `thinking: str = ""`

- [ ] **Step 1: Write the failing tests** — replace `tests/test_history.py` with:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_history.py -q`
Expected: FAIL/ERROR (`unexpected keyword argument`, missing methods).

- [ ] **Step 3: Rewrite `ta/core/history.py`**

```python
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
```

Note: `DEFAULT_HISTORY_PATH` (old name) disappears; grep confirms nothing outside `history.py` imports it.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_history.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ta/core/history.py tests/test_history.py
git commit -m "feat(history): SQLite-backed HistoryStore with upsert, find, clear, migration"
```

---

### Task 2: AggregatorWidget uses the store as MT cache

**Files:**
- Modify: `ta/ui/aggregator_widget.py`
- Modify: `tests/test_ollama.py` (fixture paths + cache-seeding sites)

**Interfaces:**
- Consumes (Task 1): `HistoryStore.find(source, src_lang, dst_lang)`, `append(source, translations, src_lang, dst_lang, thinking)`, `clear()`, `size_bytes()`.
- Produces (Task 3): `AggregatorWidget.clear_history() -> int` (bytes freed). Store reachable as `agg._history`.

- [ ] **Step 1: Update the widget** — in `ta/ui/aggregator_widget.py`:

1. Delete instance state in `__init__`: the `self._pending_translations` and `self._mt_cache` lines. Delete the `self._seed_mt_cache()` call and the whole `_seed_mt_cache` method (including its ponytail comment — the wart is fixed for real now).
2. `_on_translate` cache check becomes:

```python
        cached = self._history.find(text, src.name, dst.name)
        if cached is not None:
            self._ollama_debounce.stop()
            translation, thinking = cached
            self._ollama_panel.show_result(translation, text, src, dst, thinking)
            self._start_prefetch_idle()
        else:
            # Debounce so rapid line-skipping only translates where we settle.
            self._ollama_debounce.start()
```

3. `_on_ollama_ready` writes straight to the store (persists even if the user already moved on):

```python
    def _on_ollama_ready(self, _ignored: str) -> None:
        text = "".join(self._ollama_chunks)
        if not text:
            return
        source, src, dst = self._ollama_panel.request_key()
        self._history.append(source, {"ollama": text}, src.name, dst.name,
                             "".join(self._ollama_thinking))
        self._notify_ollama_done(text)
        self._start_prefetch_idle()
```

(The generic `translation_ready` hookup still calls `_on_translation_received("ollama", "")`, which the empty-text guard drops — streaming ready emits `""`.)

4. `_on_translation_received` upserts one engine at a time (store merges):

```python
    def _on_translation_received(self, name: str, text: str) -> None:
        if not text:
            return
        src = self._source_panel.src_language()
        dst = self._source_panel.dst_language()
        self._history.append(self._current_source, {name: text},
                             src.name, dst.name)
```

5. `_fire_prefetch`: replace the two `key` lines (`key = (text, src, dst)` / `if key in self._mt_cache: continue`) with:

```python
            if self._history.find(text, src.name, dst.name) is not None:
                continue
            self._prefetch_key = (text, src, dst)
```

6. `_on_prefetch_ready` persists the result:

```python
    def _on_prefetch_ready(self, _ignored: str) -> None:
        text = "".join(self._prefetch_chunks)
        if text and self._prefetch_key is not None:
            source, src, dst = self._prefetch_key
            self._history.append(source, {"ollama": text}, src.name, dst.name,
                                 "".join(self._prefetch_thinking))
        self._prefetch_key = None
        self._prefetch_done += 1
        self._fire_prefetch()
```

7. New public method next to `translate_source`:

```python
    def clear_history(self) -> int:
        """Wipe translation history + MT cache. Returns bytes freed on disk."""
        freed = self._history.clear()
        self._history_current_id = None
        return freed
```

- [ ] **Step 2: Update `tests/test_ollama.py`**

- Every `HistoryStore(path=tmp_path / "history.jsonl", ...)` → `HistoryStore(path=tmp_path / "history.db", ...)` (3 sites: ~533, ~831, ~857; plus ~651).
- Cache seeding `w._mt_cache[(text, src, dst)] = (t, think)` → `w._history.append(text, {"ollama": t}, src.name, dst.name, think)` (sites ~548, ~633, ~887, ~903).
- Cache asserts `w._mt_cache[key] == (t, think)` → `w._history.find(text, src.name, dst.name) == (t, think)` (sites ~582, ~625, ~657, ~921). The ~657 startup-seeding test now covers the legacy empty-lang fallback: seed via `w._history.append("古い行", {"ollama": "old line"})` (no langs) and assert `find` with the current pair still hits.
- `w._pending_translations["ollama"] == "Hello world"` (~583) → assert via history: the entry for that source has `translations["ollama"] == "Hello world"`.
- Keep `w._history.all_entries()` asserts (~586, ~940) — API unchanged. Where a test previously expected one history entry per translator response, expect one merged entry per source line.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_ollama.py tests/test_history.py -q`
Expected: all PASS. Fix any straggler that still pokes `_mt_cache`/`_pending_translations` (grep both names — must be zero hits in `ta/` and `tests/`).

- [ ] **Step 4: Commit**

```bash
git add ta/ui/aggregator_widget.py tests/test_ollama.py
git commit -m "refactor(aggregator): MT cache backed by SQLite history store"
```

---

### Task 3: Clear Translation Cache menu action

**Files:**
- Modify: `translation_assistant/ui/combined_window.py` (Tools menu, ~line 170)
- Modify: `tests/test_combined_window.py`

**Interfaces:**
- Consumes (Task 2): `AggregatorWidget.clear_history() -> int`, `agg._history.size_bytes()`.
- Produces: Tools-menu action "Clear Translation Cache…"; `CombinedMainWindow._on_clear_translation_cache()`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_combined_window.py`:

```python
def test_clear_translation_cache_action(combined_window, monkeypatch):
    win = combined_window
    agg = win._agg_widget
    agg._history.append("line", {"ollama": "cached"}, "Japanese", "English")
    assert len(agg._history.all_entries()) == 1

    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    win._on_clear_translation_cache()
    assert agg._history.all_entries() == []

    # Declining leaves history alone
    agg._history.append("line2", {"ollama": "kept"}, "Japanese", "English")
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.No)
    win._on_clear_translation_cache()
    assert len(agg._history.all_entries()) == 1


def test_clear_translation_cache_in_tools_menu(combined_window):
    win = combined_window
    labels = []
    for menu in win.menuBar().actions():
        if menu.text() == "Tools":
            labels = [a.text() for a in menu.menu().actions()]
    assert "Clear Translation Cache…" in labels
```

Use the existing fixture that patches `HistoryStore` (~line 44) — update its path from `tmp_path / "history.jsonl"` to `tmp_path / "history.db"`. Match the file's existing fixture name for `combined_window` (check top of file; reuse whatever the other menu tests use).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_combined_window.py -q -k clear_translation`
Expected: FAIL (`no attribute '_on_clear_translation_cache'`).

- [ ] **Step 3: Implement** — in `_setup_menubar`, right after `tools_menu.addAction(history_action)`:

```python
        clear_cache_action = QAction("Clear Translation Cache…", self)
        clear_cache_action.triggered.connect(self._on_clear_translation_cache)
        tools_menu.addAction(clear_cache_action)
```

New handler (near `_on_wp_settings`; add `QMessageBox` to the PySide6 imports if absent):

```python
    def _on_clear_translation_cache(self) -> None:
        agg = self._agg_widget
        mb = agg._history.size_bytes() / (1024 * 1024)
        resp = QMessageBox.question(
            self, "Clear Translation Cache",
            f"Delete translation history and cached machine translations "
            f"({mb:.1f} MB)?\nThis cannot be undone.",
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        freed = agg.clear_history()
        self._ta_widget.status_bar().showMessage(
            f"Translation cache cleared — freed {freed / (1024 * 1024):.1f} MB",
            5000,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_combined_window.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/combined_window.py tests/test_combined_window.py
git commit -m "feat(aggregator): Clear Translation Cache menu action"
```

---

### Task 4: Docs + full-suite verification

**Files:**
- Modify: `CLAUDE.md` (sqlite3 rule, test count)

- [ ] **Step 1: Update CLAUDE.md**

In "Key design decisions", amend the db.py bullet's last sentence:

> Never import `sqlite3` outside `db.py` — with one sanctioned exception: `ta/core/history.py`, the aggregator's standalone history/MT-cache store (`~/.local/share/ta-python/history.db`), kept separate so the aggregator stays self-contained.

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`
Expected: all PASS, no skips introduced. Update the "Total: 850 tests" line in CLAUDE.md to the new count printed by pytest.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: sanction sqlite3 in ta/core/history.py; bump test count"
```

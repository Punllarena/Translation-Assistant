# Aggregator history/cache → SQLite + cache cleanup

**Date:** 2026-07-15
**Status:** approved approach (B-standalone), spec pending user review

## Problem

- `~/.local/share/ta-python/history.jsonl` is 20 MB (at its trim ceiling) and is
  both the translation history and the Ollama MT-cache seed.
- `HistoryStore._flush()` rewrites the whole file on **every** append
  (`ta/core/history.py:90`) — a 20 MB disk write per translated line.
- The whole file is held in RAM twice: `HistoryStore._entries` plus the
  `AggregatorWidget._mt_cache` dict seeded from it.
- `_seed_mt_cache()` has a known correctness wart (ponytail comment,
  `aggregator_widget.py:249`): history entries don't record their language
  pair, so the cache seeds everything under whatever pair is active at startup.
- `_on_translation_received()` appends a new history entry per translator
  response, so one source line with N enabled panels produces N near-duplicate
  entries — the main reason the file hit 20 MB.
- There is no user-facing way to clear the cache/history.

The main TA database (`ta.db`, 57 KB) is healthy and out of scope.

## Decision

Replace the JSONL-backed `HistoryStore` with a standalone SQLite database at
`~/.local/share/ta-python/history.db` (XDG-aware, same directory as today).
It stays inside `ta/core/history.py` and does **not** touch
`translation_assistant/db.py` or `ta.db`. Add a "Clear translation cache…"
menu action.

Rejected alternatives:
- **A. Patch JSONL in place** (append-mode writes + clear button): smallest
  diff, but keeps the RAM mirror, the per-translator duplication, and the
  language-pair wart.
- **B-shared. Reuse `translation_assistant/db.py`:** couples the aggregator to
  TA's storage; the aggregator is deliberately self-contained.

## Design

### Schema (`ta/core/history.py`)

```sql
CREATE TABLE IF NOT EXISTS entries (
    id           INTEGER PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    source       TEXT NOT NULL,
    src_lang     TEXT NOT NULL DEFAULT '',
    dst_lang     TEXT NOT NULL DEFAULT '',
    translations TEXT NOT NULL DEFAULT '{}',   -- JSON dict engine -> text
    thinking     TEXT NOT NULL DEFAULT '',      -- Ollama thinking trace
    UNIQUE(source, src_lang, dst_lang)
);
```

The UNIQUE constraint + upsert replaces today's duplicate-per-translator
appends: repeated results for the same (source, langs) merge into one row's
`translations` JSON.

`sqlite3` is currently only imported in `translation_assistant/db.py` per
CLAUDE.md. This spec adds `ta/core/history.py` as the second sanctioned
import site (the aggregator is standalone by design); CLAUDE.md gets updated
to say so.

### HistoryStore API

Constructor keeps the `_conn: sqlite3.Connection | None` injection seam
pattern from `db.py` (tests use `:memory:`).

- `append(source, translations, src_lang="", dst_lang="", thinking="") -> int`
  — upsert by (source, src_lang, dst_lang); merges the translations dict into
  the existing row's JSON, updates timestamp/thinking. Returns row id.
- `get(id)`, `navigate(current_id, direction)`, `all_entries()` — same
  semantics as today (HistoryDialog and prev/next navigation depend on them);
  now SQL queries instead of list scans. `HistoryEntry` dataclass gains
  `src_lang`, `dst_lang`, `thinking` fields.
- `find(source, src_lang, dst_lang) -> tuple[str, str] | None` — MT cache
  lookup; returns `(ollama_text, thinking)`. Matches exact language pair
  **or** legacy rows with empty langs (imported pre-migration entries).
- `clear() -> int` — `DELETE FROM entries` + `VACUUM`; returns bytes freed
  (file size before − after) for the confirmation feedback.
- `size_bytes() -> int` — current db file size, for the confirm dialog.
- Retention: unchanged setting `history_max_bytes` (default 20 MB). After
  append, if file size exceeds it: delete oldest 10 % of rows, `VACUUM`.
  Also enforced once at startup. With upsert-dedup, hitting the cap should
  now be rare.

### Migration (one-time, inside `HistoryStore.__init__`)

If `history.db` has zero rows and `history.jsonl` exists: import every valid
JSONL line (empty `src_lang`/`dst_lang`, merged via the same upsert), then
rename the file to `history.jsonl.bak`. Nothing is deleted; `ta.db` is never
touched. Malformed lines are skipped, same as today's loader.

### AggregatorWidget changes

- Delete the `_mt_cache` dict, `_seed_mt_cache()`, and its ponytail wart.
  Cache hits become `self._history.find(text, src, dst)` (indexed lookup,
  sub-millisecond at this scale).
- `_on_translation_received()` passes the current language pair to
  `append()`. Ollama's ready-handler also passes the thinking trace.
- Prefetch results (`_on_prefetch_ready`) now persist via `append()` instead
  of dying with the session — prefetched lines stay cached across restarts.
- New `clear_history() -> int` — calls `store.clear()`, resets
  `_history_current_id`, returns bytes freed.

### Menu action (`CombinedMainWindow`)

"Clear translation cache…" following the existing menu-bar pattern
(`_setup_menubar` pulls a `QAction`). Confirm dialog shows current size
("Delete translation history and cache? Frees ~20 MB. This cannot be
undone."); on confirm, calls `aggregator.clear_history()` and reports the
freed amount in the TA status bar.

### Error handling

- DB open failure (corrupt file): rename the bad file to `history.db.corrupt`
  and start fresh — history is a cache, losing it must never block startup
  (mirrors the JSONL loader's tolerance).
- Migration import errors: per-line skip, never abort startup.

### Testing

- Rewrite `tests/test_history.py` against the SQLite store via the `_conn`
  seam: append/upsert-merge, navigate, find (exact + legacy empty-lang
  fallback), clear, retention trim, JSONL migration (import + `.bak` rename),
  corrupt-db recovery.
- Aggregator-level: cache hit via `find` skips Ollama fire; prefetch result
  persisted; `clear_history` empties store.
- `test_combined_window.py`: menu action exists and triggers clear after
  confirm.

## Out of scope

- Main `ta.db` maintenance (tiny, healthy).
- Age-based retention, LRU policies (size cap suffices).
- Recording MT usage in TA's stats/heatmap (possible later, not now).

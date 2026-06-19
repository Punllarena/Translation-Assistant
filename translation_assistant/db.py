"""
Database access layer — SQLite backend for profiles, glossary, documents, lines.
All other modules import from here; nothing else imports sqlite3 directly.
"""
import sqlite3
from pathlib import Path

_EN_WORDS = (
    "COALESCE(SUM(CASE WHEN TRIM(translated_text) != '' "
    "THEN LENGTH(TRIM(translated_text)) - LENGTH(REPLACE(TRIM(translated_text), ' ', '')) + 1 "
    "ELSE 0 END), 0)"
)

_EN_WORDS_L = _EN_WORDS.replace("translated_text", "l.translated_text")

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS profiles (
    id          INTEGER PRIMARY KEY,
    name        TEXT    UNIQUE NOT NULL,
    parse_chars TEXT    NOT NULL
                        DEFAULT '、 。 ？ ！ 「 」 …… ',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    is_default  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS glossary (
    id          INTEGER PRIMARY KEY,
    profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    phrase      TEXT    NOT NULL,
    translation TEXT    NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(profile_id, phrase)
);

CREATE INDEX IF NOT EXISTS idx_glossary_profile ON glossary(profile_id, sort_order);

CREATE TABLE IF NOT EXISTS custom_words (
    id          INTEGER PRIMARY KEY,
    profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    word        TEXT    NOT NULL COLLATE NOCASE,
    UNIQUE(profile_id, word)
);

CREATE INDEX IF NOT EXISTS idx_words_profile ON custom_words(profile_id);

CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY,
    title           TEXT    NOT NULL,
    source_language TEXT    NOT NULL DEFAULT 'ja',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    last_position   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lines (
    id              INTEGER PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    line_number     INTEGER NOT NULL,
    prefix          TEXT    NOT NULL DEFAULT '%',
    raw_text        TEXT    NOT NULL,
    translated_text TEXT    NOT NULL DEFAULT '',
    UNIQUE(document_id, line_number)
);

CREATE INDEX IF NOT EXISTS idx_lines_document ON lines(document_id, line_number);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS series_profiles (
    series_title TEXT PRIMARY KEY,
    profile_name TEXT NOT NULL DEFAULT ''
);
"""


class Database:
    def __init__(self, path: "Path | str", *, _conn: sqlite3.Connection | None = None) -> None:
        if _conn is not None:
            self._conn = _conn
        else:
            self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._apply_schema()

    def _apply_schema(self) -> None:
        self._conn.executescript(_DDL)
        # Seed schema_version if not present
        if not self._conn.execute("SELECT * FROM schema_version").fetchone():
            self._conn.execute("INSERT INTO schema_version VALUES (1)")
            self._conn.commit()
        # Ensure foreign keys are on for this connection (WAL set per session)
        self._conn.execute("PRAGMA foreign_keys = ON")
        # Idempotent column migrations
        existing = {r[1] for r in self._conn.execute("PRAGMA table_info(documents)").fetchall()}
        for col, defn in [
            ("series_title",  "TEXT    NOT NULL DEFAULT ''"),
            ("series_order",  "INTEGER NOT NULL DEFAULT 0"),
            ("chapter_title", "TEXT    NOT NULL DEFAULT ''"),
        ]:
            if col not in existing:
                self._conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {defn}")
        self._conn.commit()

        # Idempotent column migration for series_profiles
        sp_existing = {r[1] for r in self._conn.execute("PRAGMA table_info(series_profiles)").fetchall()}
        if "syosetu_url" not in sp_existing:
            self._conn.execute(
                "ALTER TABLE series_profiles ADD COLUMN syosetu_url TEXT NOT NULL DEFAULT ''"
            )
        self._conn.commit()

        # Idempotent column migration for source_url on documents
        doc_existing = {r[1] for r in self._conn.execute("PRAGMA table_info(documents)").fetchall()}
        if "source_url" not in doc_existing:
            self._conn.execute(
                "ALTER TABLE documents ADD COLUMN source_url TEXT NOT NULL DEFAULT ''"
            )
        self._conn.commit()

        # Idempotent column migration for translated_at on lines
        lines_existing = {r[1] for r in self._conn.execute("PRAGMA table_info(lines)").fetchall()}
        if "translated_at" not in lines_existing:
            self._conn.execute(
                "ALTER TABLE lines ADD COLUMN translated_at TEXT DEFAULT NULL"
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── Profiles ──────────────────────────────────────────────────────────────

    def list_profiles(self) -> list[str]:
        rows = self._conn.execute("SELECT name FROM profiles ORDER BY name").fetchall()
        return [r[0] for r in rows]

    def get_profile_id(self, name: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM profiles WHERE name = ?", (name,)
        ).fetchone()
        return row[0] if row else None

    def create_profile(self, name: str, *, is_default: bool = False) -> int:
        cur = self._conn.execute(
            "INSERT INTO profiles (name, is_default) VALUES (?, ?)",
            (name, 1 if is_default else 0),
        )
        self._conn.commit()
        return cur.lastrowid

    def rename_profile(self, old: str, new: str) -> None:
        self._conn.execute(
            "UPDATE profiles SET name = ? WHERE name = ?", (new, old)
        )
        self._conn.commit()

    def delete_profile(self, name: str) -> None:
        row = self._conn.execute(
            "SELECT is_default FROM profiles WHERE name = ?", (name,)
        ).fetchone()
        if row and row[0]:
            raise ValueError(f"Cannot delete the default profile '{name}'")
        self._conn.execute("DELETE FROM profiles WHERE name = ?", (name,))
        self._conn.commit()

    # ── Glossary ──────────────────────────────────────────────────────────────

    def get_glossary(self, profile: str) -> list[tuple[str, str]]:
        pid = self.get_profile_id(profile)
        if pid is None:
            return []
        rows = self._conn.execute(
            "SELECT phrase, translation FROM glossary "
            "WHERE profile_id = ? ORDER BY sort_order, id",
            (pid,),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def set_glossary(self, profile: str, rows: list[tuple[str, str]]) -> None:
        pid = self.get_profile_id(profile)
        if pid is None:
            raise ValueError(f"Profile '{profile}' not found")
        with self._conn:
            self._conn.execute("DELETE FROM glossary WHERE profile_id = ?", (pid,))
            self._conn.executemany(
                "INSERT INTO glossary (profile_id, phrase, translation, sort_order) "
                "VALUES (?, ?, ?, ?)",
                [(pid, phrase, translation, i) for i, (phrase, translation) in enumerate(rows)],
            )

    def add_phrase(self, profile: str, phrase: str, translation: str) -> None:
        pid = self.get_profile_id(profile)
        if pid is None:
            raise ValueError(f"Profile '{profile}' not found")
        max_order = self._conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM glossary WHERE profile_id = ?", (pid,)
        ).fetchone()[0]
        self._conn.execute(
            "INSERT OR REPLACE INTO glossary (profile_id, phrase, translation, sort_order) "
            "VALUES (?, ?, ?, ?)",
            (pid, phrase, translation, max_order + 1),
        )
        self._conn.commit()

    def delete_phrase(self, profile: str, phrase: str) -> None:
        pid = self.get_profile_id(profile)
        if pid is None:
            raise ValueError(f"Profile '{profile}' not found")
        self._conn.execute(
            "DELETE FROM glossary WHERE profile_id = ? AND phrase = ?", (pid, phrase)
        )
        self._conn.commit()

    # ── Custom words ──────────────────────────────────────────────────────────

    def get_custom_words(self, profile: str) -> list[str]:
        pid = self.get_profile_id(profile)
        if pid is None:
            return []
        rows = self._conn.execute(
            "SELECT word FROM custom_words WHERE profile_id = ? ORDER BY word", (pid,)
        ).fetchall()
        return [r[0] for r in rows]

    def add_word(self, profile: str, word: str) -> None:
        pid = self.get_profile_id(profile)
        if pid is None:
            raise ValueError(f"Profile '{profile}' not found")
        self._conn.execute(
            "INSERT OR IGNORE INTO custom_words (profile_id, word) VALUES (?, ?)", (pid, word)
        )
        self._conn.commit()

    # ── Documents ─────────────────────────────────────────────────────────────

    def list_documents(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT d.id, d.title, d.series_title, d.series_order, d.chapter_title,
                   d.updated_at, d.last_position, d.source_url,
                   CAST(COALESCE(
                       SUM(CASE WHEN TRIM(l.raw_text) != '' AND l.translated_text != '' THEN 1 ELSE 0 END) * 100
                       / NULLIF(SUM(CASE WHEN TRIM(l.raw_text) != '' THEN 1 ELSE 0 END), 0), 0
                   ) AS INTEGER) AS progress
            FROM documents d
            LEFT JOIN lines l ON l.document_id = d.id
            GROUP BY d.id
            ORDER BY d.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def create_document(self, title: str, *,
                        series_title: str = "",
                        series_order: int = 0,
                        chapter_title: str = "",
                        source_url: str = "") -> int:
        cur = self._conn.execute(
            "INSERT INTO documents (title, series_title, series_order, chapter_title, source_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, series_title, series_order, chapter_title, source_url),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_document_metadata(self, doc_id: int, *,
                                 series_title: str,
                                 series_order: int,
                                 chapter_title: str) -> None:
        self._conn.execute(
            "UPDATE documents SET series_title=?, series_order=?, chapter_title=? WHERE id=?",
            (series_title, series_order, chapter_title, doc_id),
        )
        self._conn.commit()

    def get_series_list(self) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT title FROM (
                SELECT DISTINCT series_title AS title
                  FROM documents WHERE series_title != ''
                UNION
                SELECT DISTINCT series_title AS title
                  FROM series_profiles WHERE series_title != ''
            ) ORDER BY title
            """
        ).fetchall()
        return [r[0] for r in rows]

    def get_series_profile(self, series_title: str) -> str:
        row = self._conn.execute(
            "SELECT profile_name FROM series_profiles WHERE series_title = ?",
            (series_title,),
        ).fetchone()
        return row[0] if row else ""

    def set_series_profile(self, series_title: str, profile_name: str) -> None:
        self._conn.execute(
            "INSERT INTO series_profiles (series_title, profile_name) VALUES (?, ?) "
            "ON CONFLICT(series_title) DO UPDATE SET profile_name = excluded.profile_name",
            (series_title, profile_name),
        )
        self._conn.commit()

    def get_next_series_order(self, series_title: str) -> int:
        row = self._conn.execute(
            "SELECT MAX(series_order) FROM documents WHERE series_title = ?",
            (series_title,),
        ).fetchone()
        return (row[0] or 0) + 1

    def get_series_url(self, series_title: str) -> str:
        row = self._conn.execute(
            "SELECT syosetu_url FROM series_profiles WHERE series_title = ?",
            (series_title,),
        ).fetchone()
        return row[0] if row else ""

    def set_series_url(self, series_title: str, url: str) -> None:
        self._conn.execute(
            "INSERT INTO series_profiles (series_title, syosetu_url) VALUES (?, ?) "
            "ON CONFLICT(series_title) DO UPDATE SET syosetu_url = excluded.syosetu_url",
            (series_title, url),
        )
        self._conn.commit()

    def get_series_chapters(self, series_title: str) -> list[int]:
        rows = self._conn.execute(
            "SELECT series_order FROM documents WHERE series_title = ? ORDER BY series_order",
            (series_title,),
        ).fetchall()
        return [r[0] for r in rows]

    def get_document_ids_by_series(self, series_title: str) -> list[int]:
        rows = self._conn.execute(
            "SELECT id FROM documents WHERE series_title = ? ORDER BY series_order",
            (series_title,),
        ).fetchall()
        return [r[0] for r in rows]

    def get_series_list_full(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT
                all_series.title,
                COALESCE(sp.syosetu_url, '')  AS url,
                COUNT(d.id)                   AS chapter_count,
                COALESCE(sp.profile_name, '') AS profile_name
            FROM (
                SELECT DISTINCT series_title AS title
                  FROM documents WHERE series_title != ''
                UNION
                SELECT DISTINCT series_title AS title
                  FROM series_profiles WHERE series_title != ''
            ) all_series
            LEFT JOIN documents d       ON d.series_title  = all_series.title
            LEFT JOIN series_profiles sp ON sp.series_title = all_series.title
            GROUP BY all_series.title
            ORDER BY all_series.title
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_document(self, doc_id: int) -> None:
        self._conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self._conn.commit()

    def get_document(self, doc_id: int) -> dict:
        row = self._conn.execute(
            "SELECT id, title, series_title, series_order, chapter_title, "
            "source_language, created_at, updated_at, last_position, source_url "
            "FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Document {doc_id} not found")
        return dict(row)

    def set_last_position(self, doc_id: int, pos: int) -> None:
        self._conn.execute(
            "UPDATE documents SET last_position = ? WHERE id = ?", (pos, doc_id)
        )
        self._conn.commit()

    # ── Lines ─────────────────────────────────────────────────────────────────

    def get_lines(self, doc_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT line_number, prefix, raw_text, translated_text "
            "FROM lines WHERE document_id = ? ORDER BY line_number",
            (doc_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_lines(self, doc_id: int, lines: list[dict]) -> None:
        # Read existing translated_at before deleting — autosave must not wipe them
        existing_ts = {
            r[0]: r[1]
            for r in self._conn.execute(
                "SELECT line_number, translated_at FROM lines WHERE document_id = ?", (doc_id,)
            ).fetchall()
        }
        with self._conn:
            self._conn.execute("DELETE FROM lines WHERE document_id = ?", (doc_id,))
            self._conn.executemany(
                "INSERT INTO lines "
                "(document_id, line_number, prefix, raw_text, translated_text, translated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        doc_id,
                        ln["line_number"],
                        ln["prefix"],
                        ln["raw_text"],
                        ln.get("translated_text", ""),
                        existing_ts.get(ln["line_number"]),
                    )
                    for ln in lines
                ],
            )
            self._conn.execute(
                "UPDATE documents SET updated_at = datetime('now') WHERE id = ?", (doc_id,)
            )

    def replace_raw_content(self, doc_id: int, new_raw_lines: list[str]) -> None:
        """Replace raw lines, preserving translated_text by line index."""
        existing = self.get_lines(doc_id)
        old_translations = [r["translated_text"] for r in existing]
        rows = []
        for i, ln in enumerate(new_raw_lines):
            if not ln:
                prefix, raw_text = "", ""
            elif ln[0] in ("%", "$"):
                prefix, raw_text = ln[0], ln[1:]
            else:
                prefix, raw_text = "%", ln
            rows.append({
                "line_number": i,
                "prefix": prefix,
                "raw_text": raw_text,
                "translated_text": old_translations[i] if i < len(old_translations) else "",
            })
        self.save_lines(doc_id, rows)

    def save_translation(self, doc_id: int, line_number: int, text: str) -> None:
        self._conn.execute(
            "UPDATE lines SET translated_text = ?, "
            "translated_at = CASE WHEN ? != '' THEN datetime('now') ELSE NULL END "
            "WHERE document_id = ? AND line_number = ?",
            (text, text, doc_id, line_number),
        )
        self._conn.commit()

    def get_today_stats(self) -> dict:
        row = self._conn.execute(
            f"SELECT COUNT(*) AS paragraphs, "
            f"COALESCE(SUM(LENGTH(raw_text)), 0) AS chars, "
            f"{_EN_WORDS} AS en_words "
            f"FROM lines "
            f"WHERE translated_at IS NOT NULL AND date(translated_at) = date('now')"
        ).fetchone()
        return {"paragraphs": row[0], "chars": row[1], "en_words": row[2]}

    def get_daily_stats(self, days: int = 30) -> list[dict]:
        rows = self._conn.execute(
            f"SELECT date(translated_at) AS date, "
            f"COUNT(*) AS paragraphs, "
            f"COALESCE(SUM(LENGTH(raw_text)), 0) AS chars, "
            f"{_EN_WORDS} AS en_words "
            f"FROM lines "
            f"WHERE translated_at IS NOT NULL "
            f"AND date(translated_at) >= date('now', ? || ' days') "
            f"GROUP BY date(translated_at) "
            f"ORDER BY date DESC",
            (f"-{days}",),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_daily_stats(self) -> list[dict]:
        rows = self._conn.execute(
            f"SELECT date(translated_at) AS date, "
            f"COUNT(*) AS paragraphs, "
            f"COALESCE(SUM(LENGTH(raw_text)), 0) AS chars, "
            f"{_EN_WORDS} AS en_words "
            f"FROM lines "
            f"WHERE translated_at IS NOT NULL "
            f"GROUP BY date(translated_at) "
            f"ORDER BY date ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_summary_stats(self) -> dict:
        def _q(where: str) -> dict:
            row = self._conn.execute(
                f"SELECT COUNT(*) AS paragraphs, "
                f"COALESCE(SUM(LENGTH(raw_text)), 0) AS chars, "
                f"{_EN_WORDS} AS en_words "
                f"FROM lines WHERE translated_at IS NOT NULL {where}"
            ).fetchone()
            return {"paragraphs": row[0], "chars": row[1], "en_words": row[2]}

        return {
            "today":   _q("AND date(translated_at) = date('now')"),
            "week":    _q("AND date(translated_at) >= date('now', '-7 days')"),
            "month":   _q("AND date(translated_at) >= date('now', '-30 days')"),
            "alltime": _q(""),
        }

    def get_series_stats(self) -> list[dict]:
        rows = self._conn.execute(
            f"SELECT d.series_title AS series, "
            f"COUNT(l.id) AS paragraphs, "
            f"COALESCE(SUM(LENGTH(l.raw_text)), 0) AS chars, "
            f"{_EN_WORDS_L} AS en_words, "
            f"COUNT(DISTINCT l.document_id) AS chapters "
            f"FROM lines l "
            f"JOIN documents d ON d.id = l.document_id "
            f"WHERE l.translated_at IS NOT NULL AND d.series_title != '' "
            f"GROUP BY d.series_title "
            f"ORDER BY paragraphs DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def find_tm_matches(
        self, raw_text: str, current_doc_id: int | None, limit: int = 5
    ) -> list[dict]:
        rows = self._conn.execute(
            "SELECT l.translated_text, d.title AS doc_title, d.updated_at "
            "FROM lines l "
            "JOIN documents d ON d.id = l.document_id "
            "WHERE l.raw_text = ? AND l.translated_text != '' "
            "AND (? IS NULL OR l.document_id != ?) "
            "ORDER BY d.updated_at DESC "
            "LIMIT ?",
            (raw_text, current_doc_id, current_doc_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Migration helper ──────────────────────────────────────────────────────────

def migrate_files_to_db(profile_dir: Path, db: Database) -> None:
    """
    One-time import of CSV and LEX files from an existing Profile/ directory.
    Idempotent: skips profiles already in the DB. Does not delete source files.
    """
    from translation_assistant.core import load_glossary  # avoid circular import at module level

    for csv_path in sorted(profile_dir.glob("*.csv")):
        name = csv_path.stem
        if db.get_profile_id(name) is not None:
            continue
        db.create_profile(name, is_default=(name == "Default"))
        rows = load_glossary(csv_path)
        if rows:
            db.set_glossary(name, rows)

        lex_path = profile_dir / f"{name}.lex"
        if lex_path.exists():
            for line in lex_path.read_text(encoding="utf-8").splitlines():
                word = line.strip()
                if word and not word.startswith("#"):
                    db.add_word(name, word)

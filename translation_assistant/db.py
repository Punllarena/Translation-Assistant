"""
Database access layer — SQLite backend for profiles, glossary, documents, lines.
All other modules import from here; nothing else imports sqlite3 directly.
"""
import sqlite3
from pathlib import Path

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
                   d.updated_at, d.last_position,
                   CAST(COALESCE(
                       SUM(CASE WHEN l.translated_text != '' THEN 1 ELSE 0 END) * 100
                       / NULLIF(COUNT(l.id), 0), 0
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
                        chapter_title: str = "") -> int:
        cur = self._conn.execute(
            "INSERT INTO documents (title, series_title, series_order, chapter_title) "
            "VALUES (?, ?, ?, ?)",
            (title, series_title, series_order, chapter_title),
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
            "SELECT DISTINCT series_title FROM documents "
            "WHERE series_title != '' ORDER BY series_title"
        ).fetchall()
        return [r[0] for r in rows]

    def delete_document(self, doc_id: int) -> None:
        self._conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self._conn.commit()

    def get_document(self, doc_id: int) -> dict:
        row = self._conn.execute(
            "SELECT id, title, series_title, series_order, chapter_title, "
            "source_language, created_at, updated_at, last_position "
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
        with self._conn:
            self._conn.execute("DELETE FROM lines WHERE document_id = ?", (doc_id,))
            self._conn.executemany(
                "INSERT INTO lines (document_id, line_number, prefix, raw_text, translated_text) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        doc_id,
                        ln["line_number"],
                        ln["prefix"],
                        ln["raw_text"],
                        ln.get("translated_text", ""),
                    )
                    for ln in lines
                ],
            )
            self._conn.execute(
                "UPDATE documents SET updated_at = datetime('now') WHERE id = ?", (doc_id,)
            )

    def save_translation(self, doc_id: int, line_number: int, text: str) -> None:
        self._conn.execute(
            "UPDATE lines SET translated_text = ? "
            "WHERE document_id = ? AND line_number = ?",
            (text, doc_id, line_number),
        )
        self._conn.commit()


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

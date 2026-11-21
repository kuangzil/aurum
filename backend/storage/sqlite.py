"""SQLite is authoritative; vector indexing is a separate, retryable operation."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    return value.astimezone(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    embedding_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(embedding_status IN ('pending','indexed','failed')),
                    metadata_json TEXT
                );
                CREATE INDEX IF NOT EXISTS messages_session_time
                    ON messages(session_id, created_at_utc);
                CREATE INDEX IF NOT EXISTS messages_time ON messages(created_at_utc);
                CREATE INDEX IF NOT EXISTS messages_embedding ON messages(embedding_status);
                CREATE TABLE IF NOT EXISTS gold_price_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    source TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    price TEXT NOT NULL,
                    quoted_at_utc TEXT NOT NULL,
                    fetched_at_utc TEXT NOT NULL,
                    observed_hour_utc TEXT NOT NULL,
                    is_stale INTEGER NOT NULL CHECK(is_stale IN (0,1)),
                    UNIQUE(source, symbol, currency, observed_hour_utc)
                );
                CREATE INDEX IF NOT EXISTS gold_hour ON gold_price_snapshots(observed_hour_utc);
            """)

            conn.executescript(Path(__file__).with_name("research.sql").read_text())

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()


class MessageRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, session_id: str, role: Literal['user', 'assistant'], content: str,
             message_id: str | None = None, created_at: datetime | None = None,
             metadata_json: str | None = None) -> dict:
        message_id = message_id or str(uuid4())
        timestamp = utc_iso(created_at or utc_now())
        with self.db.connect() as conn:
            conn.execute("INSERT INTO sessions VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                         (session_id, timestamp, timestamp))
            conn.execute("""INSERT INTO messages
                (message_id,session_id,role,content,created_at_utc,metadata_json)
                VALUES (?,?,?,?,?,?) ON CONFLICT(message_id) DO NOTHING""",
                (message_id, session_id, role, content, timestamp, metadata_json))
            row = dict(conn.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone())
            if (row['session_id'], row['role'], row['content']) != (session_id, role, content):
                raise ValueError("Message ID already belongs to a different immutable message")
            conn.execute("UPDATE sessions SET updated_at_utc=MAX(updated_at_utc,?) WHERE session_id=?",
                         (row['created_at_utc'], session_id))
        return row

    def history(self, session_id: str, limit: int = 100, exclude_id: str = '') -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("""SELECT * FROM messages WHERE session_id=? AND message_id!=?
                ORDER BY created_at_utc DESC, rowid DESC LIMIT ?""", (session_id, exclude_id, limit)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get(self, session_id: str, message_id: str) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM messages WHERE session_id=? AND message_id=?",
                               (session_id, message_id)).fetchone()
        return dict(row) if row else None

    def pending(self, session_id: str | None = None, limit: int = 100) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("""SELECT * FROM messages WHERE embedding_status!='indexed'
                AND (? IS NULL OR session_id=?) ORDER BY created_at_utc, rowid LIMIT ?""",
                (session_id, session_id, limit)).fetchall()
        return [dict(row) for row in rows]

    def mark_indexed(self, message_id: str, success: bool) -> None:
        with self.db.connect() as conn:
            # A concurrent failed attempt must not undo another successful upsert.
            conn.execute("""UPDATE messages SET embedding_status=? WHERE message_id=?
                AND (embedding_status!='indexed' OR ?='indexed')""",
                ('indexed' if success else 'failed', message_id, 'indexed' if success else 'failed'))

    def revision(self, session_id: str, exclude_id: str = '') -> tuple:
        with self.db.connect() as conn:
            return tuple(conn.execute("""SELECT COUNT(*), COALESCE(MAX(rowid),0),
                COALESCE(SUM(embedding_status='indexed'),0) FROM messages
                WHERE session_id=? AND message_id!=?""", (session_id, exclude_id)).fetchone())

    def turn_revisions(self, session_id: str, user_id: str, assistant_id: str) -> tuple[tuple, tuple]:
        # One statement: concurrent writers cannot slip between base/current reads.
        with self.db.connect() as conn:
            row = conn.execute("""SELECT COUNT(*), COALESCE(MAX(rowid),0),
                COALESCE(SUM(embedding_status='indexed'),0),
                COALESCE(SUM(message_id NOT IN (?,?)),0),
                COALESCE(MAX(CASE WHEN message_id NOT IN (?,?) THEN rowid END),0)
                FROM messages WHERE session_id=?""",
                (user_id, assistant_id, user_id, assistant_id, session_id)).fetchone()
        return tuple(row[3:]), tuple(row[:3])

    def reset_index(self) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE messages SET embedding_status='pending'")

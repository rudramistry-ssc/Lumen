"""SQLite storage. init_db() also upgrades existing PoC databases."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from config import get_settings

# sessions: one scan and its OCR text. messages: the chat turns that follow it.
SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,                      -- random hex, safe to expose
    text TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',        -- language tag reported by OCR
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                       -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages (session_id, id);

CREATE TABLE IF NOT EXISTS documents (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    document_id TEXT,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    # New connection per call: simple, and fine for a single-process demo.
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row            # rows behave like dicts
    conn.execute("PRAGMA foreign_keys = ON")  # makes ON DELETE CASCADE work
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    # Tiny migration so an older data/app.db keeps working after code changes.
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    # Called once on startup; creates the folder and tables if missing.
    Path(get_settings().db_path).parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "sessions", "language", "language TEXT NOT NULL DEFAULT ''")

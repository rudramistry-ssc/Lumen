"""All session/message SQL lives here so the routers stay readable."""

import uuid
from datetime import datetime, timezone

from db import get_conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_session() -> dict:
    session_id = uuid.uuid4().hex
    created_at = _now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, text, language, created_at) VALUES (?, '', '', ?)",
            (session_id, created_at),
        )
    return {"session_id": session_id, "text": "", "language": "", "created_at": created_at}


def get_session(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, text, language, created_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "session_id": row["id"],
        "text": row["text"],
        "language": row["language"],
        "created_at": row["created_at"],
    }


def set_session_scan(session_id: str, text: str, language: str) -> None:
    # Called once per scan; the latest scanned document wins.
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET text = ?, language = ? WHERE id = ?",
            (text, language, session_id),
        )


def add_message(session_id: str, role: str, content: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, _now()),
        )


def recent_messages(session_id: str, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    # Newest N first for the LIMIT, then flipped back to chronological order.
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

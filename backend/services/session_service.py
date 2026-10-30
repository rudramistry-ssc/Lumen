"""All session/message SQL lives here so the routers stay readable."""

import json
import uuid
from datetime import datetime, timezone

from pydantic import JsonValue

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
            """SELECT s.id, s.text, s.language, s.created_at,
                      d.document_id, d.status AS document_status
               FROM sessions s LEFT JOIN documents d ON d.session_id = s.id
               WHERE s.id = ?""",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "session_id": row["id"],
        "text": row["text"],
        "language": row["language"],
        "created_at": row["created_at"],
        "document_id": row["document_id"],
        "document_status": row["document_status"],
    }


def set_session_scan(session_id: str, text: str, language: str) -> None:
    # Called once per scan; the latest scanned document wins.
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET text = ?, language = ? WHERE id = ?",
            (text, language, session_id),
        )
        conn.execute("DELETE FROM documents WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))


def set_session_document(
    session_id: str, document: dict[str, JsonValue], text: str, language: str
) -> None:
    """Commit a complete result and reset history for the newly selected document."""
    encoded = json.dumps(document, ensure_ascii=False, allow_nan=False)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO documents (session_id, document_id, status, result_json)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                   document_id = excluded.document_id,
                   status = excluded.status,
                   result_json = excluded.result_json""",
            (session_id, document.get("document_id"), document["status"], encoded),
        )
        conn.execute(
            "UPDATE sessions SET text = ?, language = ? WHERE id = ?",
            (text, language, session_id),
        )
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))


def get_document(session_id: str) -> dict[str, JsonValue] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT result_json FROM documents WHERE session_id = ?", (session_id,)
        ).fetchone()
    return json.loads(row["result_json"]) if row else None


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


def conversation_history(session_id: str) -> list[dict[str, str]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def add_turn(session_id: str, question: str, answer: str) -> None:
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            [
                (session_id, "user", question, _now()),
                (session_id, "assistant", answer, _now()),
            ],
        )

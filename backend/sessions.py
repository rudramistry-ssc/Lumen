"""Bounded, ephemeral sessions. Run one app worker; New session discards context."""
import json
from dataclasses import dataclass, field
from threading import RLock
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException


@dataclass
class Session:
    id: str
    size: int
    touched: float = field(default_factory=monotonic)
    ready: bool = False
    busy: bool = True
    # The image turn exactly as the model saw it (image + its JSON answer).
    conversation: list[dict] = field(default_factory=list)
    history: list[dict[str, str]] = field(default_factory=list)


class SessionStore:
    def __init__(self, ttl=3600, capacity=32, max_bytes=128 * 1024 * 1024):
        self.ttl, self.capacity, self.max_bytes = ttl, capacity, max_bytes
        self._sessions: dict[str, Session] = {}
        self._lock = RLock()

    def _prune(self):
        now = monotonic()
        for key, session in list(self._sessions.items()):
            if now - session.touched > self.ttl:
                del self._sessions[key]

    def reserve(self, session_id: str | None, size: int) -> Session:
        with self._lock:
            self._prune()
            key = session_id or str(uuid4())
            if key in self._sessions:
                raise HTTPException(409, "Start a New session before adding another image.")
            if (len(self._sessions) >= self.capacity
                    or sum(s.size for s in self._sessions.values()) + size > self.max_bytes):
                raise HTTPException(503, "Session storage is full. Close an existing session and try again.")
            session = Session(key, size)
            self._sessions[key] = session
            return session

    def get(self, key: str) -> Session:
        with self._lock:
            self._prune()
            session = self._sessions.get(key)
            if session is None:
                raise HTTPException(404, "This session ended or expired. Start a New session and upload your image.")
            session.touched = monotonic()
            return session

    def finish_upload(self, session: Session, conversation: list[dict]):
        with self._lock:
            if self.get(session.id) is not session:
                raise HTTPException(404, "This session has ended.")
            size = len(json.dumps(conversation))
            if sum(s.size for s in self._sessions.values()) - session.size + size > self.max_bytes:
                raise HTTPException(503, "Session storage is full. Try a smaller image.")
            session.conversation, session.size = conversation, size
            session.ready, session.busy = True, False

    def begin_chat(self, key: str) -> Session:
        with self._lock:
            session = self.get(key)
            if not session.ready or session.busy:
                raise HTTPException(409, "Wait for the current image or answer to finish.")
            session.busy = True
            return session

    def finish_chat(self, session: Session, question: str, answer: str):
        with self._lock:
            if self.get(session.id) is not session:
                raise HTTPException(404, "This session has ended.")
            session.history.extend([
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ])

    def release_chat(self, session: Session):
        with self._lock:
            session.busy = False

    def delete(self, key: str):
        with self._lock:
            self._sessions.pop(key, None)

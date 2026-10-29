"""Session = one scan plus the chat that follows it."""

from fastapi import APIRouter, HTTPException

from models.schemas import SessionOut
from services import session_service

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session():
    # The client calls this first, then reuses the id for upload and chat.
    return session_service.create_session()


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str):
    # Useful after a page reload to recover the current OCR text.
    session = session_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

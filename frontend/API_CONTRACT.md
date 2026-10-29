# API contract (frontend ↔ backend)

Draft so the frontend and the FastAPI backend build to the same thing. Change it together if needed. The frontend code for these calls is all in `api.js`.

All routes are under `/api`. Errors return a normal HTTP error code with `{"detail": "message"}` (FastAPI's default).

## `GET /api/health`
Lets the UI show "Backend connected" or "Backend offline".

```json
{ "status": "ok" }
```

## `POST /api/extract`
Image → text + language. **Core feature.**

Request: `multipart/form-data`
| field        | type   | notes                       |
|--------------|--------|-----------------------------|
| `image`      | file   | jpg / png / webp, ≤ 10 MB   |
| `session_id` | string | short id made by the UI     |

Response:
```json
{
  "text": "AVIS\nAscenseur hors service.\n...",
  "language": "fr",
  "confidence": 0.91
}
```
- `language` is one of `"en"`, `"fr"`, `"mixed"`.
- `confidence` (0–1) is optional; the UI hides it if missing.
- Keep line breaks in `text` (`\n`); the UI shows them.

## `POST /api/chat`
Follow-up questions about the image, with session history.

Request (`application/json`):
```json
{
  "session_id": "5d08c3cf",
  "message": "When will it be fixed?",
  "context_text": "NOTICE\nElevator out of service...",
  "language": "en",
  "history": [
    { "role": "user", "content": "What does it say?" },
    { "role": "assistant", "content": "The elevator is out of service." }
  ]
}
```
- `context_text` is the extracted text **after the user's edits**, so the backend should use it instead of its own stored copy.
- `language` is the language the reply should be in.
- `history` is sent every time, so the backend can stay stateless if that's easier. If you store history in the DB by `session_id`, you can ignore it.

Response:
```json
{ "reply": "The notice says repairs should be finished by Friday at 5:00 PM.", "language": "en" }
```

## Not needed yet
- **Text-to-speech:** done in the browser for now (works offline with the computer's voices). Later this could become `POST /api/tts` → audio file.
- **Voice input:** the browser's speech recognition is used for now, which is not offline. For true offline use, add `POST /api/transcribe` (audio file → `{ "text": "..." }`) with Whisper, and the UI will switch to it.

## CORS
If the frontend is opened from a different port than FastAPI, enable CORS:
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```
Simplest option: let FastAPI serve the `frontend/` folder so there's no CORS at all:
```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")  # add after the /api routes
```

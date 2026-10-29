# API contract (frontend ↔ backend)

What the frontend sends to the backend and expects back. All of it is in `api.js`; the backend side is in `backend/` (see `backend/README.md`). Errors come back as a normal HTTP error code with `{"detail": "message"}` (FastAPI's default), and the UI shows that message under its own error text.

The backend address is `API_BASE_URL` in `config.js` (default `http://127.0.0.1:8000`).

## `GET /healthz`
Lets the UI show "Backend connected" or "Backend offline".

```json
{ "status": "ok" }
```

## `POST /v1/sessions`
The UI makes its own short session id (shown in the footer). The first time it needs the backend in a session, `api.js` calls this once and remembers the backend's `session_id` for that UI session. **New session** in the UI starts a fresh one.

```json
{ "session_id": "8f550995d6674619be8944898434beda", "text": "", "language": "", "created_at": "…" }
```

## `POST /v1/sessions/{id}/images`
Image → text + language. **Core feature.**

Request: `multipart/form-data`, field **`file`** (jpg / png / webp; the UI allows ≤ 10 MB, the backend ≤ 15 MB).

Response:
```json
{
  "session_id": "…",
  "text": "Elevator out of service.\nPlease use the stairs…",
  "language": "en",
  "confidence": 0.96,
  "audio_url": "/v1/media/….wav",
  "ms": 530
}
```
- `language` is `"en"`, `"fr"`, `"mixed"`, or `""` when OCR can't tell. The UI turns `""` into English; the user can change it.
- `confidence` (0–1) can be `null`; the UI hides it then.
- `text` keeps line breaks (`\n`); the UI shows them and lets the user edit them.
- `audio_url` is not used by the UI: it reads aloud with the browser's voices (offline, with word highlighting).

## `POST /v1/sessions/{id}/chat`
Follow-up questions about the photo.

Request: `multipart/form-data` (not JSON)
| field      | notes |
|------------|-------|
| `message`  | the question |
| `language` | `"en"` or `"fr"`: the language the answer should be in (the UI language) |
| `context`  | the extracted text **after the user's edits**; the backend uses it instead of its stored copy |

The backend keeps the conversation history itself (last 10 turns per session).

Response:
```json
{ "transcript": "When will it be fixed?", "reply": "The notice says repairs should be finished by Friday at 5:00 PM.", "audio_url": "/v1/media/….wav" }
```

## Demo mode
With `USE_MOCK: true` in `config.js`, or `?demo` in the address, `api.js` returns fake answers instead and never calls the backend.

## Not built yet
- **Offline voice input:** the mic uses the browser's speech recognition (Chrome/Edge, needs internet). The backend already accepts an `audio` field on the chat route, but the AI service's `/v1/stt` returns 501 until someone adds Whisper.

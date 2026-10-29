# CanAI Team E — backend

Thin orchestration API. It owns sessions, uploads, audio files, and SQLite.
All OCR / TTS / STT / chat logic lives in the separate AI service.

To run the whole app (frontend + backend + AI service), see the root
[README](../README.md). This file is about the backend on its own.

## Run with Docker

```bash
cd backend
docker compose up --build
```

- Frontend: http://localhost:5500
- API: http://localhost:8000 (docs at `/docs`)
- AI service: internal only at `http://ai:8000`, built from `../ai-service` (Tesseract inside)
- Chat needs Ollama running on the host; the AI container reaches it at `host.docker.internal:11434`
- Data: named volume `appdata` → `/data` (sqlite + audio survive restarts)

From inside a container, the host is `host.docker.internal`, **not** `localhost`.

Reset the demo data: `docker compose down -v`.

## Run locally (backend only)

From the repository root, with the root virtual environment active
(`pip install -r requirements.txt` there installs everything):

```bash
cd backend
cp .env.example .env
uvicorn main:app --reload
```

The AI service must be running at `AI_BASE_URL` (default `http://localhost:9000`).
`python run.py` in the repository root starts both for you.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/sessions` | create a session |
| GET | `/v1/sessions/{id}` | session + current OCR text |
| POST | `/v1/sessions/{id}/images` | multipart `file` → OCR + TTS |
| POST | `/v1/sessions/{id}/chat` | form `message` (or `audio`), optional `language`, `context` → reply + TTS |
| GET | `/v1/media/{name}` | generated audio (`.wav` from the local AI service, `.mp3` also accepted) |
| GET | `/healthz` | liveness |

Scan response:

```json
{ "session_id": "…", "text": "…", "language": "en", "confidence": 0.96, "audio_url": "/v1/media/….wav", "ms": 530 }
```

Chat response:

```json
{ "transcript": "…", "reply": "…", "audio_url": "/v1/media/….wav" }
```

`audio_url` is relative — prepend the API base URL on the client. It is `""`
when `TTS_ENABLED` is false. `confidence` (0–1) is `null` if the AI service
doesn't report one.

## Frontend notes

- New session: `POST /v1/sessions`, then keep `session_id`.
- Image drop/paste: `POST /v1/sessions/{id}/images` as `multipart/form-data` with the field named **`file`**.
- Chat text: same URL as chat, multipart field **`message`** (not JSON).
- Chat options: **`language`** (`en`/`fr`) is the language the answer should be in; **`context`** is the scanned text after the user's edits. Without `context`, the session's stored OCR text is used.
- Chat voice: multipart field **`audio`** with the recorded blob (`audio/webm` is fine).
- Read aloud / pause: play `audio_url` with a normal `<audio>` element — pause is client-side, no extra endpoint.
- `language` is a short tag from OCR (`en`, `fr`, …); it is `""` until an image is scanned.

## Contract with the AI service

The AI service must expose these under `AI_BASE_URL`:

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/v1/ocr` | multipart `file` | `{ "text": "…", "language": "en", "confidence"?: 0.96 }` |
| POST | `/v1/tts` | JSON `{ "text": "…", "voice": "…", "language": "en" }` | `audio/mpeg` or `audio/wav` bytes |
| POST | `/v1/stt` | multipart `file` | `{ "text": "…" }` (not built yet: the AI service answers 501) |
| POST | `/v1/reply` | JSON `{ "message", "context", "history", "language" }` | `{ "reply": "…" }` |

`context` is the OCR text from the last scan (or the user's edited copy); `history` is up to 10 previous
`{ "role", "content" }` turns. The AI service listens on `0.0.0.0` inside its
container so `http://ai:8000` resolves from the api container.

| Frontend Need         | Backend Endpoint                         | Notes                                                                 |
|-----------------------|------------------------------------------|-----------------------------------------------------------------------|
| New session           | `POST /v1/sessions`                      | Returns `session_id`; store it and use it for all subsequent requests. |
| Drop/paste image      | `POST /v1/sessions/{id}/images`          | `multipart/form-data`, field name: `file`.                            |
| Detected language     | ✅ Added                                 | Returned as `language` in scan response and `GET /v1/sessions/{id}`.  |
| Text from picture     | Same scan response                       | Available in `text`.                                                  |
| Read aloud / pause    | `audio_url` from scan response           | WAV/MP3; pause/play handled client-side with HTML `<audio>`. The current frontend reads aloud with browser voices instead (word highlighting). |
| Chat – text input     | `POST /v1/sessions/{id}/chat`            | `multipart/form-data`, field name: `message`.                         |
| Chat – voice input    | `POST /v1/sessions/{id}/chat`            | `multipart/form-data`, field name: `audio` (`audio/webm` from `MediaRecorder`). Needs `/v1/stt`, not built yet; the frontend uses browser speech recognition. |
| Chat – text output    | Same chat response                       | Returned in `reply` (plus transcript of the user's message).          |
| Chat – voice output   | Same chat response                       | Returned in `audio_url` (WAV/MP3).                                    |

Notes:

- Browser recordings arrive as `audio/webm`; the AI service should accept that.
- Images are forwarded untouched (HEIC/EXIF handling belongs to the AI side).
- One uvicorn process, no queue, no retries. A slow AI call just means a slow
  request; the timeout is 120s.

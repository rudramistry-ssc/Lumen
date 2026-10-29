# CanAI Team E — backend

Thin orchestration API. It owns sessions, uploads, audio files, and SQLite.
All OCR / TTS / STT / chat logic lives in the separate AI service.

## Run with Docker (demo setup)

```bash
cd backend
cp .env.example .env          # optional, compose has its own env
docker compose up --build
```

- API: http://localhost:8000 (docs at `/docs`)
- AI service: internal only at `http://ai:8000`, built from `../ocr`
- UI: served by the API at http://localhost:8000 (static files from `../frontend`, mounted via `FRONTEND_DIR`)
- Data: named volume `appdata` → `/data` (sqlite + mp3s survive restarts)

If the AI service isn't containerised yet, remove the `ai` service and
`depends_on` from `docker-compose.yml`, then set `AI_BASE_URL` to wherever it
runs. From inside a container, the host is `host.docker.internal`, **not**
`localhost`.

Reset the demo data: `docker compose down -v`.

## Run locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/sessions` | create a session |
| GET | `/v1/sessions/{id}` | session + current OCR text |
| POST | `/v1/sessions/{id}/images` | multipart `file` → OCR + TTS |
| POST | `/v1/sessions/{id}/chat` | multipart `audio` or form `message` → reply + TTS |
| GET | `/v1/media/{name}.mp3` | generated audio |
| GET | `/healthz` | liveness |

Scan response:

```json
{ "session_id": "…", "text": "…", "language": "en", "audio_url": "/v1/media/….mp3", "ms": 4210 }
```

Chat response:

```json
{ "transcript": "…", "reply": "…", "audio_url": "/v1/media/….mp3" }
```

`audio_url` is relative — prepend the API base URL on the client.

## Frontend notes

- New session: `POST /v1/sessions`, then keep `session_id`.
- Image drop/paste: `POST /v1/sessions/{id}/images` as `multipart/form-data` with the field named **`file`**.
- Chat text: same URL as chat, multipart field **`message`** (not JSON).
- Chat voice: multipart field **`audio`** with the recorded blob (`audio/webm` is fine).
- Read aloud / pause: play `audio_url` with a normal `<audio>` element — pause is client-side, no extra endpoint.
- `language` is a short tag from OCR (`en`, `fr`, …); it is `""` until an image is scanned.

## Contract with the AI service

The AI service must expose these under `AI_BASE_URL`:

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/v1/ocr` | multipart `file` | `{ "text": "…", "language": "en" }` |
| POST | `/v1/tts` | JSON `{ "text": "…", "voice": "…" }` | `audio/mpeg` bytes |
| POST | `/v1/stt` | multipart `file` | `{ "text": "…" }` |
| POST | `/v1/reply` | JSON `{ "message", "context", "history" }` | `{ "reply": "…" }` |

`context` is the OCR text from the last scan; `history` is up to 10 previous
`{ "role", "content" }` turns. The AI service listens on `0.0.0.0` inside its
container so `http://ai:8000` resolves from the api container.

| Frontend Need         | Backend Endpoint                         | Notes                                                                 |
|-----------------------|------------------------------------------|-----------------------------------------------------------------------|
| New session           | `POST /v1/sessions`                      | Returns `session_id`; store it and use it for all subsequent requests. |
| Drop/paste image      | `POST /v1/sessions/{id}/images`          | `multipart/form-data`, field name: `file`.                            |
| Detected language     | ✅ Added                                 | Returned as `language` in scan response and `GET /v1/sessions/{id}`.  |
| Text from picture     | Same scan response                       | Available in `text`.                                                  |
| Read aloud / pause    | `audio_url` from scan response           | Plain MP3; pause/play handled client-side with HTML `<audio>`. No extra endpoint required. |
| Chat – text input     | `POST /v1/sessions/{id}/chat`            | `multipart/form-data`, field name: `message`.                         |
| Chat – voice input    | `POST /v1/sessions/{id}/chat`            | `multipart/form-data`, field name: `audio` (`audio/webm` from `MediaRecorder`). |
| Chat – text output    | Same chat response                       | Returned in `reply` (plus transcript of the user's message).          |
| Chat – voice output   | Same chat response                       | Returned in `audio_url` (MP3).                                        |

Notes:

- Browser recordings arrive as `audio/webm`; the AI service should accept that.
- Images are forwarded untouched (HEIC/EXIF handling belongs to the AI side).
- One uvicorn process, no queue, no retries. A slow AI call just means a slow
  request; the timeout is 120s.




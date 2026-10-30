# CanAI Team E — backend

Thin orchestration API. It owns sessions, uploads, audio files, and SQLite.
Legacy mode uses the OCR HTTP service. Document mode calls the local AI packages
and a persistent Qwen server.

## Vision-first integration milestone

The AI branch is now combined with the application on `integration/offline-poc`.
The repository-root Compose setup runs the full application:

```bash
# From the repository root (not backend/):
docker compose up --build
```

First setup downloads verified models into `signspeak_models`; subsequent
offline starts use `docker compose up --pull never --no-build`. SQLite,
documents and media live in `signspeak_appdata`. See [the root guide](../README.md)
for ports, RAM/disk recommendations, live checks and troubleshooting commands.
The original `backend/docker-compose.yml` remains an OCR-only demo.

To try the new upload path locally, first provision Tesseract (English/French),
the pinned Qwen model/projector and llama.cpp as described in
[the AI handoff](../handoff/README.md). Then, in a Python environment:

```bash
cd backend
pip install -r requirements-ai.txt
cp .env.example .env
# In a separate terminal/environment, start the provisioned Qwen server once:
python -m signspeak_llm serve --vision --context-size 8192 --threads 4
# Keep it running, then start the application:
uvicorn main:app --reload
```

`IMAGE_PROCESSING_MODE=document` selects `DocumentProcessor`; the default
`ocr_service` preserves the old HTTP OCR path. Configure `SIGNSPEAK_LLM_URL`,
`DOCUMENT_CACHE_DIR`, and `DOCUMENT_TIMEOUT_SECONDS` in `.env`.
The standard bounded AI worker remains enabled. One expensive upload is allowed
at a time per backend process; uploads, Q&A and Piper share this slot.
Another request receives `503` and can be retried.
An upload rejected as busy has not been analysed: the frontend displays a
specific wait/retry notice, not an image-quality error. A request in another
tab can occupy the shared slot for several minutes on CPU. There is no
automatic upload retry or queue.
If the browser loses a chat response, it restores the question draft and warns
that the turn may already be saved. It does not automatically resubmit an
ambiguous network failure, which could duplicate a successful conversation turn.

Vision observations limit alternatives to four readings to prevent
unbounded repetitive JSON generation. Incomplete generations remain failures,
not salvaged partial results. The prompt/schema change gives uploads a new
configuration cache key; old results/evidence are preserved, not deleted.
Exact duplicate observation alternatives are deduplicated with an explicit
normalization warning; literal text is unchanged and raw output is retained.
The scan metadata includes `vision_error` when a vision attempt falls back.

The existing image endpoint now returns selected vision text, `document_id`,
ordered sections, visual descriptions, uncertainties, OCR comparison, guardrails
and execution counts. `needs_review` is a completed, unverified vision result.
`ocr_unreviewed_fallback` is explicitly labelled in the UI, not treated as Qwen
success. Symbol-only images may return empty text with visual descriptions.
Failures return `502`; deadline expiry returns `504`.

SQLite stores the full result and session/document association. Retrieve it with
`GET /v1/sessions/{id}/document`; normal session retrieval includes document ID
and status. Replacing a scan clears the previous conversation history. Keep both
the database and document cache persistent: the AI cache also contains original
image bytes and evidence, so it must not be committed or publicly served.

### Piper and typed conversation

Install `requirements-ai.txt` and provision the English/French Piper voices once,
as described in [the speech guide](../speech/README.md). In the same environment:

```bash
python -m signspeak_speech provision en
python -m signspeak_speech provision fr
```

- `POST /v1/sessions/{id}/read`: form `language=en|fr` and optional
  `include_visual_descriptions=true`; returns `audio_url` (WAV) and metadata.
  Uses `VoiceConversation.read_document`, not image inference.
- `POST /v1/sessions/{id}/chat`: form `message` and `language=en|fr`;
  uses `VoiceConversation.answer_question` with the selected document and full
  history restored from SQLite. Successful pairs are saved atomically.
- Chat returns `status`, `guardrails`, `warnings`, `errors`, `timings` and
  `history_turns` alongside the existing transcript/reply/audio URL fields.
  Blocked turns have no audio and no saved conversation turn. A Piper failure
  preserves the answer/history as `text_only`. A Qwen failure returns `502`.
- The UI plays WAV with pause/stop/speed controls, without word-level timing.
  It does not silently substitute browser speech for document-mode audio.
  Printed text and uncertainty notices use detected languages (no translation).
  Generated answers use the selected English/French interface language.

The selected document is read-only in the UI so displayed text and saved Q&A
context agree. OCR fallback cannot be read or used for chat without explicit
review. Piper is reused across requests; no model downloads happen in handlers.
This path is independent of the legacy `TTS_ENABLED` setting.

### Microphone questions

Install native FFmpeg and the pinned Whisper runtime/model following
[the STT setup](../stt/README.md). Configure `SIGNSPEAK_FFMPEG`,
`SIGNSPEAK_WHISPER_CLI` and `SIGNSPEAK_WHISPER_MODEL` in the process environment
(these AI package variables are not read from the backend `.env` file).

`POST /v1/sessions/{id}/transcribe` accepts multipart `file` and optional
`language=auto|en|fr`. It converts browser audio to 16 kHz mono PCM16 WAV via
`convert_audio`, then calls `VoiceConversation.prepare_question`. The response
includes `status`, `review_text`, `confirmation_required`, detected language,
transcription warnings and timing. It never calls Qwen/Piper or changes history.
The maximum is 60 seconds and the smaller of `MAX_AUDIO_MB` and 8,000,000 bytes.
Invalid audio is `422`, unsupported MIME is `415`, oversized audio is `413`,
missing runtime/model is `503`, and conversion timeout is `504`.

The UI puts the transcript in the existing question box for correction.
Only pressing Send (or Enter) submits the confirmed text to the normal guarded
chat endpoint and shared document history. This explicit submission is the
confirmation boundary; there is no separate voice-answer endpoint. Transcript
preparation status is not trusted from the browser. No microphone audio is
persisted by transcription; conversion/Whisper temporary files are cleaned by
the existing modules. The legacy `/audio` route still stores clips for the old
OCR-only demo. There is no browser cloud-recognition fallback in the UI.

Browser session recovery remains pending. Raw audio submitted directly to document chat is rejected rather than
answered before transcript review.

Quick no-model check: `python -B -m unittest discover -s tests -v` from `backend/`.

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

## Legacy OCR-service contract

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
| Voice clip            | `POST /v1/sessions/{id}/audio`           | `multipart/form-data`, field name: `file`; stored and playable, not transcribed yet. |
| Chat – text input     | `POST /v1/sessions/{id}/chat`            | `multipart/form-data`, field name: `message`.                         |
| Chat – voice input    | `POST /v1/sessions/{id}/chat`            | `multipart/form-data`, field name: `audio` (`audio/webm` from `MediaRecorder`). |
| Chat – text output    | Same chat response                       | Returned in `reply` (plus transcript of the user's message).          |
| Chat – voice output   | Same chat response                       | Returned in `audio_url` (MP3).                                        |

Notes:

- Browser recordings arrive as `audio/webm`; the AI service should accept that.
- Images are forwarded untouched (HEIC/EXIF handling belongs to the AI side).
- One uvicorn process, no queue, no retries. A slow AI call just means a slow
  request; the timeout is 120s.

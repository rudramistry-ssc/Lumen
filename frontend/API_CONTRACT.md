# API contract (frontend ↔ backend)

The UI talks to the FastAPI backend in `backend/`. This file documents what the
frontend actually calls today. All the calls live in `frontend/api.js`.

The backend also serves this folder at `/`, so the browser and the API share one
origin: no CORS, and `API_BASE_URL` in `config.js` stays `""`.

All routes are under `/v1` (plus `/healthz`). Errors return a normal HTTP status
with FastAPI's default body, `{"detail": "message"}`.

## `GET /healthz`

Powers the **Backend connected** / **Backend offline** pill in the top bar.

```json
{ "status": "ok" }
```

`/health` is an alias for external pollers.

## `POST /v1/sessions`

Create a session. The frontend calls this once per UI session, then reuses the
id for every upload and chat message. The "New session" button starts a new one.

```json
{ "session_id": "…", "text": "", "language": "", "created_at": "…" }
```

## `POST /v1/sessions/{session_id}/images`

Image → text + language. **Core feature.**

Request: `multipart/form-data`

| field  | type | notes                                              |
|--------|------|----------------------------------------------------|
| `file` | file | jpg / png / webp, up to `MAX_UPLOAD_MB` (15 MB)     |

The field is named **`file`**, not `image`.

Response:

```json
{
  "session_id": "…",
  "text": "AVIS\nAscenseur hors service.\n…",
  "language": "fr",
  "audio_url": "",
  "ms": 331
}
```

- `language` is `"en"`, `"fr"`, `"mixed"`, or `""` when detection failed.
- Line breaks in `text` are preserved; the UI shows them as-is.
- `audio_url` is `""` until the AI service implements `/v1/tts`.
- There is no `confidence` field. The UI hides the badge when it is missing.

Errors: `404` unknown session, `413` image too large, `415` not an image,
`422` no readable text found.

### Vision-first upload mode

With backend `IMAGE_PROCESSING_MODE=document`, the same image route calls the
local `DocumentProcessor` instead of the OCR HTTP service. It also returns:

- `document_id`, `status`, `selected_method`, `printed_text_status`
- ordered `sections`, `visual_descriptions`, `text_observations`, `warnings`
- `ocr_comparison`, `guardrails`, `cache_hit`, `execution_this_call`

`needs_review` means successful selection of unverified vision content.
`ocr_unreviewed_fallback` is a labelled fallback, not vision success; the UI
disables read-aloud for it. A symbol-only result can have empty `text`.
The UI shows descriptions separately from printed text and exposes the metadata.
Invalid image bytes return `422`, excessive dimensions return `413`, processing
failure returns `502`, deadline expiry returns `504`, and a busy processor or
missing AI installation returns `503`. Structured errors have
`detail.message`, `detail.status`, and available stage/error/warning metadata.

`GET /v1/sessions/{id}/document` returns `{ "session_id": "...", "document": {...} }`
from persistent SQLite storage without rerunning OCR or vision. Normal session
retrieval also includes nullable `document_id` and `document_status`.
New scans reset backend history. Browser page-reload recovery is not wired yet.

The scan itself returns an empty `audio_url`. Read-aloud uses
`POST /v1/sessions/{id}/read` with form `language=en|fr` and optional
`include_visual_descriptions=true`. It returns `{ "audio_url": "...wav",
"metadata": {...} }`; media is served as `audio/wav`.

In document mode, chat accepts form `message` and `language=en|fr` (default en).
The result includes the existing `transcript`, `reply`, `audio_url`, plus
`status` (`ok`, `text_only`, `blocked`), `language`, `guardrails`, `warnings`,
`errors`, `timings` and `history_turns`. History is restored in full from SQLite.
Piper failures preserve the text answer; blocked turns have no audio/history
entry and must not be spoken. Qwen failures return `502`. Missing/failed/fallback
documents return `409`; unsupported languages return `422`. Uploads/read/Q&A
share a single inference slot, returning `503` if busy.

The UI uses server WAV playback for documents and answers, with pause/stop/rate.
There is no word highlighting for WAV. Selected text is read-only to keep Q&A
context consistent. The microphone stays disabled in document mode until the
transcript-review flow is integrated; raw chat audio currently returns `422`.

## `POST /v1/sessions/{session_id}/audio`

Voice clip from the microphone. **Stores it and returns a playable URL; it
does not transcribe yet** — the AI service has no `/v1/stt`.

Request: `multipart/form-data`

| field  | type | notes                                                          |
|--------|------|----------------------------------------------------------------|
| `file` | file | `audio/webm` (Chrome/Edge), `audio/ogg` (Firefox), `audio/mp4` (Safari) |

The field is named **`file`**, like the image upload. The browser records
with `MediaRecorder` (`Speech.record()` in `speech.js`), so this works
offline. Clips are capped at `MAX_AUDIO_MB` (15 MB) and the UI stops
recording automatically after 60 s.

Response `201`:

```json
{
  "session_id": "…",
  "clip_id": "b5dc3f846015456683efaca1e5fb7d7f.webm",
  "audio_url": "/v1/media/b5dc3f846015456683efaca1e5fb7d7f.webm",
  "bytes": 24576,
  "content_type": "audio/webm;codecs=opus",
  "ms": 3
}
```

Errors: `404` unknown session, `413` clip too large, `415` not audio or an
unsupported container, `422` empty file.

## `POST /v1/sessions/{session_id}/chat`

Follow-up questions about the scanned text.

Request: `multipart/form-data` — **not JSON**.

| field     | type | notes                                          |
|-----------|------|------------------------------------------------|
| `message` | text | the typed question                             |
| `audio`   | file | optional recorded clip, `audio/webm` is fine   |

Send either `message` or `audio`. The backend keeps the scan text and the chat
history in SQLite, so the client does not resend `context_text`, `language` or
`history`.

Response:

```json
{ "transcript": "When will it be fixed?", "reply": "…", "audio_url": "" }
```

The UI reads `reply`. `audio_url` is `""` while TTS is off.

**Not working end to end yet.** The backend forwards to the AI service at
`/v1/reply` and `/v1/tts`, and `ocr/service.py` does not implement those yet, so
this route currently answers `502`. The frontend and backend wiring is done; only
the AI side is missing.

## `GET /v1/sessions/{session_id}`

Session plus its latest scan. Useful after a page reload to recover the text.

## `GET /v1/media/{name}`

Generated audio: TTS MP3s and uploaded voice clips. The `Content-Type`
follows the extension (`audio/mpeg`, `audio/webm`, `audio/ogg`, `audio/wav`,
`audio/mp4`). Names are 32 hex characters plus an extension; anything else
answers `404`.

## Not needed yet

- **Text-to-speech:** done in the browser for now (works offline with the
  computer's voices). Later this could become `POST /v1/tts` → audio file.
- **Voice input:** recorded locally with `MediaRecorder` and uploaded to
  `/v1/sessions/{id}/audio`, which works offline. The missing piece is
  transcription: the AI service needs `/v1/stt` (Whisper), and the chat route
  already accepts an `audio` file for that.

## History

An earlier draft of this file specified `/api/health`, `/api/extract` and
`/api/chat`. The backend's `/v1` session API won: `api.js` was updated to match
it, and the `/api/*` routes do not exist.

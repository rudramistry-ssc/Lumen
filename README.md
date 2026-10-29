# CanAI Team E

Turn a picture of text into readable text (and, later, speech). The web frontend for this is called **Lumen**.

| folder       | what it is                                  | how to run                                   |
|--------------|---------------------------------------------|----------------------------------------------|
| `frontend/`  | the web UI (plain HTML/CSS/JS)              | see [frontend/README.md](frontend/README.md) |
| `backend/`   | FastAPI API: sessions, uploads, chat        | see [backend/README.md](backend/README.md)   |
| `ocr/`       | OCR service (`signspeak_ocr`, Tesseract)    | internal, started by Docker                  |

## Architecture

Two small web services, each in its own Docker container:

```
Browser
        │  loads the UI from /  and calls /v1 on the same origin
        ▼
┌──────────────────┐      ┌──────────────────┐
│  Backend  (api)  │ ───▶ │   OCR service    │
│  backend/        │      │   ocr/           │
│  port 8000       │      │   internal only  │
└──────────────────┘      └──────────────────┘
 serves frontend/ at /,    reads text from images
 sessions, uploads,        with Tesseract (English + French)
 database (SQLite)
```

- **Backend** (`backend/`): the only service the frontend talks to. It creates sessions, checks uploads, saves results, and asks the OCR service to do the reading. It also serves the static UI from `frontend/` at `/`, so the browser and the API share one origin and no CORS setup is needed.
- **OCR service** (`ocr/`): a small wrapper around the `signspeak_ocr` package. It takes an image and returns the text and detected language. It is not exposed outside Docker.

## Start the project

Requires Docker.

```bash
cd backend
docker compose up --build
```

- App (UI + API): http://localhost:8000
- Interactive API docs: http://localhost:8000/docs

Stop it with `Ctrl+C`. To also wipe saved data: `docker compose down -v`.

## Open the app

With the stack running, open http://localhost:8000 — the backend serves the UI,
so there is nothing else to start. The top bar shows **Backend connected** when
the API answers. Chat is wired but returns `502` until the AI service implements
`/v1/reply` (see [frontend/API_CONTRACT.md](frontend/API_CONTRACT.md)).

## Working on the UI alone (optional)

For UI-only work you can skip Docker and serve `frontend/` with Python:

```bash
cd frontend
python3 -m http.server 5500
```

Open http://localhost:5500. Set `API_BASE_URL: "http://127.0.0.1:8000"` in
`frontend/config.js` to reach a running API, or `USE_MOCK: true` to use fake
responses. See [frontend/README.md](frontend/README.md).

## Working endpoints

Backend (`http://localhost:8000`):

| Method | Path | What it does |
|---|---|---|
| GET | `/healthz` | Check the backend is running |
| POST | `/v1/sessions` | Create a session and get a `session_id` |
| GET | `/v1/sessions/{id}` | Get a session and its scanned text |
| POST | `/v1/sessions/{id}/images` | Upload an image (form field `file`) and get its text back |

Example scan response (`audio_url` is empty until speech is added):

```json
{ "session_id": "…", "text": "…", "language": "en", "audio_url": "", "ms": 331 }
```

OCR service (internal, called by the backend):

| Method | Path | What it does |
|---|---|---|
| GET | `/healthz` | Check the OCR service is running |
| POST | `/v1/ocr` | Image in, `{ "text", "language" }` out |

## Not implemented yet

| Method | Path | Service | Purpose |
|---|---|---|---|
| POST | `/v1/tts` | OCR / AI service | Text to speech (MP3) |
| POST | `/v1/stt` | OCR / AI service | Speech to text |
| POST | `/v1/reply` | OCR / AI service | Chatbot answer about the scanned text |
| POST | `/v1/sessions/{id}/chat` | Backend | Chat with typed or spoken messages (needs `/v1/stt` and `/v1/reply`) |
| GET | `/v1/media/{name}.mp3` | Backend | Play generated audio (needs `/v1/tts`) |

The backend code for the last two already exists but cannot work until the speech and chat endpoints are built. When `/v1/tts` is ready, set `TTS_ENABLED` to `true` in `backend/docker-compose.yml`.

## Test the image-to-text API

With the project running (see above), open a second terminal:

```bash
# 1. Check the backend is up
curl localhost:8000/healthz

# 2. Create a session and save its id
SID=$(curl -s -X POST localhost:8000/v1/sessions | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

# 3. Upload a test image (English)
curl -F file=@ocr/eval/benchmark/images/english_clean.png localhost:8000/v1/sessions/$SID/images

# 4. Try a French image
curl -F file=@ocr/eval/benchmark/images/french_clean.png localhost:8000/v1/sessions/$SID/images

# 5. Read back the latest scan from the session
curl localhost:8000/v1/sessions/$SID
```

Run these from the repository root. You should get back JSON containing the text from the image, for example `"The library is closed on Monday."` with `"language": "en"`. More test images are in `ocr/eval/benchmark/images/`.

Expected errors: `415` if the file is not an image, `422` if no text is found, `404` for an unknown session.

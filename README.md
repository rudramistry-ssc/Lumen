# Lumen - CanAI Team E

Offline hackathon PoC: upload a sign or notice, display its Qwen3-VL
transcription, hear it with Piper, and ask questions by typing or microphone.
English and French are supported. Vision output and answers remain unverified;
review important information against the original image.

## Start the full app

Install Docker with Docker Compose. From the repository root:

```bash
docker compose up --build
```

Open **http://localhost:8000** once `api` is healthy. API docs are at `/docs`.
If port 8000 is occupied:

```bash
APP_PORT=8001 docker compose up --build
```

The port override example is for Bash/WSL. In PowerShell, set
`$env:APP_PORT = "8001"` before running Compose.

**First setup needs internet:** the image builds Linux CPU runtimes and installs
dependencies, then the `models` setup container downloads about 1.9 GB of pinned
Qwen model/projector, Piper voices and Whisper model files. SHA256 and size are
verified. Build/download time depends on CPU/network; leave setup running.
Downloads are explicit setup work, never part of image or chat handlers.

Subsequent launches reuse the built image and model volume, including offline:

```bash
docker compose up --pull never --no-build
```

The setup container checks existing files without network calls. Missing files
still need internet to provision; damaged files cause an explicit error instead
of being silently accepted. Build caches are not an offline installation bundle:
a fresh machine needs the container image and model volume as well as this repo.

CPU inference can take minutes per photo. Plan for **at least 8 GB RAM allocated
to Docker (12 GB recommended)** and roughly **10 GB free disk** for builds,
images and models. These are starting recommendations, not measured minimums.
The native build defaults to two compiler jobs; inference defaults to four CPU
threads (`AI_THREADS`). GPU setup is not required.

## Try it live

1. Open the app and upload one simple, well-lit English/French image or sample.
2. Wait for interpretation. `needs_review` means the vision result is available,
   not that processing failed. Warnings/descriptions appear separately.
3. Press **Read aloud** for Piper audio; the browser may require a playback click.
4. Type a question and a follow-up. Answers use the saved interpretation/history,
   without rerunning OCR or vision.
5. Allow microphone access, record, and stop. Review/correct the Whisper transcript
   in the question box, then press **Send**. Transcription never auto-submits.
6. Disconnect internet after setup and repeat reading/chat.

Microphone recording requires localhost or HTTPS. Generated answers use the
English/French interface language; read-aloud follows the document's detected
languages (not automatic translation). A failed Piper call preserves a text
answer. A blocked question has no answer audio or successful history entry.
Guardrails are lightweight and do not guarantee jailbreak resistance or accuracy.

## What Docker starts

```text
Browser -> api:8000 (FastAPI + bundled frontend)
             |-- Tesseract + DocumentProcessor (upload once)
             |-- Piper (WAV speech)
             |-- Whisper + FFmpeg (transcript review)
             `-> qwen:8091 (persistent CPU vision/Q&A server)

models setup -> models volume (pinned, verified artifacts)
api          -> appdata volume (SQLite, documents/evidence, generated audio)
```

Only the app is published, bound to localhost. Qwen is internal. API startup
waits for model provisioning and Qwen health. One expensive operation is allowed
at a time; a busy request returns `503` so it can be retried.

```bash
docker compose ps -a
docker compose logs -f models qwen api
docker compose down
```

`down` retains volumes. **Do not use `down -v` unless you intend to delete models
and saved application data.** The app stores uploaded images/evidence in its
private document cache. Do not commit or publicly expose these files.

The PoC has no authentication and is intended for local demos. Saved documents
and history survive backend restarts, but browser page-reload session recovery is
not wired yet: refreshing starts a new UI session. Keep the tab open for a demo.

## Code and details

- [Backend setup and endpoints](backend/README.md)
- [Frontend and API contract](frontend/API_CONTRACT.md)
- [AI provisioning/handoff](handoff/README.md)
- [Document schema](llm/DOCUMENTS.md)
- [Speech licenses/attribution](speech/LICENSES.md)

The old OCR-only setup is preserved: `cd backend && docker compose up --build`.
It does not run the full AI pipeline; use the repository-root Compose file for
the integrated PoC. No cloud AI services or browser recognition are used by the
integrated workflow, and the UI has no external font dependency.

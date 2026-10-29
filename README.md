# Lumen · CanAI Garage, Team E

Point a camera at a sign, poster or notice. Lumen reads the text, tells you if it's English or French, reads it aloud, and answers questions about it in English or French. Everything runs on your own computer: OCR, the AI model and the voices.

- [How it works](#how-it-works)
- [Run it: option A, one command (no Docker)](#option-a-one-command-no-docker)
- [Run it: option B, Docker](#option-b-docker)
- [Check that it works](#check-that-it-works)
- [What works and what doesn't](#what-works-and-what-doesnt)
- [Troubleshooting](#troubleshooting)

---

## How it works

Three small programs talk to each other. The browser only ever talks to the backend.

```
 Browser                Backend                 AI service                  On this computer
 frontend/              backend/                ai-service/
 :5500                  :8000                   :9000
┌───────────┐  HTTP   ┌───────────────┐ HTTP  ┌──────────────────┐        ┌──────────────────────┐
│ photo,    │ ──────▶ │ sessions      │ ────▶ │ /v1/ocr          │ ─────▶ │ Tesseract (eng+fra)  │
│ text box, │         │ uploads       │       │ /v1/reply        │ ─────▶ │ Ollama: llama3.2:3b  │
│ read aloud│ ◀────── │ chat history  │ ◀──── │ /v1/tts          │ ─────▶ │ built-in OS voices   │
│ chat      │         │ SQLite, audio │       │ /v1/stt (501)    │        └──────────────────────┘
└───────────┘         └───────────────┘       └──────────────────┘
  plain HTML/JS          FastAPI                  FastAPI + ocr/ package
```

| folder        | what it is | from branch |
|---------------|------------|-------------|
| `frontend/`   | The web page: upload, editable text, read aloud, chat, EN/FR interface. Plain HTML/CSS/JS, no build step. | `feature/frontend` |
| `backend/`    | The API the browser calls. Keeps sessions, the scanned text and chat history in SQLite, checks uploads, stores audio. It does no AI itself; it asks the AI service. | `dev-sd-backend`, `chore/connect-backend-to-ocr` |
| `ai-service/` | Does the AI work: OCR, chat answers, text to speech. | new on this branch |
| `ocr/`        | The team's OCR package (`signspeak_ocr`): Tesseract with image clean-up, language detection, confidence. Used by the AI service. `ocr/service.py` is the earlier OCR-only web wrapper, still usable on its own. | `feature/signspeak-ocr`, `chore/connect-backend-to-ocr` |
| `run.py`      | Starts all three programs with one command and checks the setup first. | new on this branch |

**What happens when you add a photo**

1. The browser creates a session (`POST /v1/sessions`) the first time, then uploads the photo (`POST /v1/sessions/{id}/images`).
2. The backend checks it's an image under 15 MB and sends it to the AI service (`/v1/ocr`).
3. The AI service runs the team's OCR package. Tesseract reads English and French; if the photo is hard (dark, blurry, small text), it retries on cleaned-up copies. It returns the text, the language (`en`, `fr`, `mixed`) and a confidence score.
4. The backend saves the text in the session, asks the AI service for audio of it (`/v1/tts`), and returns everything to the browser.
5. The browser shows the text (you can fix mistakes), the language (you can change it) and the confidence.

**What happens when you press Read aloud**

The browser reads the text with the computer's own voices (Web Speech API), highlighting each word. It works offline. Mixed text uses an English and a French voice per sentence. (The backend also makes an audio file, `audio_url`, for other clients; the page doesn't need it.)

**What happens when you ask a question**

1. The browser sends the question, the answer language (the interface language: EN or FR) and **your edited text** to `POST /v1/sessions/{id}/chat`.
2. The backend adds the last 10 turns of the conversation and asks the AI service (`/v1/reply`).
3. The AI service sends it all to the local model (Ollama, `llama3.2:3b`) with instructions: answer only from the sign, in the requested language, in 1–3 short sentences, don't invent numbers or dates, and treat the sign's text as data, not instructions.
4. The answer comes back to the browser, which shows it and reads it aloud.

The mic button uses the browser's own speech recognition (Chrome/Edge) to turn your voice into a typed question.

---

## Option A: one command (no Docker)

You need four things on the computer. Install them once.

| what | why | macOS | Windows |
|------|-----|-------|---------|
| **Python 3.11+** | runs everything | [python.org](https://www.python.org/downloads/) | [python.org](https://www.python.org/downloads/): tick **Add python.exe to PATH** |
| **Tesseract** + French | reads the photo | `brew install tesseract tesseract-lang` (see note below) | [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki): during install, under *Additional language data*, tick **French** |
| **Ollama** | runs the AI model | [ollama.com/download](https://ollama.com/download) | [ollama.com/download](https://ollama.com/download) |
| **The model** (2 GB) | answers questions | `ollama pull llama3.2:3b` | `ollama pull llama3.2:3b` |

> **macOS 14 or older:** Homebrew no longer has ready-made Tesseract packages, so `brew install` compiles about 20 libraries and can take over an hour. Use [option B (Docker)](#option-b-docker) instead: Tesseract is installed inside the container automatically.

Then, from the repository folder:

**macOS**
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

**Windows (PowerShell or Command Prompt)**
```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py
```

The first two lines are only needed once. After that, starting the app is just the last line.

`run.py` checks each part, starts the AI service, backend and frontend, waits until they answer, and opens **http://localhost:5500**. It also starts Ollama if it's installed but not running. Press **Ctrl+C** to stop everything.

What it prints when everything is installed (versions will differ):

```
Checking setup
  [ OK ] Python 3.14.6 with all packages
  [ OK ] Tesseract OCR 5.5.0 with English + French
  [ OK ] Language model llama3.2:3b
  [ OK ] Speech engine: macos-say
  [ OK ] Ports 9000, 8000, 5500 are free

Starting
  [ OK ] AI service  http://127.0.0.1:9000
  [ OK ] Backend  http://127.0.0.1:8000
  [ OK ] Frontend  http://127.0.0.1:5500

Lumen is running:  http://localhost:5500
```

If something is missing, it says what and how to fix it, and starts anyway so the rest still works. `python run.py --check` only runs the checks.

---

## Option B: Docker

Needs [Docker Desktop](https://www.docker.com/products/docker-desktop/) and Ollama with the model (see the table above). Tesseract and everything else is installed inside the containers.

```bash
cd backend
docker compose up --build
```

Open **http://localhost:5500**. The first build takes a few minutes; later starts take seconds. Stop with **Ctrl+C**; `docker compose down -v` also deletes saved sessions.

In Docker, the backend's audio files use `espeak-ng` (robotic). That doesn't affect the page, which reads aloud with the browser's voices.

---

## Check that it works

1. **Health:** http://localhost:8000/healthz should say `{"status":"ok"}`. The AI service's own health check (http://localhost:9000/healthz, option A only) lists each part: `ocr`, `llm`, `tts`, `stt`.
2. **In the app:** open it, click **Open app**, click the **English notice** sample. Text should appear in a few seconds with *English* and a confidence around 95%. Ask *What should I do?*. The first answer takes 10–20 s while the model loads, then a few seconds.
3. **Interactive API docs:** http://localhost:8000/docs lets you try each backend route by hand.
4. **From a terminal (macOS), in the repository folder:**
   ```bash
   SID=$(curl -s -X POST localhost:8000/v1/sessions | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
   curl -F file=@ocr/eval/benchmark/images/french_clean.png localhost:8000/v1/sessions/$SID/images
   curl -F message="What does it say?" -F language=en localhost:8000/v1/sessions/$SID/chat
   ```
   Expected errors: `415` if the file isn't an image, `422` if no text is found, `404` for an unknown session.

**Presentation fallback:** if anything fails live, open **http://localhost:5500/?demo**. It runs entirely in the browser with answers that match the three sample photos.

---

## What works and what doesn't

Tested on 29 Oct 2026 on a MacBook (Apple Silicon, macOS 14.6, Chrome) with Docker and with `run.py`.

| feature | status | notes |
|---------|--------|-------|
| Add photo: drag & drop, file picker, samples | ✅ works | tested in the browser end to end |
| Add photo: paste (Ctrl+V), phone camera | ✅ should work | code is there; not tested in this session |
| OCR, English and French | ✅ works | team benchmark (20 images) through the real API: **20/20 read, 0.79% character error rate**, 0.4–1.4 s per image |
| OCR on the sample photos | ⚠️ mostly | all body text read correctly; the white-on-colour banner headings (**NOTICE**, **AVIS**) are missed |
| Language detection | ⚠️ mostly | correct for English and French; short bilingual signs (like the sample) come back as *English* instead of *mixed*. Number-only images give no language (shown as English). You can change it in the dropdown. |
| Confidence % | ✅ works | Tesseract's mean word confidence |
| Edit the text, chat uses your edit | ✅ works | tested through the API (edited text gave the edited answer) |
| Read aloud in the browser (pause, speed, highlighting) | ✅ should work | unchanged from the frontend branch; not listened to in this session. Uses the computer's voices; French needs a French voice installed (Windows: Settings → Time & language → Speech → Add voices) |
| Chat in English and French | ✅ works | Ollama `llama3.2:3b`; answers from the sign, in the interface language; says so when the sign doesn't contain the answer |
| Chat history (follow-up questions) | ✅ works | last 10 turns per session |
| Backend audio (`audio_url`) | ✅ works | macOS `say` and Docker `espeak-ng` tested; **Windows voice code is written but not tested** |
| Voice questions (mic) | ⚠️ browser only | Chrome/Edge speech recognition, which needs internet; not tested in this session. Firefox has no mic support. |
| Offline speech to text (`/v1/stt`) | ❌ not built | returns 501. Add Whisper (e.g. `faster-whisper`) in `ai-service/app.py` |
| Demo mode (`?demo`) | ✅ works | tested |
| Docker (option B) | ✅ works | fully tested on macOS |
| `run.py` (option A) on macOS | ✅ works, except OCR not tested | Tesseract couldn't be installed on the test Mac (see the macOS 14 note); OCR was tested through Docker instead, with the same code |
| `run.py` on Windows | ❓ not tested | written for Windows (paths, PowerShell voices, Ollama location), but nobody has run it on Windows yet |

**Speed:** OCR takes about 0.5–1.5 s. Chat takes 10–20 s for the first answer (model loading), then about 1–9 s on an Apple Silicon Mac. A laptop without a GPU will be slower; for faster answers use `LLM_MODEL=llama3.2:1b` (`ollama pull llama3.2:1b` first), or point `LLM_BASE_URL` at vLLM on the HPC node.

---

## Troubleshooting

| you see | cause | fix |
|---------|-------|-----|
| `python: command not found` (Mac) | macOS only has `python3` | use `python3`, or `.venv/bin/python` |
| Top bar says **Backend offline** | backend not running | start it with `run.py` or Docker; or use `?demo` |
| *Can't reach the backend…* in the app | same | same |
| *(…AI service error (422): Tesseract was not found…)* | Tesseract not installed or not on PATH | install it (table above). On Windows, if it's installed somewhere unusual, set `SIGNSPEAK_TESSERACT_CMD` to the full path of `tesseract.exe` |
| *(…Tesseract language data missing: fra…)* | French not installed | Windows: rerun the Tesseract installer and tick French. Mac: `brew install tesseract-lang` |
| *(…AI service error (503): Cannot reach the language model…)* | Ollama not running | open the Ollama app, or run `ollama serve` |
| *(…language model returned 404: … model 'llama3.2:3b' not found…)* | model not downloaded | `ollama pull llama3.2:3b` |
| `[FAIL] Ports already in use` | the app is already running, or another program uses 5500/8000/9000 | stop the other copy (Ctrl+C in its terminal) |
| *Couldn't read text from this image* / *No readable text found* | photo too blurry or dark, or no text | try a sharper photo, or type the text into the box |
| French read aloud sounds English | no French voice installed | add a French voice in the OS settings, then reload the page |
| Docker: chat fails | Ollama not running on the host | start Ollama before `docker compose up` |

## Settings

All optional. Set them as environment variables before `run.py` or `docker compose up`.

| variable | default | what it does |
|----------|---------|--------------|
| `LLM_MODEL` | `llama3.2:3b` | which model answers questions |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | any OpenAI-compatible server: Ollama, or vLLM on the HPC node |
| `TTS_ENABLED` | `true` | backend makes audio for scans and replies; `false` is a bit faster (option B: edit `backend/docker-compose.yml`) |
| `SIGNSPEAK_TESSERACT_CMD` | (auto) | full path to the Tesseract program if it isn't found |

More detail: [frontend/README.md](frontend/README.md) · [frontend/API_CONTRACT.md](frontend/API_CONTRACT.md) · [backend/README.md](backend/README.md) · [ai-service/README.md](ai-service/README.md) · [ocr/README.md](ocr/README.md)

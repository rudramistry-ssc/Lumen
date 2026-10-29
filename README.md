<div align="center">

# 🍁 Lumen

### Point at any sign. Hear it in English or French.

Lumen reads the text in a photo, tells you which language it's in, reads it aloud,<br>
and answers your questions about it. Everything runs on your own computer.

**CanAI Garage 2026 · Team E**

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)
![Tesseract](https://img.shields.io/badge/OCR-Tesseract%205-5A5A5A)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20·%20llama3.2-000000)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Offline](https://img.shields.io/badge/runs-locally-2ea44f)

</div>

---

## 📖 Contents

1. [What it does](#-what-it-does)
2. [Quick start](#-quick-start)
3. [How it works](#-how-it-works)
4. [What each part does](#-what-each-part-does)
5. [How the parts are connected](#-how-the-parts-are-connected)
6. [Using the app](#-using-the-app)
7. [What works today](#-what-works-today)
8. [What's left to do](#-whats-left-to-do)
9. [Troubleshooting](#-troubleshooting)
10. [Project layout](#-project-layout)
11. [Settings](#%EF%B8%8F-settings)

---

## ✨ What it does

| | |
|---|---|
| 📷 **Add a photo** | Drag and drop, choose a file, paste (Ctrl+V), use the phone camera, or try one of 3 sample photos |
| 🔤 **Read the text** | OCR in English and French, with a confidence score. You can fix any mistakes in the text box |
| 🌐 **Detect the language** | English, French or both. You can change it if the guess is wrong |
| 🔊 **Read it aloud** | With the computer's own voices: pause, stop, speed, and each word highlighted as it's read |
| 💬 **Ask about it** | "What should I do?", "When is it?", "Translate it"… answered by a local AI model, only from what the sign says |
| 🇨🇦 **Bilingual interface** | The whole app in English or French; answers come back in the interface language |
| ♿ **Accessible** | Bigger text buttons, keyboard navigation, screen-reader labels |

---

## 🚀 Quick start

> 💡 **First time?** Read the setup for your computer once. After that, starting the app is one command.

### 🍎 On this Mac: Docker

Tesseract is installed *inside* Docker, so nothing else is needed except Ollama.

**Terminal 1**: start the AI model and leave it open:
```bash
~/.local/ollama/ollama serve
```
> If it says `address already in use`, it's already running. That's fine.

**Terminal 2**: start the app:
```bash
cd /Users/saadturzo/CanAI_Team_E/backend
docker compose up --build
```

Then open **http://localhost:5500** in Chrome. Press <kbd>Ctrl</kbd>+<kbd>C</kbd> to stop.

### 🪟 On Windows: one command, no Docker

**1. Install once**

| install | where | important |
|---|---|---|
| **Python 3.11+** | [python.org](https://www.python.org/downloads/) | tick **Add python.exe to PATH** |
| **Tesseract** | [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) | tick **French** under *Additional language data* |
| **Ollama** | [ollama.com/download](https://ollama.com/download) | starts by itself after installing |
| **French voice** *(for read aloud)* | Settings → Time & language → Speech → Add voices | French (Canada) |

**2. Set up the project once** (VS Code terminal):
```powershell
git clone https://github.com/rudramistry-ssc/CanAI_Team_E.git
cd CanAI_Team_E
git switch tester/full-integration
ollama pull llama3.2:3b
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

**3. Run it, every time:**
```powershell
.venv\Scripts\python run.py
```

`run.py` checks every part, starts everything, and opens the browser:

```
Checking setup
  [ OK ] Python 3.13 with all packages
  [ OK ] Tesseract OCR 5.x with English + French
  [ OK ] Language model llama3.2:3b
  [ OK ] Speech engine: windows-sapi
  [ OK ] Ports 9000, 8000, 5500 are free

Starting
  [ OK ] AI service  http://127.0.0.1:9000
  [ OK ] Backend  http://127.0.0.1:8000
  [ OK ] Frontend  http://127.0.0.1:5500

Lumen is running:  http://localhost:5500
```
*(Example of a fully installed setup.)* If something is missing it prints `[FAIL]` with the fix, and still starts the rest. `run.py --check` only runs the checks.

<details>
<summary><b>🍎 Mac without Docker</b></summary>

Same as Windows, with Mac commands. You need Tesseract installed (`brew install tesseract tesseract-lang`). On **macOS 14 or older** Homebrew has no ready-made package and compiles ~20 libraries (an hour or more), so Docker is easier there.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```
</details>

> 🛟 **Presentation fallback:** if anything breaks live, open **http://localhost:5500/?demo**. It runs entirely in the browser with answers that match the 3 sample photos.

---

## 🧠 How it works

Three small programs work together. **The browser only talks to the backend; the backend only talks to the AI service.**

```
   🖥️  BROWSER                 🗄️  BACKEND                 🤖  AI SERVICE               🧰  ON THIS COMPUTER
   frontend/  :5500            backend/  :8000             ai-service/  :9000
 ┌─────────────────┐  HTTP   ┌──────────────────┐ HTTP  ┌───────────────────┐      ┌─────────────────────┐
 │ photo upload    │ ──────▶ │ sessions         │ ────▶ │ /v1/ocr           │ ───▶ │ Tesseract  eng+fra  │
 │ editable text   │         │ upload checks    │       │ /v1/reply         │ ───▶ │ Ollama  llama3.2:3b │
 │ read aloud      │ ◀────── │ chat history     │ ◀──── │ /v1/tts           │ ───▶ │ OS voices           │
 │ chat            │         │ SQLite + audio   │       │ /v1/stt  (501)    │      └─────────────────────┘
 └─────────────────┘         └──────────────────┘       └───────────────────┘
   HTML · CSS · JS             FastAPI · SQLite           FastAPI + ocr/ package
```

### 📷 When you add a photo

```
Browser ──POST /v1/sessions──────────────▶ Backend                          (first time only)
Browser ──POST /v1/sessions/{id}/images──▶ Backend ──/v1/ocr──▶ AI service ──▶ Tesseract
                                           Backend ──/v1/tts──▶ AI service ──▶ OS voice
Browser ◀── { text, language, confidence, audio_url } ── Backend (text saved in the session)
```

1. The backend checks it's an image under 15 MB.
2. The AI service runs the team's OCR package. If the photo is hard (dark, blurry, small text), it retries on cleaned-up copies.
3. You get the **text**, the **language** (`en` / `fr` / `mixed`) and a **confidence** score.

### 🔊 When you press Read aloud

The **browser** reads the text with the computer's voices (Web Speech API) and highlights each word. No server is needed, so it works offline. The language dropdown picks the voice.

### 💬 When you ask a question

```
Browser ──POST /v1/sessions/{id}/chat──▶ Backend ──/v1/reply──▶ AI service ──▶ Ollama
          message + language +           + last 10 turns         + rules for the model
          YOUR EDITED TEXT
Browser ◀────────────── { reply } ─────── Backend (turn saved in history)
```

The model is told to answer **only from the sign**, **in the requested language**, in **1–3 short sentences** (they're read aloud), **never invent numbers or dates**, and to treat the sign's text as data, not instructions.

---

## 🧩 What each part does

### 🖥️ `frontend/`: what you see
Plain HTML, CSS and JavaScript, so there's nothing to build or install.

| file | job |
|---|---|
| `index.html` · `styles.css` | the page and its look (dark, Neon-style) |
| `intro.js` · `intro.css` | the landing page with the scan animation |
| `app.js` | everything on the page: upload, text box, player, chat |
| `api.js` | **every call to the backend** in one place, plus the fake answers for demo mode |
| `speech.js` | read aloud and the mic, using the browser's own speech features |
| `i18n.js` | every piece of text in English and French |
| `config.js` | settings: backend address, demo mode, app name |

### 🗄️ `backend/`: the organiser
FastAPI. It does no AI itself: it keeps track of things and asks the AI service.

| file | job |
|---|---|
| `routers/sessions.py` | create and read a session |
| `routers/images.py` | photo upload → OCR → audio → save |
| `routers/chat.py` | question → answer, with history |
| `services/ai_client.py` | **the only file that talks to the AI service** |
| `services/session_service.py` | SQLite: sessions and chat messages |
| `services/storage_service.py` | saves and serves the audio files |

### 🤖 `ai-service/`: the brains
FastAPI. One route per AI job.

| file | job |
|---|---|
| `app.py` | the routes: `/v1/ocr`, `/v1/reply`, `/v1/tts`, `/v1/stt`, `/healthz` |
| `llm.py` | talks to the local model (Ollama, or vLLM: anything OpenAI-compatible) |
| `tts.py` | speech with built-in voices: macOS `say`, Windows System.Speech, Linux `espeak-ng` |

### 🔤 `ocr/`: reading the photo
The team's `signspeak_ocr` package: Tesseract plus image quality checks, clean-up retries, language detection and confidence. Includes a 20-image benchmark in `ocr/eval/`.

### ▶️ `run.py`: the starter
Checks the setup, starts all three programs on ports 9000 / 8000 / 5500, waits until each one answers, opens the browser, and stops everything on <kbd>Ctrl</kbd>+<kbd>C</kbd>.

---

## 🔗 How the parts are connected

This branch (`tester/full-integration`) brings every team branch together and adds the missing pieces.

| branch | what it brought |
|---|---|
| `dev-sd-backend` | the backend: sessions, uploads, chat, SQLite, Docker |
| `feature/signspeak-ocr` | the OCR package and benchmark |
| `chore/connect-backend-to-ocr` | OCR web wrapper, backend → OCR connection, TTS on/off switch |
| `feature/frontend` | the Lumen web app |
| **`tester/full-integration`** | **everything above, plus what was needed to make it work together** ↓ |

**What was added to connect them:**

| gap | fix |
|---|---|
| The frontend called `/api/...` routes that didn't exist | `api.js` now uses the backend's real `/v1/...` routes and creates a backend session per UI session |
| The backend needed an AI service with OCR, chat and speech, but only OCR existed | new `ai-service/` with all four routes |
| Chat had no AI model | Ollama with `llama3.2:3b`, running locally |
| Chat ignored the user's corrected text and the answer language | the backend accepts `context` and `language` on chat and passes them on |
| No confidence shown | the backend now forwards OCR confidence |
| The backend could only store MP3 audio | it now stores and serves WAV too (built-in voices make WAV) |
| No easy way to start it all | `run.py` (no Docker) and an updated `docker-compose.yml` (everything in Docker) |
| Errors just said "failed" | the real reason is shown, e.g. *model not downloaded* |

📄 The exact requests and responses: [`frontend/API_CONTRACT.md`](frontend/API_CONTRACT.md) (browser ↔ backend) and [`backend/README.md`](backend/README.md) (backend ↔ AI service).

---

## 🎯 Using the app

1. Click **Open app** on the landing page.
2. Add a photo, or click a sample: **English notice**, **French notice**, **Bilingual sign**.
3. Check the text. Fix any mistakes; **the chat uses your fixed version**.
4. Press **Read aloud**.
5. Ask a question, or tap **Summarize it**, **What should I do?**, **When is it?**, **Translate it**.

> ❓ **Does the language dropdown translate the text?**
> **No.** It only tells the app what language the text is *already* in, so read aloud picks the right voice. Fix it if the guess is wrong.
>
> 🌐 **To translate**, ask in the chat ("Translate it"). Answers come in the **interface language**: the **EN / FR** buttons in the top bar. With EN selected, a French sign is explained in English, and the other way round.

---

## ✅ What works today

*Tested 29 Oct 2026 on a MacBook (Apple Silicon, macOS 14.6, Chrome), with Docker and with `run.py`.*

| feature | status | notes |
|---|:---:|---|
| Upload: drag & drop, file picker, samples | ✅ | tested in the browser |
| Upload: paste, phone camera | 🟡 | code is there, not tested |
| OCR English + French | ✅ | team benchmark through the real API: **20/20 images, 0.79 % character error rate**, 0.4–1.4 s each |
| Confidence score | ✅ | ~94–96 % on the samples |
| Language detection | 🟡 | right for EN and FR; **short bilingual signs come back as English**. Number-only images: no language (shown as English) |
| Edit text → chat uses it | ✅ | tested |
| Read aloud in the browser | 🟡 | voices found and the player starts; **not listened to** in testing |
| Chat in English and French | ✅ | answers only from the sign; says so when the answer isn't there |
| Chat history (follow-ups) | ✅ | last 10 turns |
| Backend audio files | ✅ | macOS and Docker tested · **Windows code not tested** |
| Mic (voice questions) | 🟡 | browser speech recognition (Chrome/Edge, needs internet); not tested |
| Offline speech-to-text | ❌ | not built (`/v1/stt` returns 501) |
| Demo mode `?demo` | ✅ | tested |
| Docker | ✅ | fully tested on Mac |
| `run.py` on Mac | ✅ | all parts except OCR (Tesseract not installed on the test Mac; OCR tested in Docker, same code) |
| `run.py` on Windows | ❓ | written for Windows, **not run on Windows yet** |

**⏱️ Speed:** OCR ~0.5–1.5 s. Chat: 10–20 s for the first answer (model loading), then ~1–9 s on an Apple Silicon Mac. A laptop without a GPU will be slower. Use `LLM_MODEL=llama3.2:1b` for speed, or vLLM on the HPC node.

---

## 🛠️ What's left to do

### Before the presentation
- [ ] **Run it on the Windows laptop** from scratch, following the Quick start
- [ ] **Listen to Read aloud** in English and French, and install a French voice if needed
- [ ] Try the **mic** in Chrome or Edge
- [ ] Try a few **real phone photos** of real signs
- [ ] Push `tester/full-integration` and decide whether to merge it into `main`

### Known gaps
| gap | why it matters | idea |
|---|---|---|
| 🎤 **Offline voice input** | the mic uses an online service (Chrome/Edge) | add Whisper (`faster-whisper`) to `/v1/stt`; the backend already accepts an `audio` field |
| 🏷️ **Banner headings missed** | white text on coloured bars ("NOTICE", "AVIS") isn't read | add an inverted-image pass in the OCR clean-up step |
| 🌐 **Short bilingual signs → "English"** | the mixed voice isn't picked automatically | tune the threshold in `ocr/src/signspeak_ocr/language.py` |
| 🔊 **No French voice installed** | French gets read with an English voice | the page could fall back to the backend's audio file (`audio_url`) |
| 🧪 **No automated tests** | changes can break things silently | turn the end-to-end checks used here into `pytest` tests |
| ⚡ **Slow chat on CPU laptops** | waiting time in the demo | smaller model, or vLLM on the HPC GPU node (`LLM_BASE_URL`) |
| 🔒 **Open to any website (CORS `*`), no login** | fine on one computer; not for the internet | restrict `CORS_ORIGINS` and add auth before hosting it anywhere |

---

## 🩺 Troubleshooting

| you see | fix |
|---|---|
| `python: command not found` (Mac) | use `python3`, or `.venv/bin/python` |
| **Backend offline** in the top bar | start the app (`run.py` or Docker), or use `?demo` |
| *…Tesseract was not found…* | install Tesseract (Quick start). Windows, unusual folder: set `SIGNSPEAK_TESSERACT_CMD` to the full path of `tesseract.exe` |
| *…language data missing: fra…* | Windows: rerun the Tesseract installer and tick French · Mac: `brew install tesseract-lang` |
| *…Cannot reach the language model…* | start Ollama: open the app, or `ollama serve` |
| *…model 'llama3.2:3b' not found…* | `ollama pull llama3.2:3b` |
| `[FAIL] Ports already in use` | the app is already running somewhere: stop it with <kbd>Ctrl</kbd>+<kbd>C</kbd> there, or `docker compose down` |
| *No readable text found* | sharper, brighter photo, or type the text into the box |
| French sounds English | add a French voice in the OS settings, reload the page |
| Docker: chat fails | start Ollama **before** `docker compose up` |

**Health checks:** http://localhost:8000/healthz (backend) · http://localhost:9000/healthz (AI service, `run.py` only: shows OCR / model / voice status) · http://localhost:8000/docs (try every route by hand)

---

## 📁 Project layout

```
CanAI_Team_E/
├── run.py                  ▶️  start everything (no Docker)
├── requirements.txt        📦 all Python packages, one install
├── frontend/               🖥️  the web app
│   ├── index.html · styles.css · intro.css
│   ├── app.js · api.js · speech.js · intro.js
│   ├── i18n.js · config.js · samples.js
│   ├── API_CONTRACT.md     📄 browser ↔ backend
│   └── tools/build_single.py   one-file version → dist/lumen.html
├── backend/                🗄️  the organiser
│   ├── main.py · config.py · db.py
│   ├── routers/            sessions · images · chat
│   ├── services/           ai_client · session_service · storage_service
│   ├── models/schemas.py
│   └── docker-compose.yml  🐳 everything in Docker
├── ai-service/             🤖 the brains
│   ├── app.py · llm.py · tts.py · config.py
│   └── Dockerfile
└── ocr/                    🔤 reading photos
    ├── src/signspeak_ocr/  the OCR package
    ├── service.py          earlier OCR-only web wrapper
    └── eval/               20-image benchmark
```

---

## ⚙️ Settings

All optional. Set them before `run.py` or `docker compose up`.

| variable | default | what it does |
|---|---|---|
| `LLM_MODEL` | `llama3.2:3b` | which model answers questions |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama, or vLLM on the HPC node |
| `TTS_ENABLED` | `true` | backend makes audio files; `false` is a bit faster |
| `SIGNSPEAK_TESSERACT_CMD` | auto | path to Tesseract if it isn't found |

Frontend settings (backend address, demo mode, app name) are in [`frontend/config.js`](frontend/config.js).

**More detail:** [frontend](frontend/README.md) · [API contract](frontend/API_CONTRACT.md) · [backend](backend/README.md) · [AI service](ai-service/README.md) · [OCR](ocr/README.md)

---

<div align="center">

Made by **Team E** at **CanAI Garage 2026** 🍁

</div>

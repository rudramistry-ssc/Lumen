# AI service

The part that does the actual AI work. Only the backend talks to it (`AI_BASE_URL`, port 9000 when started by `run.py`). It is one small FastAPI app:

| file        | what it does                                                        |
|-------------|---------------------------------------------------------------------|
| `app.py`    | the routes below                                                    |
| `llm.py`    | chat answers from a local model (Ollama, or any OpenAI-compatible server such as vLLM) |
| `tts.py`    | text to speech with the voices built into the computer              |
| `config.py` | settings, all overridable with environment variables                |

## Routes

| Method | Path        | Request                                         | Response | Status |
|--------|-------------|-------------------------------------------------|----------|--------|
| POST   | `/v1/ocr`   | multipart `file` (image)                        | `{ "text", "language", "confidence" }` | ✅ works |
| POST   | `/v1/reply` | JSON `{ "message", "context", "history", "language" }` | `{ "reply" }` | ✅ works (needs Ollama) |
| POST   | `/v1/tts`   | JSON `{ "text", "language", "voice"? }`         | WAV audio | ✅ works |
| POST   | `/v1/stt`   | multipart `file` (audio)                        | 501 Not Implemented | ❌ not built |
| GET    | `/healthz`  |                                                 | which parts work on this computer | ✅ |

`language` is `"en"`, `"fr"` or `"mixed"` from OCR (`""` if it can't tell). For `/v1/reply` it is the language the answer should be in.

## How each part works

**OCR** uses the team's `signspeak_ocr` package (`../ocr`), which runs Tesseract with English + French. With `OCR_PREPROCESS=true` (default) a hard photo gets up to three extra passes on cleaned-up copies (OpenCV). `confidence` is Tesseract's mean word confidence, weighted by text length, from 0 to 1. This is the same OCR call as the team's `ocr/service.py`, plus the confidence.

**Chat** sends the sign's text, the last 10 turns and the question to the model with instructions to answer only from the sign, in the requested language, in one to three plain sentences (they are read aloud), and not to invent numbers or dates. The sign text is marked as data, not instructions, so text on a sign can't take over the model.

**Text to speech** writes a WAV file with the computer's own voices, so it works offline:
- macOS: `say` (Samantha for English, Amélie for French, if installed)
- Windows: the built-in System.Speech engine through PowerShell. A French voice is used if one is installed (Settings → Time & language → Speech → Add voices).
- Linux: `espeak-ng`, if installed

"mixed" text is read with the English voice. The frontend does its own read-aloud in the browser, with word highlighting, so this audio is only used through the backend's `audio_url`.

**Speech to text** is not built. The frontend's mic button uses the browser's speech recognition instead (Chrome/Edge, needs internet). For offline voice input, add Whisper (for example `faster-whisper`) to `/v1/stt`.

## Settings

| env var              | default                      | what it is |
|----------------------|------------------------------|------------|
| `LLM_BASE_URL`       | `http://localhost:11434/v1`  | OpenAI-compatible API. Ollama by default; for vLLM on the HPC node use `http://<node>:<port>/v1` |
| `LLM_MODEL`          | `llama3.2:3b`                | model name on that server |
| `LLM_API_KEY`        | `ollama`                     | Ollama ignores it; set it if your vLLM server needs one |
| `LLM_TIMEOUT_SECONDS`| `120`                        | |
| `LLM_MAX_TOKENS`     | `300`                        | |
| `OCR_PREPROCESS`     | `true`                       | extra OCR passes on hard photos |

## Run it on its own

From the repository root, with the virtual environment active:

```bash
cd ai-service
uvicorn app:app --port 9000
```

Then http://localhost:9000/healthz shows what works, and http://localhost:9000/docs lets you try each route.

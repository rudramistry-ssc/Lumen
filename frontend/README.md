# Lumen frontend · CanAI Garage, Team E

The user interface for our accessibility tool: **photo → text → read aloud → ask questions**, in English or French.

Plain HTML, CSS and JavaScript. No build step, no npm, nothing to install. The project name is set in one place: `APP_NAME` in `config.js`.

## Run the app

The UI is served by the backend. From the repository root, start the full stack:

```bash
docker compose up --build
```

Open **http://localhost:8000**. The API serves this folder, so the UI and the
API share one origin — no CORS, and `API_BASE_URL` stays `""`.

Stop it with `Ctrl+C`, or `docker compose down`.

## Run the UI alone

For UI-only work you only need Python 3, to run a small local web server.

```bash
cd frontend
python3 -m http.server 5500
```

Then open **http://localhost:5500** in Chrome or Edge. Set
`API_BASE_URL: "http://127.0.0.1:8000"` to reach a running API, or
`USE_MOCK: true` to work with fake responses and no backend at all.

To stop the server, press `Ctrl+C` in the terminal.

> **Mac users:** use `python3`, not `python`. On most Macs, `python` doesn't exist and the command fails with "command not found".
>
> **Windows users:** use `python` or `py`: `py -m http.server 5500`.

**Without a server:** you can also double-click `index.html`. Most of the app works, but voice input may be blocked by the browser.

### Port already in use?

If you see `Address already in use`, either a server is already running (just open the link) or something else is using port 5500. Use another port: `python3 -m http.server 5501`.

## Current status

The integration branch adds an opt-in vision-first upload path. See
[backend setup](../backend/README.md#vision-first-integration-milestone).
It displays selected Qwen text, review warnings, separately labelled visual
interpretations, and expandable processing metadata. Document read-aloud uses
Piper WAV, and typed chat uses saved document context/history with guardrails.
Blocked answers are not spoken; a speech failure leaves the text answer visible.
Selected text is read-only; WAV playback supports pause, stop and speed but no
word highlighting. Microphone input uses local Whisper, puts the transcript in
the question box for review/correction, and waits for Send before asking Qwen.
There is no cloud recognition fallback. FFmpeg and Whisper must be provisioned
on the backend; see the backend setup above. The existing Docker demo
below describes the preserved legacy OCR-only demo (`cd backend` before Compose).
For the full integrated app, run Compose at the repository root; see
[the launch guide](../README.md).

The UI is wired to the real backend and uses it by default (`USE_MOCK: false`,
`API_BASE_URL: ""`). What works today:

The table below describes the legacy OCR-service Docker demo; the opt-in
document mode above also connects Piper read-aloud and guarded typed chat.

| Feature | Status |
|---|---|
| Backend status pill | ✅ `GET /healthz` |
| Photo → text | ✅ `POST /v1/sessions`, then `POST /v1/sessions/{id}/images` |
| Read aloud | ✅ in the browser, no backend call |
| Ask questions | ⚠️ wired to `POST /v1/sessions/{id}/chat`, but the AI service has no `/v1/reply` yet, so it answers `502` |
| Voice input | ✅ recorded in the browser and uploaded to `POST /v1/sessions/{id}/audio`; the clip plays back in the chat panel |
| Voice → text | ⚠️ the backend stores the clip but does not transcribe it; the AI service needs `/v1/stt` |

To work on the UI without a backend, set `USE_MOCK: true` in `config.js`; the
top bar then says **Demo mode**.

See `API_CONTRACT.md` for the exact routes, fields and error codes.

## Trying it

1. Open the app. The landing page appears first; click **Try the demo** or **Open app**.
2. Under the photo box, click a sample: **English notice**, **French notice** or **Bilingual sign** — or drop your own photo.
3. Check the extracted text (you can edit it), then press **Read aloud**.
4. Ask a question, or tap a chip like *What should I do?* or *Translate it*.

In demo mode (`USE_MOCK: true`) the answers are fake and match the three sample
photos, so the demo looks real without a backend. For your own photos in demo
mode, a file name containing `fr`, `en` or `mix` picks the fake language;
otherwise it cycles EN → FR → mixed. A name containing `fail` shows the error
state.

## Settings (`config.js`)

| setting         | what it does                                                        |
|-----------------|---------------------------------------------------------------------|
| `APP_NAME`      | name shown everywhere in the UI                                     |
| `SHOW_INTRO`    | `true` shows the landing page first; `false` opens straight to the app |
| `USE_MOCK`      | `true` = fake responses, `false` = call the real backend            |
| `API_BASE_URL`  | backend address; `""` means same origin (the normal setup)         |
| `MAX_IMAGE_MB`  | biggest photo the app will send                                     |

## One-file version

```bash
cd frontend
python3 tools/build_single.py
```

This bundles everything into `dist/lumen.html`, a single file you can send to anyone and open by double-clicking. `dist/` is not committed; rebuild it when you need it.

## Files

| file                      | what it does                                                   |
|---------------------------|----------------------------------------------------------------|
| `index.html`              | page structure                                                 |
| `styles.css`              | app styling (dark, Neon-style)                                 |
| `intro.css` / `intro.js`  | landing page                                                   |
| `config.js`               | settings: backend switch, backend URL, app name                |
| `i18n.js`                 | every piece of UI text, in English and French                  |
| `api.js`                  | all backend calls, plus the fake responses                     |
| `samples.js`              | the 3 sample photos, embedded so they work offline (`samples/` has the originals) |
| `speech.js`               | read aloud (text-to-speech) and voice input (speech-to-text)   |
| `app.js`                  | ties it together: upload, text panel, player, chat             |
| `tools/build_single.py`   | builds the one-file version                                    |
| `API_CONTRACT.md`         | the backend routes this UI calls, with fields and errors        |

## Features

- Upload by drag and drop, file picker, or paste (Ctrl+V). On phones, opens the camera.
- Extracted text is editable, so users can fix OCR mistakes before listening.
- Detected language shown and changeable: English, French, or mixed.
- Sample photos for a reliable live demo, and progress steps while a photo is processed.
- Read aloud with pause, stop and speed, and word-by-word highlighting. Mixed text uses an English and a French voice per sentence.
- Copy button for the extracted text.
- One-tap questions: Summarize, What should I do?, When is it?, Translate.
- Answers come back in the interface language, so an English speaker can understand a French sign and the other way round.
- Chat with session history. Every reply has a listen button, and replies can be read aloud automatically.
- Mic button for voice questions.
- Interface in English or French, text size buttons, keyboard accessible, screen reader friendly.

## Known limits

- **Read aloud uses the voices installed on the computer.** Chrome and Edge also list cloud voices; the app prefers local ones, so English works offline. If no local voice exists for the language, the text may stay silent and the UI says so. On Windows: Settings → Time & language → Language & region → Add a language → French (Canada) → check **Speech**. On macOS: System Settings → Accessibility → Spoken Content → System voice → Manage voices.
- **Word highlighting** needs the computer's built-in voices. Some online voices in Chrome don't report word positions, so the text shows without highlighting.
- **Voice input records offline but does not transcribe yet.** The mic button records with `MediaRecorder` (no cloud call) and uploads the clip to `POST /v1/sessions/{id}/audio`; the backend stores it and the UI plays it back. Turning the clip into text needs `/v1/stt` in the AI service. Browsers without `MediaRecorder` fall back to the online speech API; if neither is available, the UI shows a message instead.
- **Fonts** load from Google Fonts when online and fall back to system fonts offline.

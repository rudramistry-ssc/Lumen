# Lumen frontend · CanAI Garage, Team E

The user interface for our accessibility tool: **photo → text → read aloud → ask questions**, in English or French.

Plain HTML, CSS and JavaScript. No build step, no npm, nothing to install. The project name is set in one place: `APP_NAME` in `config.js`.

## Quick start

You only need Python 3, to run a small local web server.

```bash
cd frontend
python3 -m http.server 5500
```

Then open **http://localhost:5500** in Chrome or Edge.

To stop the server, press `Ctrl+C` in the terminal.

> **Mac users:** use `python3`, not `python`. On most Macs, `python` doesn't exist and the command fails with "command not found".
>
> **Windows users:** use `python` or `py`: `py -m http.server 5500`.

**Without a server:** you can also double-click `index.html`. Most of the app works, but voice input may be blocked by the browser.

### Port already in use?

If you see `Address already in use`, either a server is already running (just open the link) or something else is using port 5500. Use another port: `python3 -m http.server 5501`.

## Current status: demo mode

**The frontend is not connected to the backend yet.** It runs in demo mode with fake responses, so you can work on the UI without a backend. The pill in the top bar says **Demo mode**.

Before it can connect, two things have to happen:

1. **The routes need to match.** The frontend calls `/api/health`, `/api/extract` and `/api/chat` (see `API_CONTRACT.md`). The backend (`backend/`) currently has `/v1/sessions`, `/v1/sessions/{id}/images` and `/v1/sessions/{id}/chat`. One side needs to change. All frontend calls live in `api.js`.
2. **Switch off demo mode** in `config.js`:
   ```js
   USE_MOCK: false,
   API_BASE_URL: "http://127.0.0.1:8000",   // or "" if FastAPI serves this folder
   ```

Then the top bar shows **Backend connected** or **Backend offline**.

## Trying the demo

1. Open the app. The landing page appears first; click **Try the demo** or **Open app**.
2. Under the photo box, click a sample: **English notice**, **French notice** or **Bilingual sign**.
3. Check the extracted text (you can edit it), then press **Read aloud**.
4. Ask a question, or tap a chip like *What should I do?* or *Translate it*.

The fake answers match the three sample photos, so the demo looks real. For your own photos in demo mode, a file name containing `fr`, `en` or `mix` picks the fake language; otherwise it cycles EN → FR → mixed. A name containing `fail` shows the error state.

## Settings (`config.js`)

| setting         | what it does                                                        |
|-----------------|---------------------------------------------------------------------|
| `APP_NAME`      | name shown everywhere in the UI                                     |
| `SHOW_INTRO`    | `true` shows the landing page first; `false` opens straight to the app |
| `USE_MOCK`      | `true` = fake responses, `false` = call the real backend            |
| `API_BASE_URL`  | backend address; `""` means same origin                             |
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
| `config.js`               | settings: demo mode switch, backend URL, app name              |
| `i18n.js`                 | every piece of UI text, in English and French                  |
| `api.js`                  | all backend calls, plus the fake responses                     |
| `samples.js`              | the 3 sample photos, embedded so they work offline (`samples/` has the originals) |
| `speech.js`               | read aloud (text-to-speech) and voice input (speech-to-text)   |
| `app.js`                  | ties it together: upload, text panel, player, chat             |
| `tools/build_single.py`   | builds the one-file version                                    |
| `API_CONTRACT.md`         | what the backend needs to send and receive                     |

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

- **Read aloud uses the voices installed on the computer.** If no French voice is installed, a default voice is used and the UI says so. On Windows: Settings → Time & language → Speech → Add voices → French (Canada). On macOS: System Settings → Accessibility → Spoken Content → System voice → Manage voices.
- **Word highlighting** needs the computer's built-in voices. Some online voices in Chrome don't report word positions, so the text shows without highlighting.
- **Voice input isn't offline.** Chrome and Edge send audio to an online service. For a fully offline app, the backend needs a Whisper `/api/transcribe` route (see `API_CONTRACT.md`). Firefox has no voice input; the UI shows a message instead.
- **Fonts** load from Google Fonts when online and fall back to system fonts offline.

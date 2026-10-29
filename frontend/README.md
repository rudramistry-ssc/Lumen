# Lumen frontend · CanAI Garage, Team E

The user interface for our accessibility tool: **photo → text → read aloud → ask questions**, in English or French. The name is set in one place: `APP_NAME` in `config.js`.

Plain HTML, CSS and JavaScript. No build step, no npm. Works offline (fonts fall back to system fonts without internet).

## Launch screen

The app opens on a landing page (Neon-style: black, scan-bar hero, numbered sections). **Try the demo** or **Open app** opens the app; the logo in the app's top-left goes back. To skip it, set `SHOW_INTRO: false` in `config.js`. Styles: `intro.css`, animation: `intro.js`.

## One-file version

`python tools/build_single.py` bundles everything into `dist/lumen.html`, a single file you can send to anyone and open by double-clicking.

## Run it

**Option 1: just open it.** Double-click `index.html`. It runs in demo mode with fake responses.

**Option 2: a local server** (recommended, needed for the mic in some browsers):
```bash
cd frontend
python -m http.server 5500
```
Then open http://localhost:5500

## Demo mode vs real backend

In `config.js`:
```js
USE_MOCK: true,     // fake responses, no backend needed
API_BASE_URL: "",   // "" if FastAPI serves this folder, else e.g. "http://127.0.0.1:8000"
```
Set `USE_MOCK: false` once the backend has the routes in `API_CONTRACT.md`. The pill in the top bar shows **Demo mode**, **Backend connected** or **Backend offline**.

**Demo tip:** use the three sample buttons under the photo box (English notice, French notice, bilingual sign). In demo mode the fake text and answers match those photos, so the demo looks real. Try the question chips ("What should I do?", "Translate it"…) on each one.

For your own photos in demo mode, a file name containing `fr`, `en` or `mix` picks the fake language; otherwise it cycles EN → FR → mixed. A name containing `fail` shows the error state.

## Files

| file             | what it does                                                   |
|------------------|----------------------------------------------------------------|
| `index.html`     | page structure                                                 |
| `styles.css`     | app styling (dark, Neon-style)                                 |
| `intro.css` / `intro.js` | landing page                                          |
| `config.js`      | demo mode switch and backend URL                               |
| `i18n.js`        | every piece of UI text, in English and French                  |
| `api.js`         | all backend calls, plus the fake responses                     |
| `samples.js`     | the 3 sample photos, embedded so they work offline (`samples/` has the originals) |
| `speech.js`      | read aloud (text-to-speech) and voice input (speech-to-text)   |
| `app.js`         | ties it together: upload, text panel, player, chat             |
| `API_CONTRACT.md`| what the backend needs to send and receive                     |

## Features

- Upload by drag and drop, file picker, or paste (Ctrl+V). On phones, opens the camera.
- Extracted text is editable, so users can fix OCR mistakes before listening (from the hackathon brief).
- Detected language shown and changeable: English, French, or mixed.
- Sample photos for a reliable live demo.
- Progress steps while the photo is processed.
- Read aloud with pause, stop and speed, and **word-by-word highlighting** as it reads. Mixed text uses an English and a French voice per sentence.
- Copy button for the extracted text.
- One-tap questions: Summarize, What should I do?, When is it?, Translate.
- Answers come back in the interface language, so an English speaker can understand a French sign and the other way round.
- Chat with session history. Every reply has a listen button, and replies can be read aloud automatically.
- Mic button for voice questions.
- Interface in English or French, text size buttons, keyboard accessible, screen reader friendly.

## Known limits

- Word highlighting needs the computer's built-in voices (Windows/macOS voices work). Some online voices in Chrome don't report word positions, so the text shows without highlighting.

- **Read aloud uses the voices installed on the computer.** If there's no French voice installed, a default voice is used and the UI says so. On Windows: Settings → Time & language → Speech → Add voices → French (Canada).
- **Voice input isn't offline.** Chrome and Edge send audio to an online service. For a fully offline app, the backend needs a Whisper `/api/transcribe` route (see `API_CONTRACT.md`). Firefox has no voice input; the UI shows a message instead.

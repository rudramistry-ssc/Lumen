# Lumen frontend · CanAI Garage, Team E

The user interface for our accessibility tool: **photo → text → read aloud → ask questions**, in English or French.

Plain HTML, CSS and JavaScript. No build step, no npm, nothing to install. The project name is set in one place: `APP_NAME` in `config.js`.

## Quick start

**To run the whole app (frontend + backend + AI), use `python run.py` from the repository root.** See the root [README](../README.md). It starts this frontend for you.

To run only the frontend (for UI work):

```bash
cd frontend
python3 -m http.server 5500
```

Then open **http://localhost:5500/?demo** in Chrome or Edge. `?demo` gives fake answers, so no backend is needed. Without `?demo` the app calls the real backend at `http://127.0.0.1:8000`, and the top bar shows **Backend offline** if it isn't running.

> **Mac:** use `python3`, not `python` (`python` usually doesn't exist on a Mac).
> **Windows:** use `py -m http.server 5500`.

You can also double-click `index.html`. Most of the app works, but voice input may be blocked by the browser.

If you see `Address already in use`, the app is probably already running (just open the link), or use another port: `python3 -m http.server 5501`.

## Real backend vs demo mode

| address                          | what happens                                                    | top bar |
|----------------------------------|-----------------------------------------------------------------|---------|
| `http://localhost:5500`          | real OCR and real AI answers through the backend                | **Backend connected** / **Backend offline** |
| `http://localhost:5500/?demo`    | fake answers that match the 3 sample photos, no backend needed  | (hidden) |

`?demo` is a safe fallback for a live presentation: if anything on the backend side fails, add `?demo` and keep going. To make demo mode the default, set `USE_MOCK: true` in `config.js`.

When something goes wrong, the error box shows the backend's reason in brackets, e.g. *(502: AI service error (503): Cannot reach the language model …)*. If the backend can't be reached at all, it says how to start it.

## Trying it

1. Open the app. The landing page appears first; click **Try the demo** or **Open app**.
2. Under the photo box, click a sample: **English notice**, **French notice** or **Bilingual sign**, or add your own photo.
3. Check the extracted text (you can fix mistakes; the chat uses your fixed version), then press **Read aloud**.
4. Ask a question, or tap a chip like *What should I do?* or *Translate it*. Answers come back in the interface language (EN/FR buttons in the top bar).

In demo mode, for your own photos, a file name containing `fr`, `en` or `mix` picks the fake language; otherwise it cycles EN → FR → mixed. A name containing `fail` shows the error state.

## Settings (`config.js`)

| setting         | what it does                                                        |
|-----------------|---------------------------------------------------------------------|
| `APP_NAME`      | name shown everywhere in the UI                                     |
| `SHOW_INTRO`    | `true` shows the landing page first; `false` opens straight to the app |
| `USE_MOCK`      | `true` = fake responses, `false` = real backend (default; `?demo` in the address also turns on fake responses) |
| `API_BASE_URL`  | backend address, default `http://127.0.0.1:8000`; `""` means same address as this page |
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
| `api.js`                  | all backend calls (`/v1/...`, see `API_CONTRACT.md`), plus the fake responses |
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
- **Voice input isn't offline.** Chrome and Edge send audio to an online service. For a fully offline app, the AI service's `/v1/stt` needs Whisper (see `API_CONTRACT.md`). Firefox has no voice input; the UI shows a message instead.
- **Fonts** load from Google Fonts when online and fall back to system fonts offline.

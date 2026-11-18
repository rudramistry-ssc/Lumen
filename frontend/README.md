# Lumen frontend

Open http://localhost:8000 after starting the app with `start.ps1` / `start.sh` from the repository root.
Do not open this HTML file directly or run a separate static server.

The original Lumen landing page, styling, bilingual interface and controls are
restored. Click **Open app**, then choose, drop or paste one photo, or choose a
sample. Real extraction starts immediately. The existing text box displays two
sections: extracted text and image summary.

The page uses `POST /api/extract` and `POST /api/chat` on the same server.
The original chat panel displays real follow-up answers from Qwen using the
image and full session history. New session is required for another image.
Editing and copying work with the combined result. Existing read-aloud/speaker
controls use local Kokoro; the microphone records with MediaRecorder and sends
audio only to local Whisper. Click the microphone again to transcribe and send.
Open the app on localhost on the computer running Python to keep speech local.
No browser online recognition service is used. Reset aborts pending browser
requests, recording and playback, and clears the server session.
OCR always uses the real backend. No fake OCR or chat responses are returned.

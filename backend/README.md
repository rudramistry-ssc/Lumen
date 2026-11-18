# Local app API

Runs as the `api` service in Docker (see the repository README); it also serves
the frontend at http://localhost:8000. `provision.py` is the one-time `models`
setup service that downloads and verifies every pinned model file.

`POST /api/extract` accepts multipart field `image` (maximum 10 MB), plus an
optional UUID `session_id` (the frontend supplies a new UUID for each session).
It calls `signspeak_ocr.analyze_image` with bytes, using private model settings
from the environment (set by `compose.yaml`).

Successful responses contain `session_id`, `text`, `summary` and the image's
detected `language` (`en`, `fr`, `mixed`, `none`). Detection shares the OCR request.
The separate `summary_language` field selects the summary's playback voice.
`confidence` contains separate `text`/`summary` integer percentages (or `null`)
and `method: "model_estimate"`. Qwen supplies them in the same image request.
They are self-assessments, not calibrated accuracy measurements. The parser
rejects out-of-range, non-integer and invalid no-text estimates.
The request goes to the internal `qwen` container (llama.cpp), on a GPU when
usable, otherwise on the CPU.

`POST /api/chat` looks up that session, sends its prepared image, original text,
summary, uncertainty notes, edited display text, all completed turns and the
current question to the same Qwen endpoint. Successful answers are appended to
server-owned history. A failed generation does not enter history. One request
per session can run at a time. An image cannot be replaced inside a session.

`DELETE /api/sessions/{session_id}` discards the image and conversation. Sessions
are bounded, in memory and expire after one idle hour; use a single server worker.
No database is needed. Resetting during generation cannot revive the old session.

`POST /api/speech/transcribe` uses CPU Whisper; `POST /api/speech/synthesize` uses
CPU Kokoro. Both load installed local files only. Models are downloaded and verified
once by the `models` setup service into the read-only `/models` volume. No external speech service
is contacted. `GET /api/speech/status` reports whether local assets are installed;
it does not perform inference or validate every model file.
The app's startup lifecycle warms both voice languages before it accepts
requests. Synthesis queues behind an ongoing inference instead of rejecting the
next speaker click. The frontend prepares the complete content, excluding interface
headings, and joins the generated PCM into one WAV before playback. An early click
waits once for completion; generation cannot cause mid-reading pauses. Cached
recordings replay immediately. New session, edits and language changes clear
speech caches. Generation requests remain limited to 120 characters per clip.
The backend caches clips in process memory (24 MiB / 128 clips, ten-minute
validity) so repeated requests can bypass inference and its busy lock. Server
restart clears this cache; it is not persisted. HTML and JavaScript responses
disable browser caching, and the playback script URLs carry a version.
`speech_acceleration.py` builds an optimized copy of the supported Kokoro export
and runs it through OpenVINO on CPU in FP32 precision. Trained weights and voice
settings are unchanged. Unsupported models, missing acceleration dependencies,
or execution failures fall back to the original ONNX engine. Set the environment
variable `LUMEN_SPEECH_ACCELERATION=off` to disable it for troubleshooting.

See [API contract](../frontend/API_CONTRACT.md) for payloads and limits.

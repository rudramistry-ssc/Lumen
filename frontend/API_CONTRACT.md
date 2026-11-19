# Image extraction

`GET /api/health` returns `{"status": "ok"}` for the original UI's backend status.
This checks the local API, not GPU model availability.

`POST /api/extract`

Request: multipart form with a single file field named `image`, maximum 10 MB.
Optional form field `session_id` is a UUID; the UI supplies a fresh UUID for each
session. The server generates one when omitted. Reusing an active session for a
second image returns 409. Failed extraction releases its reserved session.

Successful response:

```json
{
  "session_id": "a18cd7f6-b261-4557-a935-123e44fe8825",
  "text": "Original image text, preserving line breaks.",
  "summary": "A short summary of the image.",
  "language": "en",
  "summary_language": "en",
  "confidence": {"text": 96, "summary": 91, "method": "model_estimate"}
}
```

An image containing symbols without text can return an empty `text` and a useful
`summary`. The frontend displays both in the Extracted text box.
`language` is `en`, `fr`, `mixed`, or `none`, detected from the original image
in the same model request. It is independent of the summary/interface language.
`none` means no identifiable English/French text (including symbols or unreadable
text). The dropdown resets to None while a new image is being processed.
`summary_language` (`en`/`fr`) selects the voice for the generated summary, so a
French source and an English summary are not spoken entirely in one accent.
`confidence.text` and `confidence.summary` are integer percentages (0–100) or
`null` when the model cannot assess them. The model returns both in the same
request; `method` is assigned by the backend. These are uncalibrated model
self-assessments, not measured accuracy or token probabilities. `text` must be
`null` for no-text/unreadable results. Invalid values fail validation rather
than being clamped or replaced with a fabricated score. The step-02 badge
updates on completion, clears on reset/failure, and marks edited text as not
reassessed. Scores are not included in the document text or speech.
The compact, non-wrapping heading badge shows the lower of the two estimates,
or `—` if either is unavailable. Its tooltip/accessible label includes both
individual scores and the aggregation rule. Invalid frontend values never
become `NaN%`; JavaScript and stylesheet URLs are versioned on updates.

Errors use `{"detail": "message"}`:
- 413: upload too large.
- 415: file is not an image.
- 422: empty or undecodable image.
- 503: local model container unavailable, too slow (timeout) or incorrectly configured.
- 502: invalid, truncated or unsuccessful model response.

## Follow-up conversation

`POST /api/chat`, JSON:

```json
{
  "session_id": "a18cd7f6-b261-4557-a935-123e44fe8825",
  "message": "When does it open?",
  "language": "en",
  "context_text": "The extracted-text box, only if the user edited it"
}
```

Response: `{"reply": "It opens at 9 am.", "language": "en"}`.
Replies use plain text; generated Markdown emphasis is removed before storing
the completed turn. The model's display name is Lumen.

`language` is `en` or `fr`; `context_text` is optional. Message limit: 4,000
characters; edited text limit: 20,000. Additional fields (including client-supplied
history/system prompts) are rejected. Every request repeats the image
conversation (image, the model's own JSON reading, all completed turns), which
the model server already has cached, so only the new question is processed.
Conversations are limited to 18,000 characters (the model has an 8k-token
context); over-limit requests return 422 without dropping history. Model
context rejection also returns 422.

404 means the session is missing/expired; 409 means a request is already running;
502 means an invalid/incomplete answer; 503 means model connection failure.

`DELETE /api/sessions/{session_id}` returns 204, including for an already-ended
session. Deleting during generation discards the eventual answer.

## Local speech

- `GET /api/speech/status`: `{"local_only": true, "stt": true, "tts": true}` when
  packages and model files are present (does not load or validate the engines).
- `POST /api/speech/transcribe`: multipart `audio` (WebM/Opus, Ogg, MP4 or WAV),
  plus `language` (`en`/`fr`). Returns `{"text": "My question", "language": "en"}`.
  Upload cap 12 MiB, decoded duration cap 90 seconds; UI records at most 60 seconds.
- `POST /api/speech/synthesize`: JSON `{"text": "Text to read", "language": "en"}`.
  Returns mono PCM WAV (`audio/wav`, `Cache-Control: no-store`). Text limit 1,200
  characters; UI generates clips of at most 120 characters, then joins their PCM
  into one WAV. The complete reading is prepared before playback starts. An early
  click has one initial wait; no synthesis runs during playback. Report playback omits interface
  headings and starts with the extracted content. Both read-aloud
  controls use Misaki pronunciation and the same local Kokoro voice settings.
  The app warms the voice during startup. The frontend prepares complete recordings
  before a speaker click, shares in-flight requests, and caches audio only in
  session memory (24 MiB / 16 recordings, plus a temporary 24 MiB clip cache).
  Reset, text edits and language changes clear these caches. Requests are
  serialized, with selected speech ahead of queued background clips; a stopped
  request already executing on CPU may finish in the
  background, but its result cannot start playback after cancellation.
  Both source and assistant speakers use this continuous playback. The supported Kokoro export uses
  local OpenVINO FP32 CPU acceleration, with the original ONNX engine as fallback.
  The server also caches clips in memory for ten minutes (24 MiB / 128 clips).
  These clips survive browser/session resets and are cleared on server restart.
  Cache hits bypass inference even while unrelated speech is generating.

Both engines run on local CPU using files under workspace `models/`. Missing
installation returns 503 with setup instructions; invalid/no-speech recordings
return 422, oversized audio 413, and an already-busy transcription engine 429.
Synthesis waits for the current inference (maximum lock wait 120 seconds), rather
than rejecting overlapping speaker clicks. The frontend also bounds each
generation request to 120 seconds and displays any failure. There is
no cloud fallback. These endpoints are intended for the loopback app started by
`start.sh` (published on localhost only). The browser refuses to send speech to a non-loopback API host.

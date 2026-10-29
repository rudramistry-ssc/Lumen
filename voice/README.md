# SignSpeak offline voice conversation

Small adapter over the existing `stt/`, `llm/` and `speech/` packages. It does
not run OCR/reconciliation, provision models, start a server per question, play
audio or implement backend routes. Existing modules and their caches are untouched.
Use already-provisioned Whisper Base, Qwen3-VL and English/French Piper voices.

## Run the synthetic demonstration

From the repository root in PowerShell, reuse the Piper environment (no installs):

```powershell
& speech/.venv/Scripts/python.exe voice/demo.py --start-server --scripted-confirmation
```

This explicitly starts **one** existing Qwen `Server` for the entire evaluation,
bound to localhost, and closes only that owned process afterward. An occupied
port is an error; choose `--port 8092` or omit `--start-server` to reuse the
existing server at `SIGNSPEAK_LLM_URL`. When attaching, supply `--llama-pid PID`
for complete combined memory measurement; otherwise Qwen RAM is excluded.
The reusable adapter itself never starts/stops model servers.

Demo sequence: English audio question, typed follow-up, warm English spoken
follow-up, French audio question about the English document, and an absent-fact
question. Questions are generated with Piper in a separate preparation process,
then resampled from 22,050 to 16,000 Hz with evaluation-only linear interpolation.
Fixture preparation is excluded from interaction timing and does not pre-load the
evaluated Piper instance. All resulting WAVs, transcripts, history and measurements
are retained in a new ignored `voice/runtime/demo-*/` directory.

`--scripted-confirmation` explicitly submits the known synthetic question after
logging the raw Whisper hypothesis; **it is not human transcript review** and is
refused with caller-supplied recordings. Omit it for interactive confirmation.
See [measured results and WAVs](RESULTS.md). No human-speech accuracy or manual
listening quality is inferred from this synthetic demonstration.

## Record your actual microphone questions

Run these commands yourself when ready to speak. No service, new package or
PowerShell execution-policy change is required:

```powershell
python voice/record.py --list-devices
python voice/record.py --device 0 --seconds 12
```

Device `0` currently identifies the laptop microphone array; `1` is the JLab
headset. Re-list before choosing; `--device -1` uses the Windows default. The
optional recorder uses the Windows WinMM API. It waits for Enter before **each**
question, counts down 3–2–1, then captures 12 seconds. Prompts:

- English: “On which day does the library reopen?”
- French: “Quel jour la bibliothèque est-elle fermée ?”

It saves `english.wav`, `french.wav` and a manifest under ignored
`voice/runtime/microphone-<UTC timestamp>/`. Output is native 16 kHz mono PCM16
WAV with no cloud processing or format conversion. `--seconds` allows 10–15;
`--output-dir` optionally selects another local directory. Ctrl+C closes the
microphone. Device/permission/format errors are reported without installing a
different recorder. Device enumeration was tested; actual capture awaits you.
The saved prompt is not a verified transcript of what you actually say.

After recording, provide the paths or run the interactive demo:

```powershell
& speech/.venv/Scripts/python.exe voice/demo.py --start-server `
  --english voice/runtime/microphone-<timestamp>/english.wav `
  --french voice/runtime/microphone-<timestamp>/french.wav
```

Each transcript is shown before submission. Enter accepts it, typing replaces it,
and `/skip` prevents its submission. Actual recordings are never automatically
confirmed by this demo. It also runs the explicit typed follow-up and absent-fact
question against the same history.

## Backend integration contract

Development imports can use `PYTHONPATH` containing `voice/src`, `stt/src`,
`llm/src`, `speech/src` (semicolon on Windows, colon on Linux). Alternatively
install the local packages together into the consuming environment:
`pip install ./stt ./llm ./speech ./voice`. Reuse the pinned Piper dependencies;
this adapter adds no third-party framework or inference dependencies.

```python
from signspeak_voice import DocumentSession, VoiceConversation

# Load ONCE per uploaded document; retain original records unchanged.
session = DocumentSession(views, records={
    "original_ocr": original_ocr,
    "reconciliation": cached_reconciliation,  # optional; retained, not recomputed
})
voice = VoiceConversation()  # retain this application-level instance

# Step 1: never calls Qwen or changes history.
prepared = voice.prepare_question(wav_bytes, language="auto")
# Show prepared["review_text"], warnings in prepared["transcription"], and language.
# Wait for the user's explicit confirmation/correction in your own UI.

# Step 2: called only following that explicit action.
result = voice.answer_question(
    session, confirmed_text, prepared=prepared,
    language="fr",  # explicit response language; may differ from document language
)
answer = result["answer"]
wav_bytes = result["wav_bytes"]  # audio/wav or None on failure

# Typed questions use EXACTLY the same session/history.
typed_result = voice.answer_question(session, "And at what time?", language="en")
history_for_persistence = session.history
```

- Input is the existing complete adapter `views`, including `llm_context`.
  `DocumentSession.from_file(path)` accepts cached views directly or the existing
  evaluation `{views, source}` wrapper. A new session starts a new conversation.
  Restore a persisted session with the same document, `session_id=...` and
  complete `history=[user, assistant, ...]` pairs. Keep records associated with
  that document; never reuse another image's history. Snapshot copies protect
  original records; session ID/context hash identify returned turns.
- `prepare_question`: accepts existing STT format/limits; returns
  `ready_for_review`, `no_speech`, `error` or `unsupported_language`, raw STT
  metadata, review text, suggested language and elapsed processing time.
  It does not retain audio. It cannot automatically submit a transcript.
- `answer_question`: requires nonempty **explicitly confirmed** text. A supplied
  preparation that is not ready is rejected before Qwen. Typed submission omits
  `prepared`. Response language must resolve to `en`/`fr`: a supplied value wins;
  otherwise an explicit preparation preference wins, then its detected language.
  Typed questions require explicit `language`. Document language never selects
  the response voice. Qwen is requested to answer in that language; this is not
  independent verification of its actual output language.
- Output includes `answer`, `wav_bytes`, MIME type, raw LLM metadata, Piper speech
  plan/voice metadata, warnings/errors, context identity, history-turn count and
  STT/Qwen/Piper/total timing. `verification` remains `not_performed`.
  Return WAV bytes as binary media through your own transport, not JSON directly.
- `ok` means text/audio generation completed; `text_only` preserves a Qwen
  answer/history if Piper fails; `error` reports Qwen failure without committing
  a partial turn. Invalid caller inputs raise `ValueError`. Retry synthesis from
  the returned text/Piper instance after a TTS failure rather than resubmitting
  the question and duplicating history.
- Existing Qwen grounding/compact context/numeric-conflict safeguards remain.
  Source numeric uncertainty and tentative readings are passed to Piper's
  localized notices. Only explicit answer text/language and uncertainty flags
  reach speech; source IDs, coordinates and confidence fields are not spoken.
  These flags are not a guarantee that Qwen found every disputed value.
- Calls are synchronous and serialize complete turns per session. Use a worker
  thread and a bounded queue in an async backend. All typed and spoken calls for
  a document must use the same session; history is returned as a snapshot.
  No automatic history truncation, conversation retrieval or reconciliation occurs.
- Active processing total sums STT and answer-call wall times, excluding human
  review and application queue time. Demo additionally records submission-to-WAV
  wall time and review delay. Server/model startup and adapter construction are
  reported separately. No automatic microphone capture occurs in the adapter.

## Configuration, Docker and validation

Inject `WhisperSTT(...)`, `LocalLLM(...)`, `PiperSpeech(...)` through
`VoiceConversation(stt=..., llm=..., speech=...)`, or use the existing environment
settings: `SIGNSPEAK_WHISPER_CLI`, `SIGNSPEAK_WHISPER_MODEL`,
`SIGNSPEAK_STT_CACHE`, `SIGNSPEAK_LLM_URL`, `SIGNSPEAK_VOICE_DIR`.
Qwen lifecycle uses the existing launcher/configuration separately. Standard
temporary-directory settings apply; keep temp storage writable and model storage
persistent. Service origins must be trusted local/native/container endpoints.
No models are downloaded during voice calls. The existing optional FFmpeg
boundary remains in `signspeak_stt.convert_audio` for noncanonical uploads.

Docker needs the same pinned native Whisper/Qwen runtimes, model artifacts and
Piper dependencies documented in their components. The adapter needs no new
service, microphone or playback device in a container. The user-run Windows
recorder is an optional development helper. No Compose/configuration is added;
actual Linux/container execution remains pending with the deployment team.

```powershell
python voice/tests/test_conversation.py
```

Eight tests cover the confirmation boundary, no-speech behavior, transcript
correction, user language, shared history, source preservation, uncertainty
propagation, Qwen failure and text fallback on TTS failure. The five-turn actual
model demonstration is separate from these stub-based boundary tests. Microphone
validation, room-noise reliability and manual audio listening remain pending.

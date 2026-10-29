# SignSpeak integration handoff

Run commands from the repository root. These tools do not download artifacts or
change existing modules. Their generated reports/WAVs are ignored under
`handoff/runtime/`. Readiness exits 0 only when all required checks pass;
nonzero reports an actionable failure, without a Python traceback.

## Check and smoke test

Current Windows environments remain separate; no installation is needed to test:

```powershell
& speech/.venv/Scripts/python.exe -B handoff/check.py `
  --ocr-python ocr/.venv/Scripts/python.exe --json handoff/runtime/readiness.json
```

This verifies package versions/imports, actual Tesseract version/eng/fra data,
existing model hashes, executable launchability, temp/cache writability and the
running Qwen `/health` and `/props` endpoints. It never starts a service. A
present executable is **not** evidence of a healthy service. Hash-valid artifacts
are setup evidence, not a promise of correct inference. Read-only model mounts
are permitted after provisioning; write failures there are warnings. Temp and
output write failures are fatal. Missing FFmpeg is optional for WAV-only use.

Actual integration test, reusing the authorized microphone recording and its
previously reviewed question (change the audio path for another recording):

```powershell
& speech/.venv/Scripts/python.exe -B handoff/smoke.py `
  --ocr-python ocr/.venv/Scripts/python.exe --start-server `
  --audio voice/runtime/microphone-20261029T175805378773Z/english.wav `
  --confirmed-question 'On which day does the library reopen?'
```

The default image is the permitted, generated English library notice in
`ocr/eval/benchmark/images/english_clean.png`. Override with `--image` and
`--question`; choose `--language en|fr`. `--confirmed-question` is an explicit
submission supplied by the caller, not a guessed correction. The recording's raw
transcript is saved separately. Missing models/audio/dependencies fail instead of
downloading or substituting mocks. No reconciliation is run.

`--start-server` explicitly starts **one** existing llama.cpp `Server` for this
whole test and stops only that owned process afterward. Omit it to reuse the
already-running service at `SIGNSPEAK_LLM_URL`. An occupied port is never killed;
use `--port` with `--start-server` if needed. `--ocr-python` selects an isolated
OCR subprocess using the real public API; omit it in a combined app environment.
Smoke output includes `document.json` (source + views), `session.json` (history),
two WAVs, preflight/readiness records, and compact per-step `results.json`.

## Dependency and artifact chain

| Component | Python dependencies | Native requirement / service |
| --- | --- | --- |
| OCR | NumPy >=2.1, Pillow >=11; optional `opencv-python-headless>=4.10` for preprocessing | Tesseract >=4 (local tested 5.4), `eng.traineddata`, `fra.traineddata`; no service |
| Qwen client | Standard library; optional Pillow for vision preparation | Compatible CPU `llama-server` + shared libraries; **one running HTTP service** |
| Piper | Exact pins in [speech/requirements.txt](../speech/requirements.txt): piper-tts 1.8.0, onnxruntime 1.31.1, numpy 2.5.4, pathvalidate, flatbuffers, packaging, protobuf | CPU ONNX/phonemization resources supplied by Piper; direct import, no service |
| Whisper | Standard library | Native `whisper-cli` + libraries and multilingual Base; subprocess, no persistent service needed |
| Voice | The three preceding local packages | Direct import, reuses Qwen URL and one retained Piper instance |

Use Python >=3.11 (Windows validation: 3.13.1). No PyTorch, pytesseract, Pipecat,
audio hardware or external inference SDK is required. For a fresh **combined**
backend environment, install the existing packages/constraints together:

```text
python -m pip install -r speech/requirements.txt "./ocr[preprocess]" ./llm ./speech ./stt ./voice
```

Alternatively retain separate environments and an application-owned subprocess
boundary, as the smoke test does for OCR. Do not combine venv `site-packages`
paths: the existing speech environment lacks Pillow/OpenCV. The checker validates
the chosen environments; it does not install missing dependencies.

Artifact identities are reused from the original manifests/verifiers, not copied
to another download manifest:

| Files | Pinned identity source |
| --- | --- |
| `Qwen3VL-2B-Instruct-Q4_K_M.gguf` | [llm/models.json](../llm/models.json), `vl`; revision `52d6c8ffea26cc873ac5ad116f8631268d7eb503`, SHA256/size recorded there |
| `mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf` | [llm/server.py](../llm/src/signspeak_llm/server.py) `FILES` / `REVISION`, same official revision; verified by `verify_file` |
| `en_US-ljspeech-high.onnx`, `fr_FR-siwis-medium.onnx`, adjacent `.onnx.json`, each voice's `MODEL_CARD` | [speech/voices.json](../speech/src/signspeak_speech/voices.json), revision `5041a7a49ae5b3a0f30e6837769eb03fdbb231bd`; exact per-file hashes, sizes and license provenance |
| `ggml-base.bin` (multilingual, not `base.en`) | [stt/artifacts.json](../stt/artifacts.json), revision `5359861c739e955e79d9a303bcbc70fb988958b1`; SHA256/size there |
| whisper.cpp Windows CPU archive | Same STT manifest: b5454 / v1.9.5 source commit `d1be6fde11ac6e0407606b4e42fe72d34add8037`; Linux needs a native build |
| Tesseract language data | Existing OS/user installation. Checker records installed eng/fra hashes. **No upstream data revision is pinned in this repo**; deployment team must record its chosen package/data provenance. |

llama.cpp's working Windows build is 11904 / source `5cd62ffee`; see
[LLM setup](../llm/README.md). No automated llama.cpp runtime installer exists.
Retain compatible native libraries alongside each executable. The cached
Qwen3-1.7B comparison model is not required and is not used here.

## First install: provision once, then start once

Only run the following provisioning commands deliberately during first install,
using installed local packages or appropriate `PYTHONPATH` entries. In PowerShell,
source-tree development imports can be set without hardcoded machine paths:

```powershell
$env:PYTHONPATH = ('ocr/src','llm/src','speech/src','stt/src','voice/src') -join [IO.Path]::PathSeparator
```

```text
python llm/src/signspeak_llm/models.py vl
python -m signspeak_speech provision en fr
python stt/src/signspeak_stt/provision.py
```

The Qwen provisioner downloads **only the language model**. For the projector,
reuse the existing generic verified downloader and the existing Qwen constants;
set `SIGNSPEAK_LLM_PROJECTOR` to its intended persistent filename first:

```python
import os
from pathlib import Path
from signspeak_llm.server import FILES, REVISION, MODEL_REPO, verify_file
from signspeak_stt.provision import download

p = Path(os.environ["SIGNSPEAK_LLM_PROJECTOR"])
size, digest = FILES[p.name]  # requires the exact pinned projector filename
download(f"https://huggingface.co/{MODEL_REPO}/resolve/{REVISION}/{p.name}",
         p, {"bytes": size, "sha256": digest})
verify_file(p)
```

This is first-install-only guidance, not run by the checker or smoke test. The
Windows STT provisioner installs the official CPU runtime/model; on Linux it
provisions **only the model**, so the Docker team must build/provide whisper-cli.
Likewise install native Tesseract plus English/French data and llama-server once.
Persist these files and Python wheels/libraries in the image/volumes as appropriate.

Start Qwen **once**, outside request handlers:

```text
python -m signspeak_llm serve --threads 4
```

It verifies local files, binds `127.0.0.1:8091`, waits for health, and uses
`--offline`. OCR-grounded chat does not need the projector loaded. `--vision`
explicitly loads the cached projector for optional future image requests; this
handoff never calls reconciliation. The existing native launcher binds loopback:
for a separate container service, the Docker team must arrange the server's bind
address and trusted internal service URL themselves (no Compose changes here).

## Minimal backend calls and return types

```python
import json
from pathlib import Path
from signspeak_ocr import extract_image, PipelineConfig, PreprocessConfig
from signspeak_ocr.integration import adapt_result
from signspeak_speech import PiperSpeech
from signspeak_voice import DocumentSession, VoiceConversation

# Once per uploaded image; bytes or a local path are accepted. Preserve source.
source = extract_image(image_bytes, PipelineConfig(
    preprocessing=PreprocessConfig(enabled=True)))  # dict
if source["validation"]["overall_status"] == "failed":
    raise ValueError(source["errors"])
views = adapt_result(source)  # dict with display, speech, llm_context, source
cache = Path("sessions") / upload_id
cache.mkdir(parents=True, exist_ok=True)
(cache / "document.json").write_text(
    json.dumps({"source": source, "views": views}, ensure_ascii=False), encoding="utf-8")
session = DocumentSession(views, records={"original_ocr": source})

tts = PiperSpeech()  # retain once to keep lazily loaded voices resident
read_aloud = tts.synthesize_view(views["speech"])  # SpeechResult
# Or: tts.synthesize(text, "en") / tts.synthesize(text, "fr")
read_aloud_wav = read_aloud.wav_bytes  # bytes, 22,050 Hz mono PCM16 WAV

voice = VoiceConversation(speech=tts)  # retain once; Qwen service already running
prepared = voice.prepare_question(wav_bytes, language="auto")  # dict; STT only
# Show review_text + transcription warnings. Wait for explicit user confirmation.
if prepared["status"] == "ready_for_review":
    answer = voice.answer_question(session, confirmed_text,
                                   prepared=prepared, language="fr")  # dict

# Typed and spoken questions must use the SAME session/history:
typed = voice.answer_question(session, "When does it reopen?", language="en")
```

Preserve original images, source JSON and optional cached reconciliation separately.
Load saved documents with `DocumentSession.from_file(cache / "document.json")`.
Persist `session.session_id`, `session.context_sha256` and `session.history` after
turns; restore active history explicitly with the constructor's `history=` and
`session_id=` arguments. The file loader loads document records, not active history.
Never attach another uploaded image's history or rerun OCR per question.

`answer` contains `status` (`ok`, `text_only`, `error`), `answer` text,
`wav_bytes` (bytes or None), `audio_mime_type`, `timings`, warnings/errors and
model metadata. Return WAV bytes through your framework's binary response with
`Content-Type: audio/wav`, or save them and return a media URL. Do not JSON-encode
raw bytes. A Piper failure keeps text/history (`text_only`); retry synthesis from
that text rather than resubmitting a duplicate Qwen turn. Invalid caller inputs
raise `ValueError`; Qwen failure returns an error without adding a partial turn.
Retain source uncertainty; TTS notices announce it without proving correctness.
For unresolved mixed/unknown OCR language tags, split identified language segments
or supply an explicit `default_language` to Piper; it never silently translates.
Use a worker thread/bounded queue for these synchronous APIs. Model status is
not transcript/answer verification; keep review especially for numbers.

Browser MediaRecorder audio may be **WebM/Opus, not WAV**. The STT contract is
16 kHz mono PCM16 WAV (default 60 s / 8 MB limits). Convert explicitly before STT:

```python
from signspeak_stt import convert_audio
wav_bytes = convert_audio(browser_audio_bytes)  # needs local SIGNSPEAK_FFMPEG/PATH
```

No format is guessed or silently converted by `prepare_question`. FFmpeg is
currently absent, so real WebM/Opus acceptance remains blocked until the team
provisions it and tests conversion. No microphone/audio playback device is
required inside the backend/container; the browser records and plays media.

## Storage, offline launch and remaining deployment gaps

| Settings | Storage / purpose |
| --- | --- |
| `SIGNSPEAK_TESSERACT_CMD`, `SIGNSPEAK_TESSDATA_DIR` (or `TESSDATA_PREFIX`) | Native OCR executable and eng/fra data, usually provisioned in container image |
| `SIGNSPEAK_LLAMA_SERVER`, `SIGNSPEAK_LLM_MODEL` | Native server and persistent Qwen GGUF; default model resolver uses HF snapshot or `SIGNSPEAK_MODEL_CACHE` |
| `SIGNSPEAK_LLM_PROJECTOR` | Persistent pinned projector. Default `--vision` path uses the standard home HF snapshot; set explicitly when using custom HF/cache mounts |
| `SIGNSPEAK_LLM_URL` | Trusted internal HTTP origin, default `http://127.0.0.1:8091`; no `/v1` suffix |
| `SIGNSPEAK_VOICE_DIR` | Persistent root with each named voice subdirectory and its three files |
| `SIGNSPEAK_STT_CACHE`, `SIGNSPEAK_WHISPER_CLI`, `SIGNSPEAK_WHISPER_MODEL` | Native CLI + libraries and persistent Base model; explicit paths override defaults |
| `HF_HUB_CACHE` | Optional existing model/voice snapshots reused by resolvers |
| `SIGNSPEAK_FFMPEG` | Optional native browser-audio converter |
| `TMPDIR` (Linux), `TEMP`/`TMP` (Windows) | Writable ephemeral inference files; microphone data is not permanently retained by normal STT |

Persist Qwen/projector, Whisper model and both voice directories across launches;
store uploaded images/document JSON/history in application-owned persistent
storage. Binaries/libraries/Python dependencies can live in the built image.
Provision model mounts writable initially; subsequent inference can read them
read-only. Temp/session/output storage must remain writable.

Subsequent offline launch: mount existing artifacts, set explicit paths/URL, start
Qwen once with local files, wait for health, then run readiness and accept requests.
Do not invoke provisioning at each startup/request. Source inspection found no
download call in OCR extraction, LocalLLM.answer, Piper synthesis, Whisper
transcription or voice orchestration. The smoke test additionally denied Python
socket connections except its configured Qwen endpoint. Native processes were
not subjected to OS-wide packet tracing; this is not an air-gap certification.

Linux OCR benchmark evidence already exists in `ocr/eval/RESULTS.md`. Current
Qwen/Piper/Whisper/voice and this complete smoke test were exercised on Windows;
the integrated Linux/Docker application, native library packaging and browser
audio conversion still require deployment-team validation. Windows executables
cannot be reused as Linux binaries. No Dockerfiles, Compose or shared config were
changed. Some older OCR docs still say Windows validation pending; this handoff
records a new successful clean-sample Windows execution, not a new broad OCR study.

## Observed handoff result

Actual run: [machine-readable smoke result](runtime/smoke-1793298769628480100/results.json).
All seven steps passed; [running-service readiness](runtime/smoke-1793298769628480100/readiness-running.json)
was true. With Qwen stopped, readiness correctly failed only the service check;
optional FFmpeg remained a warning. The owned smoke-test server was stopped afterward.

- Image OCR/save: 0.94 s; source text matched the generated notice.
- Typed Qwen/Piper: 10.75 s (5.82 s Qwen, 4.93 s Piper). Answer:
  “The library reopens on Tuesday at 9:00 AM.” [WAV](runtime/smoke-1793298769628480100/typed-answer.wav)
- Real saved microphone STT: 1.83 s. Raw hypothesis:
  “One which did as the library opened.” Explicit previously reviewed submission:
  “On which day does the library reopen?” No STT accuracy claim is made.
- Confirmed spoken Qwen/Piper: 0.55 s, or 2.38 s including STT (review delay
  excluded). Answer: “Tuesday”. [WAV](runtime/smoke-1793298769628480100/spoken-answer.wav)
- Source/cache hashes stayed unchanged across questions; two shared history turns;
  one OCR call and zero reconciliation calls. No model download was performed.

Remaining integration work: supply a combined dependency environment or explicit
process boundaries, run/configure Qwen service, install/test FFmpeg if browser
WebM is accepted, pin Tesseract data provenance, verify Linux/container packaging
and listen to final audio. These are deployment/validation tasks, not new AI features.

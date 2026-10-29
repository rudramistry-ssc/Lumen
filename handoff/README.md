# SignSpeak backend handoff — current default

Vision metadata normalization preserves usable literal sections when the model
contradicts them with `printed_text_status=none`; the status becomes `present`
with an explicit normalization warning. Words and values are never repaired.
Malformed JSON, invalid fields, empty claimed text and incomplete generations
still fail. The original response remains in `vision_only.json` under
`inference.answer`; normalization warnings also propagate to document warnings.
Cross-out observations without a corresponding crossed-out section are retained
as `unconfirmed_observations` in vision evidence, excluded from active annotations.
Even consistent visual markings remain unverified. Numeric uncertainty extracts
individual literal values from uncertain passages, rather than treating a whole
paragraph as one disputed number. Full passages remain in text observations.

Final targeted validation (2026-10-29): 53 regression tests passed. One live
vision-first library-notice upload ran OCR once and vision once, normalized the
model's contradictory `none` status, and selected its unchanged literal text.
The displayed text matched; Q&A answered "The library opens at 9:00 AM on Monday."
Piper synthesized that answer and a correct follow-up. Both questions used the
same saved context with no image inference; no spurious numeric conflicts were
created. Local evidence: `handoff/runtime/final-workflow/results.json` (Git-ignored).
Existing jailbreak tests passed; the previously documented security limitations
remain accepted and unchanged. No photo benchmark or long security smoke reran.

## Offline prompt-injection and jailbreak guardrails

`llm/src/signspeak_llm/guardrails.py` provides local deterministic checks, with
no new models, packages, services or network calls. `DocumentProcessor` scans
the selected vision document and retained OCR evidence. It adds `guardrails`
metadata to the document and its saved `llm_context`; literal text, sections,
OCR and visual interpretations stay intact. Suspicious document instructions
are `needs_review` evidence, not a reason to reject reading or questions.
Findings contain risk categories and original string offsets/path, without
duplicating document text in logs. Cached documents are checked from saved
evidence without rerunning OCR or vision. The existing vision system prompt
already requires literal transcription of malicious instructions without obeying
them; it and the one-OCR/one-vision upload architecture are unchanged.

`LocalLLM.answer` checks the question, document and conversation history before
any Qwen request, then validates the raw and final answer. Q&A operating rules
are system messages, document JSON is untrusted user evidence, and role-like
delimiters are escaped without changing decoded document text. Follow-ups use
saved selected text, section states, visual descriptions and uncertainty only.
Ambiguous source discussions continue through the existing model under these
task boundaries. The low-level `complete` transport remains available to image
transcription; use `answer` for Q&A so those checks cannot be skipped.

`VoiceConversation.answer_question` applies the same checks for typed and
explicitly confirmed STT questions, including when an injected/custom Qwen client
is used. STT preparation still only prepares review text. A blocked question
never reaches Qwen. An unsafe answer never reaches Piper or history, and the
unsafe generation is omitted from the returned result. Successful turns still
share the same session history. A detector exception or malformed decision
returns `blocked` with `reason=guardrail_unavailable`; it never silently allows
the request. Valid saved blocked upload metadata also prevents Q&A.

Consumers receive `guardrails.status` (`allowed`, `blocked`, `needs_review`),
matching boolean fields, `reason`, `detected_risks`, and `suspicious_spans` where
applicable. Allowed/review Q&A results also include per-stage `checks`.
`needs_review` can coexist with a normal spoken answer: it identifies suspicious
source material or ambiguous discussion, not an executed command. Existing
document review status is independent of this security status.

For a blocked Q&A turn, display the short localized `answer` as a notice;
`status=blocked`, `wav_bytes=None`, unchanged `history_turns`, and the security
reason distinguish it from a successful answer. Do not request playback or
append a successful turn. A detector failure can be displayed as an inability to
complete security checks, with an option to retry. The frontend/backend and
Docker implementation files have not been changed.

Literal read-aloud remains available through `read_document`: speaking photographed
words (including malicious instructions) is document reading, not execution.
Only validated generated Q&A answers go through the answer-to-Piper path.

Focused regressions in `llm/tests/test_guardrails.py` and
`voice/tests/test_security.py` cover English/French indirect attacks, fake roles,
hidden-prompt requests, role-play, command requests, zero-width obfuscation,
one-level base64 attacks, legitimate quoted/translated source discussion,
history safety, session isolation, cached uploads, output rejection, and failed
detectors. They use fixtures/stubs rather than model downloads or a new photo
evaluation. These heuristics do not prove factual accuracy or complete jailbreak
resistance: paraphrases, other languages/encodings, subtle instruction compliance,
and nonliteral internal-data leaks can evade detection. Prompt boundaries provide
an additional defense using the existing Qwen model; no extra detector model runs.

Validation on 2026-10-29: **76 tests passed, no failures or skips**: LLM 50
(including 8 new security tests and both opt-in OCR deadline tests), voice 12
(including 4 new security tests), speech 8, STT contracts 6. The security fixture
matrix blocks 11 explicit attack variants before model requests and allows all
10 legitimate-question variants (zero false positives in that matrix). Initial
sandbox runs encountered Windows temporary-directory permission and taskkill
restrictions; rerunning the affected suites outside the sandbox passed. No
ten-photo evaluation or model inference benchmark was rerun. The existing saved
photo regression only replays stored JSON and verifies it remains unchanged.

Run each suite with `python -B -m unittest discover -s <directory> -v`, using
`llm/tests`, `voice/tests`, `speech/tests`, and `stt/eval` (the latter with
`-p test_contract.py`). Set `PYTHONPATH` to the five package `src` directories;
use the existing OCR environment for LLM tests and speech environment for the
others. Set `SIGNSPEAK_RUN_OCR_DEADLINE_TEST=1` for the two installed-Tesseract
transport tests. These use a local simulated HTTP server, not Qwen. On restricted
Windows hosts, allow temporary-directory access and owned-worker termination.

**Default upload: real OCR once + one independent vision-only transcription.**
The vision prompt receives the image without OCR text. Successful vision text is
the selected document for display, Piper and typed/spoken Q&A. OCR is preserved
for geometry and advisory discrepancies; it never rewrites the vision text. The
hybrid reconciler remains available for explicit evaluation/debugging only.

## Setup and launch

Use Python >=3.11 (tested 3.13.1). A combined consuming environment needs:

```text
python -m pip install -r speech/requirements.txt "./ocr[preprocess]" ./llm ./speech ./stt ./voice
```

OCR needs native Tesseract with `eng.traineddata`/`fra.traineddata`; preprocessing
uses OpenCV. Qwen needs a native llama-server and its libraries. Whisper uses
native whisper-cli, not PyTorch. Piper runs directly through CPU ONNX, with no
service. **Only Qwen requires a persistent HTTP service.** Existing separate
OCR/Piper environments remain supported via `DocumentProcessor(worker_python=...)`
and the smoke test's `--ocr-python`. The upload interpreter must have OCR, Pillow,
OpenCV and the LLM package; the consuming interpreter may retain Piper separately.
Do not mix their site-packages paths; the Piper environment lacks Pillow/OpenCV.

Model filenames, revisions, hashes and licenses remain in existing manifests:

- [Qwen VL manifest](../llm/models.json), `vl`, and [projector FILES/REVISION](../llm/src/signspeak_llm/server.py): Q4_K_M language model + Q8_0 projector, revision `52d6c8ffea26cc873ac5ad116f8631268d7eb503`.
- [Piper manifest](../speech/src/signspeak_speech/voices.json): en_US-ljspeech-high and fr_FR-siwis-medium; each ONNX, adjacent config and model card.
- [Whisper manifest](../stt/artifacts.json): multilingual ggml-base.bin and official Windows CPU b5454 runtime; Linux requires its own native binary.
- Tesseract data has no upstream revision pinned here. Readiness inventories installed hashes; the deployment team must record its chosen data/package provenance.

Explicit first-install commands only (installed packages or source PYTHONPATH):

```text
python llm/src/signspeak_llm/models.py vl
python -m signspeak_speech provision en fr
python stt/src/signspeak_stt/provision.py
```

The Qwen provisioner supplies only the language model. Provision the pinned
projector separately using the existing generic downloader and constants:

```python
import os
from pathlib import Path
from signspeak_llm.server import FILES, REVISION, MODEL_REPO, verify_file
from signspeak_stt.provision import download
p = Path(os.environ["SIGNSPEAK_LLM_PROJECTOR"])
size, digest = FILES[p.name]  # mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf
url = f"https://huggingface.co/{MODEL_REPO}/resolve/{REVISION}/{p.name}"
download(url, p, {"bytes": size, "sha256": digest})
verify_file(p)
```

Start Qwen **once**, outside request handlers, and retain it across all uploads
and questions. Vision/projector and 8192 context are now launcher defaults:

```text
python -m signspeak_llm serve --vision --context-size 8192 --threads 4
```

The existing launcher binds localhost. For a separate container service, the
Docker team must arrange the native server bind address/internal URL. The legacy
`--text-only` launch cannot process normal uploads. Never run provisioning during
subsequent offline startup or inference.

## One upload API, shared downstream context

```python
import json
from pathlib import Path
from signspeak_llm import DocumentProcessor
from signspeak_speech import PiperSpeech
from signspeak_voice import DocumentSession, VoiceConversation

processor = DocumentProcessor(processing_timeout_seconds=600)  # retain
# Separate environments: set worker_python to the OCR-capable Python executable.
# Called ONLY from upload processing. Wait for the complete result.
document = processor.process(image_bytes)  # JSON-compatible dict, persistently cached
Path("uploaded-document.json").write_text(json.dumps(document), encoding="utf-8")
if document["status"] != "needs_review":
    raise RuntimeError(f"Upload failed or requires fallback review: {document}")

selected = document["selected_views"]
display = selected["display"]  # final text + ordered sections + warnings
session = DocumentSession.from_document(document)  # fresh per-upload history
speech = PiperSpeech()  # retain to reuse voices
voice = VoiceConversation(speech=speech)
reading = voice.read_document(session, language="en")  # no LLM call
reading_wav = reading.wav_bytes  # SpeechResult -> PCM16 WAV bytes, 22050 Hz
# Printed text only: voice.read_document(..., include_visual_descriptions=False)

# Typed question: final selected context, not original OCR.
answer = voice.answer_question(session, "When does it reopen?", language="en")
# Subsequent audio question: STT only, then explicit user confirmation/correction.
prepared = voice.prepare_question(wav_bytes, language="auto")
# Display prepared["review_text"] and its STT warnings, and wait for the user.
if prepared["status"] == "ready_for_review":
    spoken = voice.answer_question(session, confirmed_text, prepared=prepared, language="fr")
# All follow-ups use this SAME session. Do not call processor again here.
```

`document["text"]` equals display text, `speech.text` and Q&A `selected_text`.
Ordered sections preserve `text_state` (plain/crossed_out/uncertain).
`printed_text_status` distinguishes present/none/uncertain. A symbol-only result
has empty literal text/sections; `visual_descriptions` separately explains symbols
with language/kind and unverified provenance. `read_aloud` combines the same
literal text with explicitly labelled descriptions; `speech` is literal only.
Both carry uncertainty notices. Q&A receives descriptions and warnings separately,
never as words claimed to be printed. No model word boxes/confidences are created.

`text_observations` retains cross-outs, possible replacements, redactions and
critical-value doubts. `ocr_comparison`/context `ocr_discrepancies` are fallible
advisory evidence. Disagreements never replace selected vision numbers. Agreement
is not verification. Suspicious times/empty fields are flagged, never repaired or
filled. All results remain `needs_review` until an external human review.

The cache saves original `image.bin`, `ocr.json` (full engine output and views),
`vision_only.json`, `evidence.json` and `document.json`, with image identity and
an evidence digest. Never use `original_views['llm_context']` for normal Q&A.
No normal hybrid request runs. [Detailed contract](../llm/DOCUMENTS.md).

`SIGNSPEAK_UPLOAD_DEADLINE_SECONDS` (default 600) or constructor override bounds
the whole upload, including preprocessing, OCR, HTTP reads and lock waiting.
The standard path uses an owned subprocess with time reserved for cancellation;
the worker and its OCR children are terminated at expiry, closing its HTTP
connections. The shared Qwen server stays running. Native cancellation is
connection-disconnect driven; inspect `cancellation` rather than assuming a server
acknowledgement. Process cleanup failures are explicit, not claimed successful.
Do not use test-only `isolate=False` in production: it bypasses this hard boundary.

On `deadline_exceeded`/`processing_failed`, there is no selected document; inspect
`stage`, `error`, `cancellation`, `partial_evidence` and request wall time. Saved
OCR checkpoints remain unverified. A completed `ocr_unreviewed_fallback` is also
explicit and rejected by `DocumentSession.from_document` unless `allow_fallback=True`.
Never present it as vision text. Cached failures/fallbacks do not silently retry;
review/repair the individual cache deliberately. Legacy v1 mixed-text documents
are preserved but require explicit review/reclassification for the v2 typed
literal/description contract; no automatic migration or image rerun occurs.

`answer`/`spoken` are dictionaries with answer text, `wav_bytes`, MIME type,
warnings/errors and STT/Qwen/Piper timing. Return WAV bytes via your framework's
binary `audio/wav` response (or saved media URL), not inside JSON. Piper failure
returns `text_only` while retaining text/history; retry synthesis, not the Qwen
turn. Invalid input raises ValueError; Qwen failure does not append partial history.
These synchronous calls need a worker/bounded queue in async backends.

Restore documents using `DocumentSession.from_file(document_json)`. Save session ID
and history separately; restore with `DocumentSession(selected_views, history=...,
session_id=...)`. New uploads create new sessions; shared document cache never
stores conversation history. OCR-only sessions require explicit legacy opt-in;
labelled OCR fallback requires explicit `allow_fallback=True` through the loaders.

Browser audio may be **WebM/Opus**, not WAV. Convert explicitly through
`signspeak_stt.convert_audio(browser_bytes)` using local `SIGNSPEAK_FFMPEG`/PATH.
STT requires 16 kHz mono PCM16 WAV (default 60 s / 8 MB). FFmpeg is currently absent,
so browser-format conversion still needs provisioning/testing. No audio hardware
is required in Docker; the frontend records and plays audio. Unknown/mixed speech
segments require explicit language boundaries or a caller-selected default voice.

## Readiness and actual smoke test

From the repository root in PowerShell (no installs into existing environments):

```powershell
& speech/.venv/Scripts/python.exe -B handoff/check.py --ocr-python ocr/.venv/Scripts/python.exe
& speech/.venv/Scripts/python.exe -B handoff/smoke.py --ocr-python ocr/.venv/Scripts/python.exe `
  --start-server --audio voice/runtime/microphone-20261029T175805378773Z/english.wav `
  --confirmed-question 'On which day does the library reopen?'
```

Readiness checks package imports/versions, real Tesseract language availability,
model hashes, executable probes, writable locations and actual Qwen health,
vision capability, model filename and context size. It never starts/downloads
anything. Exit 0 means required checks passed, not semantic accuracy verified.

The smoke test explicitly owns one server for the whole run; omit --start-server
to attach to an existing service. It saves a new ignored runtime directory and
uses the actual public APIs. The authorized recording is replayed with explicit
previously reviewed text; STT output is preserved, not silently corrected.
It checks display/Piper identity, saved selected context, typed and spoken text-only
follow-ups, stable context, cache reuse, and fresh session history. A missing model
fails clearly; no mock/substitute or download is used.

## Docker persistence and outstanding validation

Persist `SIGNSPEAK_DOCUMENT_CACHE` (default ~/.cache/signspeak/documents), Qwen GGUF
and projector, Whisper Base and both Piper voice directories, plus application
uploads/source JSON/session histories. Normal launch requires only reads from
model mounts; document/session cache and temporary storage must be writable.
Existing environment overrides remain:

- `SIGNSPEAK_DOCUMENT_PYTHON` (OCR-capable worker interpreter), `SIGNSPEAK_UPLOAD_DEADLINE_SECONDS`.
- `SIGNSPEAK_LLAMA_SERVER`, `SIGNSPEAK_LLM_MODEL`, `SIGNSPEAK_LLM_PROJECTOR`, `SIGNSPEAK_LLM_URL` (trusted origin, no /v1 suffix).
- `SIGNSPEAK_MODEL_CACHE`/`HF_HUB_CACHE` for existing model snapshots. Explicitly set projector path for custom mounts: its default uses the standard home HF snapshot.
- `SIGNSPEAK_VOICE_DIR`, `SIGNSPEAK_STT_CACHE`, `SIGNSPEAK_WHISPER_CLI`, `SIGNSPEAK_WHISPER_MODEL`.
- `SIGNSPEAK_TESSERACT_CMD`, `SIGNSPEAK_TESSDATA_DIR`/`TESSDATA_PREFIX`; `SIGNSPEAK_FFMPEG` if converting browser audio.
- Standard TMPDIR (Linux) or TEMP/TMP (Windows) for writable ephemeral files.

Native Linux executables/libraries must be provisioned by the Docker team; Windows
binaries are not reusable there. OCR has previous Linux benchmark evidence, but
the complete current Qwen/Piper/Whisper/voice application remains untested
in Linux/Docker. No inference path calls provisioning; the Qwen launcher uses
--offline. Native processes have not been subjected to OS-wide network tracing.

Validation: the preserved [historical generated smoke](runtime/hybrid-smoke-1793303344367060700/results.json)
used the previous two-visual-call upload architecture; its timings are not measurements
of this revision. Current targeted regressions exercise one OCR/one vision/no hybrid,
cached reuse, stable shared question history, separate new sessions, literal/symbol
separation, explicit fallback and worker cancellation. The opt-in transport test
uses real Tesseract and a deliberately trickling local HTTP test server (not Qwen)
to verify the end-to-end deadline and retained OCR; no new model benchmark was run.
Private results: `llm/runtime/vision-default-regression/report.json`.

The original photographic pilot and all outputs remain under
`llm/runtime/photo-evaluation/user-ten-20261029/`: eight saved records, two
unfinished at user request. All ten reference templates remain pending manual
review; real-photo transcription accuracy is NOT manually validated. No validated
CER/WER or claim that selected text is correct. FFmpeg conversion, Tesseract
provenance pinning and full Linux/container validation remain deployment checks.

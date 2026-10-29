# Upload-once vision document

Normal path: **Tesseract OCR once + independent Qwen3-VL once -> saved vision text**.
OCR never enters the vision transcription prompt. No normal hybrid inference,
word merging or majority vote. `Reconciler.reconcile(..., mode="hybrid")` and the
legacy comparison functions remain explicit evaluation/debug tools.

```python
from signspeak_llm import DocumentProcessor
from signspeak_voice import DocumentSession, VoiceConversation

processor = DocumentProcessor(processing_timeout_seconds=600)
document = processor.process(original_image_bytes)  # JSON-compatible dict
if document["status"] != "needs_review":
    raise RuntimeError(document)  # explicitly handle failure/labelled OCR fallback
session = DocumentSession.from_document(document)
voice = VoiceConversation()  # retain Piper voices and local Qwen client
reading = voice.read_document(session, language="en")  # SpeechResult.wav_bytes
answer = voice.answer_question(session, "What does it say?", language="en")
# Reuse session for typed and confirmed spoken follow-ups; never call processor here.
```

One persistent vision-enabled server is required, including the existing projector:
`python -m signspeak_llm serve --vision --context-size 8192 --threads 4`.
Follow-ups are text-only with `cache_prompt=True`, stable document context and the
same history. Context overflow fails rather than silently truncating the document.

The selected v2 result contains:

- `text`, ordered `sections` with `text_state`, `printed_text_status`.
- `visual_descriptions`: unverified symbol/pictogram/layout interpretations,
  distinct from literal words. `none` requires empty printed sections.
- `text_observations`: cross-outs, redactions, uncertain replacements and values.
- `ocr_comparison`, `warnings`, `verification="not_performed"`, `vision_error`.
- `selected_views`: display, literal-only speech, labelled-description read_aloud,
  and stable llm_context including warnings, observations and OCR discrepancies.
- Source identity, `evidence_ref`/digest, measured processing/request wall seconds,
  and `execution_this_call` (fresh: OCR 1 / vision 1 / hybrid 0; cache: all zero).

Vision text is authoritative for presentation, not verified ground truth. OCR
numeric discrepancies never alter it. Only uncertainties within the vision
reading itself enter conservative numeric-answer safeguards. No new coordinates,
word confidence or independent verification is claimed. Piper announces uncertainty;
read_aloud prefixes descriptions as interpretations, never physically printed text.

Cache: `SIGNSPEAK_DOCUMENT_CACHE` (default ~/.cache/signspeak/documents), keyed by
image SHA256 and configuration/schema. Original bytes, complete OCR with boxes,
vision result and selected document are separate files. Completed results and
labelled OCR fallbacks persist. A cache hit runs neither engine. New sessions
have new IDs/history even when their image cache is reused. Application-owned
history must be saved separately. Never substitute original OCR views into Q&A.

The standard processor uses a bounded owned subprocess. Configure the OCR-capable
interpreter using `worker_python` / `SIGNSPEAK_DOCUMENT_PYTHON` if Piper and OCR
use separate environments. The worker needs the OCR package/preprocessing deps,
Pillow and the LLM package; it does not load another Qwen model or launch a server.
`processing_timeout_seconds` / `SIGNSPEAK_UPLOAD_DEADLINE_SECONDS` defaults to 600.
The total budget includes startup, pipe IO, locking, OCR, network streaming and
cancellation reserve. Expiry stops only the worker tree and closes its sockets;
Qwen remains running and handles disconnect-driven cancellation. OS termination
failures are explicit. `isolate=False` is only for controlled callback tests/debug.

`deadline_exceeded` / `processing_failed` returns no selected_views, with stage,
error, cancellation metadata and partial_evidence checkpoint directory. No partial
vision text is promoted. The worker checks the deadline before final commit.
Saved failures/fallbacks do not retry automatically. Damaged/incomplete caches
require explicit repair; stale locks must not be blindly deleted while active.
Legacy v1 mixed literal/symbol results remain preserved, are rejected for v2
sessions, and need explicit review/reclassification rather than automatic reruns.

The historical photographic pilot/reference files are unchanged. References are
still unverified; there are no validated real-photo CER/WER scores. Regression
replays validate contracts, not transcription accuracy. See the
[backend/Docker guide](../handoff/README.md) for provisioning, voice confirmation,
WAV responses, mounts and remaining Linux validation.

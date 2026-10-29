# Hybrid OCR + Qwen3-VL reconciliation

Transcribes an image in reading order, assisted by compact OCR evidence. It
produces a **separate, unverified candidate**, not a summary or a replacement for
the original OCR JSON. No OCR execution, model download, server startup, routes,
speech engines or Docker configuration occurs inside `reconcile()`.

## Start and use

The existing OCR environment already has Pillow. A separate installation can use
`pip install -e './llm[vision]'`; Pillow is the only additional vision dependency.
From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = 'llm/src;ocr/src'
$env:PYTHONIOENCODING = 'utf-8'
& ocr/.venv/Scripts/python.exe -m signspeak_llm serve --vision --threads 4
```

Startup reuses the cached Qwen3-VL Q4_K_M and matching Q8 projector, verifies their
hashes, runs CPU-only with one 4096-token slot and binds `127.0.0.1:8091`.
Use `--binary`, `--model`, `--projector`, `--port`, `--context-size`, or
`SIGNSPEAK_LLAMA_SERVER`, `SIGNSPEAK_LLM_MODEL`, `SIGNSPEAK_LLM_PROJECTOR` on other
machines. Binaries on PATH are detected. No download occurs during serving.

In the application, reuse its existing adapter output:

```python
from signspeak_llm import reconcile

result = reconcile(image_bytes, views["llm_context"])
# Original OCR JSON and views are unchanged.
candidate = result["text"]
```

For explicit configuration and one instance shared across requests:

```python
from signspeak_llm import LocalLLM, Reconciler

engine = Reconciler(
    LocalLLM("http://127.0.0.1:8091", max_tokens=768, timeout=240),
    cache_dir="/persistent/reconciliation",  # choose a writable local path
    model_fingerprint="actual weights + projector hashes + runtime/config version",
)
result = engine.reconcile(image_bytes, views["llm_context"])
```

The endpoint is a trusted local HTTP origin without `/v1`; `SIGNSPEAK_LLM_URL` is
also supported. The native startup helper remains separate from the client.
Docker teammates can supply their own Linux runtime and persistent mounts.

A saved adapter view can be used from another terminal with the same PYTHONPATH:

```powershell
& ocr/.venv/Scripts/python.exe -m signspeak_llm reconcile photo.jpg views.json --output candidate.json --cache-dir llm/runtime/reconciliation-cache
```

## Result contract

| Field | Meaning |
|---|---|
| `status` | `ok`, `needs_review`, or `fallback`; processing status, never proof of accuracy |
| `text`, `sections` | Ordered candidate transcription; sections have application-assigned IDs |
| `source` | Original image-byte SHA256 and original OCR run/image references |
| `model_text` | Model transcription, or null on failure; fallback text is never presented as model output |
| `model_only_readings` | Added tokens not corroborated by OCR; may be legitimate visual recoveries |
| `comparison` | Literal numeric differences, omissions, additions, sequence edits and preserved OCR conflicts |
| `uncertain_readings` | Sections containing the model's `[unclear]` marker |
| `warnings`, `requires_review` | Review flags for differences, critical values and source uncertainty |
| `verification` | Always `not_performed`, including when OCR and VLM agree |
| `inference`, `processing_ms` | Raw model JSON, usage, timings, TTFT and total processing duration |
| `ocr_fallback` | Original selected OCR text and source references |
| `cache_key`, `cache_hit` | Persistent result identity and reuse indicator |

No coordinates or verified confidence are generated for reconstructed words.
Region references are attached only for exact section/region text matches;
these are literal links, not independent verification or visual alignment.

Differences in numbers, signs, dates, prices and common units are flagged without
choosing an OCR or VLM reading as truth. Decimal representation changes remain
visible even when a conservative decimal comparison finds the same quantity.
Text edits can also be OCR cleanup or reading-order changes; “unsupported” means
not supported by OCR, **not** a proven hallucination. Cross-field associations,
all unit types and visual correctness are not independently validated.

Do not silently replace an OCR value or read a disputed candidate aloud as
verified. A consumer should retain and expose the alternatives/review flags.
The model receives image/document instructions as data under an application
system instruction and JSON schema. This reduces instruction-following risk;
it does not establish general prompt-injection resistance.

## Cache, failures and integration

Successful candidates, including `needs_review`, are cached atomically by image
bytes, complete OCR evidence, prompt/version and configured model parameters.
Cache hits work with the model server stopped. Default storage is
`~/.cache/signspeak/reconciliation`; override with `SIGNSPEAK_RECONCILE_CACHE` or
`cache_dir`. Cached text is local document data; it is not sent through proxies.

Update `model_fingerprint` when weights, projector, runtime or serving settings
change. The default identifies the expected pinned Qwen pair, not an attestation
of an arbitrary server. One instance serializes concurrent calls; multiple
processes can duplicate a first request, though atomic writes avoid partial JSON.

Timeouts, invalid JSON/schema, incomplete generation, context overflow, bad images
and image/OCR hash mismatches return `fallback`, retaining OCR and an error.
Failures are not persisted, permitting an explicit retry. Invalid API argument
types raise `ValueError`. CLI exit code 2 indicates an OCR fallback was written.

Image preparation applies EXIF orientation, converts to RGB PNG and bounds the
long edge to 1280 pixels, recording sizes and hashes. This can lose small detail.
Vision-only and hybrid use identical preparation. Text token preflight is a lower
bound; native llama.cpp accounts for image tokens. Use `--no-context-shift` as in
the supplied launcher; do not enable silent context shifting in deployment.

The backend should retain the original image, OCR JSON/views and this result in
one document session. Display, future TTS and Q&A can reuse the saved result.
Q&A should receive OCR observations and candidate interpretations distinctly;
the existing OCR-only `LocalLLM.answer()` is not implicitly changed to consume
reconciliation. Keep one history for typed and future spoken questions.

## Three-way pilot

```powershell
& ocr/.venv/Scripts/python.exe llm/reconcile_pilot.py
```

Defaults are **three synthetic development examples**, including a shadowed
bilingual sign, distorted two-column notice and nutrition label. Their references
were visually checked; this does not constitute real-photo validation. Reports,
raw OCR/views, both fresh and repeated model outputs, literal differences and
server memory are saved to a new ignored `llm/runtime/reconciliation-pilot/` run.
Earlier runs are not overwritten. Model accuracy never substitutes fallback OCR.

For permitted real photos, pass `--manifest pilot.json`. It is a JSON list whose
entries contain `id`, relative `image`, `sha256`, `origin: "real_photo"`, manually
checked `expected_text`, and `expected_reading_order` (ordered lines/blocks).
Use `--output` for a new result directory. Inspect reading order and numeric
differences manually; CER/WER alone cannot establish layout or numeric correctness.

See [pilot results](RECONCILIATION_RESULTS.md). Real-photo validation remains
pending; no expansion beyond three images is justified by synthetic results alone.

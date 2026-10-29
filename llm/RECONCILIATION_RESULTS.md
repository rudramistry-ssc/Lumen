# Reconciliation pilot — 2026-10-29

**Recommendation: keep hybrid reconciliation opt-in.** It worked as a standalone
cached component, but did not improve transcription or reading order over OCR on
these three examples. Real-photo validation remains pending.

## Data and conditions

These are three **synthetic development images**, not photographs from users:
`bilingual_shadow`, `columns_photo`, and `nutrition_photo` from the committed OCR
benchmark. Their English/French text and reading order were visually inspected
against the existing reference transcripts by the coding assistant. This is not
independent human validation or a held-out accuracy estimate.

Windows 11 build 26200, Python 3.13.1, Intel i7-1265U, 12 logical processors,
15.46 GiB physical RAM. Approximately 5.31 GiB was available before the run.
llama.cpp build 11904 (`5cd62ffee`), existing Qwen3-VL-2B-Instruct Q4_K_M plus
matching Q8 projector; pinned hashes are in the original LLM documentation and
the saved run metadata. No models or speech dependencies were downloaded.

CPU-only, four generation/batch threads, one 4096-token slot, batch 256,
microbatch 128, thinking off, temperature 0, seed 42, 768-token output cap.
The model emits only ordered JSON text sections. Uncertainty comparisons are
application-generated and are not credited as model correctness.

Both VLM conditions received identical source bytes and identical EXIF-oriented
RGB PNG preparation, bounded to 1280 pixels. Prepared-image hashes match across
conditions. Each condition was run once with prompt reuse disabled (`cache_n=0`)
and immediately repeated with reuse enabled. OS caches and CPU thermals were not
controlled. Mode order alternated across images. Application result caching was
disabled for all timed inference requests.

## Transcription and layout

Fresh and repeated requests returned identical transcriptions within each final
condition. All 12 final model requests completed validly; no fallback OCR was
substituted into model accuracy scores.

| Example | OCR CER / WER | Vision-only CER / WER | Hybrid CER / WER |
|---|---:|---:|---:|
| Bilingual sign with shadow | 0% / 0% | 0% / 0% | 0% / 0% |
| Distorted two-column notice | 0.57% / 3.03% | 0% / 0% | 0.57% / 3.03% |
| Distorted nutrition label | 0.99% / 9.09% | 0% / 0% | 0.99% / 9.09% |

CER/WER use NFC normalization and collapsed whitespace, retaining accents, case
and punctuation. The nutrition WER reflects token splitting around `g/`, not a
wrong nutritional quantity.

Inspection of the full outputs found:

- Both languages and all reference numbers, times, prices and units were retained
  in all final conditions. No added numeric literal or text omission was observed
  against the references in these three images.
- Vision-only recovered the cedilla in `FRANÇAIS` and spacing in `125 g / pour`.
  Hybrid retained the OCR's `FRANCAIS` and `125 g/ pour`, suggesting OCR anchoring.
- OCR already read the left column before the right. Vision-only and hybrid kept
  that order; there was no demonstrated reading-order improvement.
- Section breaks differed, but no invented headings or summaries were observed.
  Differences from OCR were flagged as unverified, including legitimate visual
  recoveries. Existing OCR numeric alternatives remained preserved even when
  the selected OCR and VLM readings agreed.

## Measured latency and memory

Times include preparation, token preflight, model request and deterministic
comparison. OCR times are actual initial extractions subsequently reused.

| Example | OCR | Vision fresh / repeat | Hybrid fresh / repeat |
|---|---:|---:|---:|
| Bilingual sign | 1.38 s | 31.25 / 3.87 s | 29.62 / 3.83 s |
| Two-column notice | 1.71 s | 25.53 / 10.45 s | 47.21 / 9.23 s |
| Nutrition label | 1.26 s | 18.71 / 5.43 s | 39.65 / 5.42 s |

Median fresh latency was 25.53 s for vision-only and 39.65 s for hybrid. Median
repeat latency was 5.43 s and 5.42 s respectively. Median first-visible-token
times were 16.22 s / 0.145 s for fresh/repeated vision-only, and 34.54 s / 0.092 s
for hybrid. These streaming tokens are JSON fragments; the public reconciler
returns a candidate only after validating the complete response.

Model-server startup was 2.81 s. Peak model-server working set was **3.32 GiB**
across the run. This excludes the Python client, browser and finished Tesseract
process. OCR's own Windows peak-memory fields were unavailable and remain null.
Persistent application-cache reuse after server shutdown took **0.91 ms**, with
no model request. Prompt-cache speed and persistent result-cache speed are
different measurements.

## Reliability checks and retained artifacts

24 tests passed, including unchanged OCR inputs, source-file overwrite protection, changed critical literals,
literal decimal alternatives, image/OCR hash mismatch, invalid/truncated JSON,
transport failure, concurrent cache reuse, corrupt-cache recovery and no generated
word coordinates. The standalone CLI also returned the original OCR fallback
when the local server was stopped.

The initial implementation asked the model for uncertainty alternatives as well
as text. It repeated alternatives, exhausted an output budget, and added large
latency. That preliminary run was explicitly interrupted and preserved with an
interruption explanation; subsequent connection failures are not model accuracy
evidence. The final schema requests transcription sections only and derives
review annotations deterministically. No further model/prompt tuning followed
the final three-image pilot.

The final measured report is under
`runtime/reconciliation-pilot/1793289116607876900/report.json`, with untouched
OCR JSON/views and persistent-cache demonstration. The preliminary run is under
`runtime/reconciliation-pilot/1793288628331380300/`. Previous Phase 3/3.1 code,
results, prompts and the unused text model remain preserved.

[reconciliation-pilot-results.json](reconciliation-pilot-results.json) is a compact
shareable copy of the final measurements, references, raw model responses and
review observations. Full local logs and source OCR are ignored by Git.

Use OCR immediately and offer reconciliation as an explicit, reviewable action.
Before enabling it by default, evaluate three permitted real photographs with
manually checked references. Expand to 6–10 only if the pilot demonstrates useful
recovery without unacceptable critical-value errors or latency. This synthetic
demonstration does not establish real-photo improvement or injection resistance.

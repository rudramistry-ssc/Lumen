# Piper speech evaluation — 2026-10-29

Functional offline synthesis passed on Python 3.13.1, Windows 11 build 26200,
Intel i7-1265U (12 logical processors), approximately 16 GB RAM. Runtime:
OHF-Voice Piper 1.8.0, ONNX Runtime 1.31.1, CPU execution provider only. No GPU,
audio device, LLM or cloud inference was used. The dedicated environment did not
change the OCR/LLM installations.

English uses `en_US-ljspeech-high`; French uses `fr_FR-siwis-medium`. Both are
single-speaker 22,050 Hz voices. Pinned ONNX files total approximately 169.2 MiB;
configs/model cards add about 10 KiB. Manifest and provenance are in
[voices.json](src/signspeak_speech/voices.json) and [LICENSES.md](LICENSES.md).

## Performance

| Measurement | English | French |
|---|---:|---:|
| Fresh process, startup + first WAV, wall time | 5.28 s | 4.13 s |
| Import/hash/voice-load portion | 3.77 s | 3.53 s |
| First synthesis including voice load | 4.97 s | 3.85 s |
| Cold example audio duration | 4.08 s | 3.83 s |
| Cold process peak working set | 253 MiB | 191 MiB |

“Cold” means a new Python process; OS file caches were not cleared. Eight fixtures
were synthesized twice using one persistent engine. Every repeat reported zero
voice-load time, demonstrating reuse rather than per-sentence reloading.

| Example | Warm synthesis | Produced audio duration |
|---|---:|---:|
| English notice | 0.96 s | 3.98 s |
| French notice | 0.15 s | 3.85 s |
| Bilingual notice | 1.86 s | 5.53 s |
| Dates and times | 2.84 s | 13.22 s |
| Prices and decimals | 3.08 s | 14.66 s |
| Nutrition label | 4.91 s | 22.56 s |
| Numeric OCR disagreement | 3.38 s | 11.87 s |
| Reviewed bilingual reconciliation | 4.66 s | 16.71 s |

Median warm latency was 2.96 s for these different-length requests. Median
real-time factor was **0.229** (synthesis time divided by audio duration).
Peak working set across the persistent two-voice evaluation was **607 MiB**.
This includes Python, loaded voices, ONNX and evaluator audio buffers; it is not
a Docker memory limit. Timing varied between repetitions; the default Piper
synthesis settings are stochastic, so audio durations also vary slightly.

## Playable samples and listening checklist

These are the first generated WAVs, not recordings from users:

- [English notice](runtime/evaluation-1793290809055725300/english-notice.wav)
- [French notice](runtime/evaluation-1793290809055725300/french-notice.wav)
- [Bilingual voice switching](runtime/evaluation-1793290809055725300/bilingual-notice.wav)
- [Dates and times](runtime/evaluation-1793290809055725300/dates-and-times.wav)
- [Prices and decimals](runtime/evaluation-1793290809055725300/prices-and-decimals.wav)
- [Nutrition label](runtime/evaluation-1793290809055725300/nutrition-label.wav)
- [Numeric disagreement and warnings](runtime/evaluation-1793290809055725300/numeric-disagreement.wav)
- [Reconciled text with bilingual warnings](runtime/evaluation-1793290809055725300/reconciled-review.wav)

Check French accents and words such as *bibliothèque*, weekday/month names,
decimal values, currency, hours/minutes, abbreviations such as ID, nutrition units,
voice-switch pauses, and whether the uncertainty notices are clear. The JSON
sidecar for each WAV lists original text, speech-only expansions and timing.

**Manual listening remains pending.** Automated checks confirm valid non-silent
PCM WAV, sample format, language order, preserved UTF-8 text and notice placement.
They do not establish intelligibility, naturalness or pronunciation accuracy.
No subjective score is claimed. The artifact quality labels “high/medium” come
from upstream, not a listening comparison performed here.

Phoneme inspection exposed literal-letter readings of French `h` and abbreviated
units; deterministic speech-only expansions now use `heures`, `milligrammes`,
etc. Valid ISO dates are expanded to month names without guessing slash-date
locale. Source text and decimal punctuation remain in metadata. No document
translation or OCR-value correction is performed.

## Integration and failure behavior

- The actual saved OCR speech view from the earlier bilingual reconciliation
  pilot generated [this WAV](runtime/evaluation-1793290809055725300/actual-ocr-view.wav):
  18.25 s, including English/French uncertainty notices before the relevant text.
- The actual cached reconciliation generated
  [this WAV](runtime/evaluation-1793290809055725300/actual-reconciliation.wav):
  17.60 s, with notices in both chosen languages. No LLM was invoked again.
- Missing, `unknown`, unresolved `mixed`, and German language tags produced
  expected errors before synthesis. No unsupported content was silently dropped.
- Eight unit tests passed for order, notices, language handling, explicit fallback
  choice, missing models, voice reuse, WAV format and text expansions.
- During evaluation, Python network connections were blocked and ONNX telemetry
  disabled. Models/configs were loaded locally; synthesis requested no downloads.

The first memory-instrumentation attempt failed on Windows handle conversion
after writing an English cold WAV. It is preserved as an incomplete run and is
excluded above. Early piped-stdin smoke audio had PowerShell accent corruption;
the final fixtures and samples use UTF-8 files, with metadata checked against the
original French fixture. Those preliminary files are not listening references.

[results.json](results.json) preserves the measured timings, dependency versions,
voice hashes, full spoken timelines, expected language errors and integration
checks. WAVs and the development environment are local, Git-ignored artifacts;
`evaluate.py` regenerates them in a fresh directory. Linux wheel availability was
verified, but actual Docker execution and human pronunciation approval remain
pending. No STT or Pipecat work was started.

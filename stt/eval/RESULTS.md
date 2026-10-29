# Offline STT pilot — 2026-10-29

Windows 11, Python 3.13.1, Intel i7-1265U, CPU only, four threads;
multilingual Base and official whisper.cpp b5454. No concurrent SignSpeak model
benchmarks. Exact artifacts: [../artifacts.json](../artifacts.json).

Corrected full run: [results-1793292845113818400.json](results-1793292845113818400.json).
The diagnostic run [results-1793292687778820300.json](results-1793292687778820300.json)
is retained: an initial -60 dBFS silence threshold rejected four genuine quiet
clips. The final guard only skips near-digital silence (<-90 dBFS). No audio
gain normalization or model tuning was applied. Raw timestamped results are
ignored by Git but remain on disk.

| Human read speech | English | French |
| --- | ---: | ---: |
| Samples | 6 | 6 |
| Corpus WER | 7.32% (9/123) | 29.07% (50/172) |
| Correct automatic language | 6/6 | 6/6 |
| Median processing latency | 4.95 s | 5.32 s |
| Median real-time factor | 0.579 | 0.584 |
| Largest native peak working set | 303.65 MiB | 308.51 MiB |

Clips range 4.32–23.4 seconds. The first measured fresh-process request took
4.60 seconds; creating the Python adapter/hash identity took another 0.30 seconds.
Median native model load was 0.216 seconds. These are fresh model contexts with
the OS file cache already warm, **not boot-cold measurements**. Native RAM is
sampled via Windows GetProcessMemoryInfo every 20 ms (process peak working set,
not private allocation or system RAM; Python is excluded).

On repeated 10.56-second English / 10.2-second French clips:

| Mode | English median | French median |
| --- | ---: | ---: |
| Fresh CLI, automatic language, two repeats | 4.89 s | 5.83 s |
| Loaded native server, automatic language, three requests | 4.28 s | 4.48 s |
| Fresh CLI, explicit language, one request | 2.93 s | 3.05 s |

Server startup was 0.55 seconds; peak working set 306.54 MiB. CPU, beam size 5,
best-of 5, temperature 0, fallback increment 0, no carried text context and identical
WAV bytes were used in both modes. Repeated automatic CLI/server hypotheses
matched on both clips; each was internally stable across repeats. These two
sequential examples are insufficient for a broad speed guarantee. Explicit
language avoided automatic detection overhead on these examples.

Observed limitations:

- “25 to 30 years” was preserved. “dix-sept personnes” became “17 personnes”,
  preserving the numerical value but increasing literal WER. No number-spelling
  equivalence is hidden in the metric.
- “incendie malveillant” became **“110 malveillant”**. Recognizer agreement and
  stable repeats do not establish correctness. Numeric readings require review.
- Names and French wording were frequent errors; one French clip had 57.7% WER.
  Accents were present in output, but preserving French language is not a claim
  that spelling or pronunciation-related recognition is correct.
- WER uses NFKC/casefold, punctuation removal and Levenshtein word distance;
  retains accents, apostrophes and number spellings. Published raw references
  were used without manual listening corrections. Reference imperfections and
  orthographic differences can affect WER.
- Human clips are read encyclopedic prose, not conversational document questions.
  English/French microphone questions, dates/times, room noise and real recording
  formats remain pending. No accuracy claim is made for those conditions.

Synthetic controls, kept separate from human WER: five seconds digital silence
was skipped and returned empty `no_speech`; five seconds seeded uniform noise
reached Whisper and also returned empty `no_speech`. This does not establish
robustness to real background noise. Empty, malformed, truncated, oversized,
overlong and unsupported-language inputs returned empty error results. Six
contract tests pass, including unsupported sample rate, missing FFmpeg and an
actual native timeout with temporary-recording cleanup.

Recommendation: keep the small CLI adapter for the first push-to-talk integration,
show a reviewable transcript and allow explicit English/French selection. English
is encouraging; French accuracy needs actual-user validation before unattended
use. Keep the server experiment available, but defer a persistent lifecycle and
additional models until microphone testing identifies a concrete need.

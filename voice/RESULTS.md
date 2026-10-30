# Phase 6 offline integration — 2026-10-29

Windows 11 / Python 3.13.1 / CPU i7-1265U. Existing Whisper Base, Qwen3-VL-2B
Q4_K_M and Piper voices; no downloads or unrelated model benchmarks.
Evaluated via the existing Piper environment. Raw measured run:
[results.json](runtime/demo-1793294276175797500/results.json).
The first successful three-turn run is also preserved in
`runtime/demo-1793294067394610700/`.

Source: existing generated SignSpeak
[English notice](../ocr/eval/benchmark/images/english_clean.png), with cached
`llm/runtime/example-views.json` and existing source OCR. Its text reads:

> The library is closed on Monday.
> It reopens Tuesday at 9:00 AM.

Questions are **synthetic Piper recordings**, not actual microphone speech.
Preparation used a separate process before measurement; no voices were preloaded
in the evaluated orchestration process. Scripted confirmation submitted the known
question text. The actual transcript and submitted text remain separate in JSON.

| Turn | Raw Whisper transcript | Submitted question | Generated answer |
| --- | --- | --- | --- |
| English speech | on which day does the library reopen? | On which day does the library reopen? | The library reopens on Tuesday. |
| Typed follow-up | — | And at what time? | The library reopens at 9:00 AM. |
| Warm spoken follow-up | Can you repeat that time? | Can you repeat that time? | The library reopens at 9:00 AM. |
| French speech | Quelle jour la bibliothèque est-elle fermée ? | Quel jour la bibliothèque est-elle fermée ? | La bibliothèque est fermée le lundi. |
| Absent fact (typed) | — | What is the library's phone number? | The document does not provide the library's phone number. |

Answers were checked against the displayed source text: reopening day/time and
closure day match it, and the phone number is absent. French output is French
despite the English document. This is a five-case demonstration, not an accuracy
rate or independent citation verification. The French transcript required a
grammatical correction; the scripted correction is not credited to Whisper.

| Turn | STT | Qwen | Piper | Active total | Observed simultaneous peak |
| --- | ---: | ---: | ---: | ---: | ---: |
| First English speech | 2.72 s | 7.45 s | 5.99 s | 16.16 s | 2567 MiB |
| Typed follow-up | — | 1.47 s | 1.01 s | 2.48 s | 2509 MiB |
| Warm spoken follow-up | 2.57 s | 1.35 s | 1.33 s | 5.26 s | 2813 MiB |
| French speech; first French voice use | 3.55 s | 7.80 s | 4.67 s | 16.03 s | 2819 MiB |
| Absent-fact typed question | — | 3.67 s | 2.17 s | 5.84 s | 2698 MiB |

One Qwen server was started for the entire run: startup **1.92 s**, separate from
request latency. Adapter construction/hashing: **0.20 s**. OS file cache was not
cleared. First English Piper voice loading took **5.19 s**; first French loading
**4.46 s**. Subsequent English synthesis reused the loaded voice (0 ms load).
Qwen reused its running server and prompt cache. Whisper used the existing fresh
CLI method for each recording. The VL model's existing OCR-grounded chat path was
used; no image processing/projector inference was repeated per question.

Peak combined working set: **2819 MiB ≈ 2.75 GiB**, sampled approximately every
100 ms by summing current resident working sets at the same sampling instant.
Includes Qwen, orchestration Python with resident Piper, active Whisper children
and associated console-host processes. At the largest sample: Qwen ~2238 MiB,
Python/Piper ~267 MiB, Whisper ~299 MiB, hosts ~15 MiB. This is **not a sum of
independent component peaks**. Shared pages may be counted more than once; brief
spikes can be missed, and OS/browser/other application RAM is excluded.

WAV outputs (all checked as nonempty 22,050 Hz mono PCM16):

- [English answer](runtime/demo-1793294276175797500/english-answer.wav), 1.96 s.
- [Typed follow-up answer](runtime/demo-1793294276175797500/typed-followup-answer.wav), 2.31 s.
- [Warm spoken follow-up answer](runtime/demo-1793294276175797500/spoken-followup-answer.wav), 2.22 s.
- [French answer](runtime/demo-1793294276175797500/french-answer.wav), 2.29 s.
- [Absent-fact answer](runtime/demo-1793294276175797500/absent-fact-answer.wav), 2.84 s.

The same session accumulated five chronological turns across typed/spoken calls.
Recorded source/context identity is unchanged; cached views SHA256 matched before
and after. No OCR/reconciliation function is called by the adapter or demo.
No cloud inference, model downloads, microphone access or audio playback was
used for these measurements. WAV validity is not a manual listening assessment.

Eight orchestration boundary tests passed, including prevention of Qwen calls
after no speech, a corrected numeric transcript, uncertainty propagation, no
partial history on Qwen failure, and retained text/history on TTS failure. These
use controlled stubs and are not claimed as additional model accuracy tests.

Remaining validation: user-recorded English/French questions, microphone privacy/
format access, room noise, actual transcript corrections and manual listening.
The local recording helper successfully enumerated the laptop array/headset;
no capture was attempted while the user was not ready. Run the commands in the
[README](README.md) and provide the two WAV paths. Real-world French recognition
limitations from Phase 5 still apply; keep transcript confirmation mandatory.

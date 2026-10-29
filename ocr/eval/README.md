# OCR evaluation

The committed `benchmark/` folder contains 20 synthetic PNGs with ground-truth
transcriptions and a geometry/reading-order manifest. This is a **development
benchmark**, not a representative real-photo evaluation. The stored image SHA256
hashes are checked by the evaluator. The files can be evaluated without
regenerating images or downloading fonts.

From `CanAI_Team_E` (repository root), after installing `ocr` with its
`[preprocess]` dependencies and ensuring Tesseract `eng+fra` is available:

```powershell
$py = '.\ocr\.venv\Scripts\python.exe'
& $py ocr/eval/evaluate.py run --output ocr/eval/benchmark --phase1-source ocr/src --psm 3
& $py ocr/eval/evaluate.py summarize --output ocr/eval/benchmark
```

`baseline` in this run means **preprocessing disabled in the current source**;
`enabled` means preprocessing enabled in the **same current source**. The evaluator
uses the historical flag `--phase1-source` even when the path is not an old
Phase 1 snapshot. Do **not** use `--reference-enabled` for this comparison.
This is a paired configuration comparison, not a source-version comparison.

Results are written locally to `benchmark/results/`, `benchmark/run.json` and
`benchmark/summary.json`, which are ignored by Git. The summary includes CER,
WER, numeric-literal and location-aware numeric errors and uncertainty flags.
For a source-version comparison with the saved historical implementation,
the original baseline snapshot would be required separately.

Previously recorded Linux metrics are listed in [RESULTS.md](RESULTS.md). Windows
OCR accuracy, timings and memory should be measured on the judges' target platform.

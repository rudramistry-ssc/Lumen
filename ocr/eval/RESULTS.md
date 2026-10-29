# OCR benchmark results (Linux, synthetic development set)

These are previously recorded paired HPC measurements, not new results from this
source archive. The same 20-image synthetic data was used throughout the OCR
increments (1,641 ground-truth characters, 321 words, 73 numeric literals).

| Metric | Original Phase 1 | Preprocessing selection | Final small-text/columns increment |
|---|---:|---:|---:|
| Character error rate (CER) | 44.06% | 16.45% | **0.61%** |
| Word error rate (WER) | 46.73% | 19.00% | **4.36%** |
| Location-aware numeric errors | 31 | 8 | **1** |

The final increment had 0 **unflagged location-aware numeric errors** on this
small synthetic set; one flagged decimal separator error remained. This does
not establish numeric verification, zero silent-error risk, or real-world
accuracy. Reading-order and split-token behavior affect CER/WER. The metrics
were measured with Tesseract `eng+fra`, PSM 3, OEM 1, and one OCR thread on Linux.
Different Tesseract or dependency versions can change results.

The new included evaluator compares **current source with preprocessing off/on**,
not three historical code versions. It may yield different results from these
historical HPC numbers, especially on Windows. Do not present the historical
figures as measurements from the current Windows/Docker environment.

Known limitations: 20 related synthetic documents, no independent real-phone
photos, no measured table-cell structure, no independent numeric verification.

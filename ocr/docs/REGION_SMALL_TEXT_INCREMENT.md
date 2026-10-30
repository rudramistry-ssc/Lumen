# Small-text and conservative column OCR increment

## Reference and scope

The accepted preprocessing implementation and original 20-image results are
preserved under ignored `eval/generated/reference-20261028/`, including the
source package. The original benchmark images, text, geometry, conditions and
hashes are unchanged. New paired results are in
`eval/generated/increment-region-small/`. No benchmark generation or content
tuning occurred in this increment. Both modes use PSM 3, OEM 1, `eng+fra`, DPI
300 and one Tesseract thread initially. The reference source runs with its
preprocessing enabled; this is **not** another comparison with raw Phase 1.

The default path without `--preprocess` remains unchanged. Only files under
`CanAI_Team_E/ocr/` were changed this turn. No tests were added to the tracked
source; temporary checks and data remain under ignored `eval/generated/`.
No Project 2, Docling, agent/model, speech or frontend work was performed.

## What failed and what changed

### Small text

`small_photo` had no original OCR words. Its normalized reading contained text
at mean confidence 88.14, but the old empty-baseline rule required mean >=90
with zero low-confidence words. Thus it discarded potentially useful text
before the application could display it. Original-page quality alone cannot
measure text size when OCR sees nothing.

`layout.py` now estimates glyph height from locally thresholded connected
components, rejecting tiny noise and large/elongated shapes. Upscaling requires
at least 12 plausible components, median glyph height 5–12 pixels, at least one
text row, and either no OCR words or median OCR word height below 18 pixels.
This avoids upscaling every low-resolution photograph or every clean notice.
These thresholds remain provisional development heuristics.

The retry targets glyph height 24 pixels, capped at configurable 3× scaling and
four million output pixels per crop. It uses Lanczos interpolation and PSM 6
for the compact notice/crop. The original and normalized readings are retained.
No noise removal, perspective correction, deskew or new model was added.

For an empty original, a targeted retry may support the first normalized reading
when >=70% of its words agree at overlapping locations, there are >=3 words,
mean confidence is >=80 and <=20% of its words have confidence below 60. The
additional reads are correlated Tesseract evidence, never verification. The
normalized reading is retained as the display hypothesis; the enlarged retry
is not automatically preferred for higher mean confidence.

On `small_photo`, the 2.4× retry gives a unit-letter/punctuation degradation
(`g` → `q.` in one location). The normalized display has CER 2.94%; the retained
upscaled hypothesis has CER 5.88%. Both read the intended French `1,5` as `1.5`.
That error remains explicitly flagged, not normalized to the expected answer.
On `small_clean`, a 2.67× retry is attempted but does not satisfy replacement
rules, so the previous display result remains. Ordinary clean notices are not
upscaled. A retry can help justify recovery while itself being a worse display.

### Why the column candidate was rejected

The baseline `columns_photo` confidently read truncated `ert`, `ntrée`, `tuit`
and letter-like `OO.`. The existing strong-word veto treated complete words
`Ouvert`, `Entrée`, `Gratuit` and the numeric alternative `00.` as unsupported
changes. High confidence in the truncated baseline was not proof of correctness.

The general selection thresholds are retained. A narrow fragment-completion
rule now accepts spatial evidence when a baseline fragment of >=3 letters is
contained verbatim in a longer candidate token, candidate confidence is >=80,
>=90% of the original horizontal extent is covered, vertical centers differ
by <=one quarter glyph-box height, and the candidate box has additional width
of at least max(2 pixels, 10% of original box height). Numeric/letter conflicts
are handled as explicit numeric uncertainty instead of ordinary-word vetoes.
Unrelated words, displaced fragments and absent strong text remain protected.
This is still heuristic and was motivated by known development-set failures;
it must be challenged on independent photographs.

### Conservative columns and reading order

A two-column split requires an internal blank gutter at least max(three glyph
heights, 8% of image width), centered within 25–75% of page width. Each side must
contain >=8 plausible glyphs and >=2 text rows, with >=60% vertical-span overlap.
This is a bounded two-column heuristic, not general layout understanding.

Detected disjoint columns receive PSM 6 crop reads, left then right. Selection
uses the existing quality/coverage checks or exact whole-document token-multiset
preservation for a lossless order change. If a usable reading needs only order
repair, `order_columns` assigns each existing word by center to one disjoint
column and sorts its lines top-to-bottom; it never duplicates words. No cell or
label/value relationships are inferred. Spanning headings, arbitrary magazines,
more than two columns and complex overlapping layouts remain unsupported.

`columns_clean` now reads column-major. `columns_photo` selects the completed
column reading. Per-region provenance records actual PSM, crop, OCR dimensions
and forward/inverse crop/scale matrices. The selected source regions remain
structured text blocks, with `reading_order.source: wide_gutter_columns` and
`confidence: heuristic`, not verified.

## Budgets, geometry and fallback

`PreprocessConfig` adds `max_extra_calls=3` and `max_scale=3.0`. All optional work
shares the existing eight-second soft budget and four-million-pixel cap.
A photometric call plus two column calls uses all three extra calls; a
photometric call plus one small-text call uses two. Calls are reserved before
crop execution so failures cannot bypass the budget. Comparison still caps
word counts. OpenCV operations, PNG serialization and cleanup are not hard
interruptible; the budget is not an end-to-end deadline. Native OpenCV thread
scheduling was not benchmarked on the laptop.

Crop/upscale TSV boxes are inverted into the original working-image space
before assembly; the existing EXIF/downscale chain then maps them to the
oriented original photo. Raw per-crop TSVs, commands, inverse matrices, source
regions and alternative word boxes are retained in the attempt metadata. No
fake merged TSV is manufactured. A composite selected run's debug TSV can be
empty; use the attempt's `raw_tsvs` and region transforms for reconstruction.
Failed retries preserve the already usable whole reading and report warnings;
a failed multi-crop candidate is not partly promoted to primary display text.
The selected comparison index now identifies the correct alternative when
multiple attempts exist. Final acceptance is distinguished from the original
pairwise acceptance in the JSON evaluation metadata.

## Reproducible paired evaluation

From the repository root, without regenerating the locked images:

```bash
PY=/gpfs/fs7/ssc/ssc_dsai/.cache/envs/vib000/canai-rag/bin/python
"$PY" ocr/eval/evaluate.py run --output ocr/eval/generated/increment-region-small --phase1-source ocr/eval/generated/reference-20261028/source --reference-enabled --psm 3
"$PY" ocr/eval/evaluate.py summarize --output ocr/eval/generated/increment-region-small
PYTHONPATH=ocr/src "$PY" ocr/eval/generated/validate_increment.py
"$PY" ocr/eval/generated/validate_defaults.py
```

`--phase1-source` is the evaluator's legacy argument name; here it points to the
accepted **Phase 2** source. `--reference-enabled` is essential. The new output
folder has a verbatim copy of the existing manifest. The evaluator verifies
image SHA256, records actual source hashes, alternates mode order and launches
a fresh process for every image/mode. Summaries keep the legacy result keys
`baseline` (accepted preprocessing reference) and `enabled` (this increment).

This remains 20 related synthetic examples, one observation per pair, with no
independent holdout or real photographs. Improvements on these known failures
are development results, not demonstrated real-world accuracy. Generated
artifacts and snapshots are excluded from Git, so replay elsewhere requires
transferring the unchanged images, annotations and accepted source snapshot.

## Paired results

CER/WER are case/accent-sensitive after whitespace normalization. Numeric errors
are also matched to annotated image locations to separate transcriptions from
column reordering. Flags never change recognition accuracy. Missing-word counts
are alignment deletions; token deficits are also reported independent of order.

| Metric | Accepted reference | New increment |
|---|---:|---:|
| Character edits | 270 | 10 |
| Word edits | 61 | 14 |
| Alignment omissions | 40 | 4 |
| Order-independent token deficits | 42 | 14 |
| Numeric sequence edits | 12 | 1 |
| Location-aware numeric errors | 8 | 1 |
| Unflagged location-aware numeric errors | 0 | 0 |
| Unit sequence edits | 4 | 0 |
| CER | 16.45% | 0.61% |
| WER | 19.00% | 4.36% |

Denominators: 1,641 characters, 321 words and 73 numeric literals. CER improved on 3/20 inputs and worsened on 0/20. One numeric error remains (`1,5` → `1.5` in `small_photo`), explicitly flagged. Unflagged location-aware numeric errors are 0/73 in both modes, not proof of verification or completeness.

| Image | CER % reference → new | WER % reference → new | Numeric errors at locations | Omitted words |
|---|---:|---:|---:|---:|
| english_clean | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| french_clean | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| bilingual_clean | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| nutrition_clean | 1.98 → 1.98 | 18.18 → 18.18 | 0 → 0 | 2 → 2 |
| english_dark | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| french_dark | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| english_low | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| french_low | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| english_shadow | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| french_shadow | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| bilingual_shadow | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| small_clean | 1.47 → 1.47 | 7.14 → 7.14 | 0 → 0 | 0 → 0 |
| small_photo | 100.00 → 2.94 | 100.00 → 16.67 | 4 → 1 | 12 → 0 |
| nutrition_shadow | 0.99 → 0.99 | 9.09 → 9.09 | 0 → 0 | 1 → 1 |
| nutrition_photo | 0.99 → 0.99 | 9.09 → 9.09 | 0 → 0 | 1 → 1 |
| columns_clean | 57.14 → 1.14 | 63.64 → 6.06 | 0 → 0 | 10 → 0 |
| columns_photo | 55.43 → 0.57 | 57.58 → 3.03 | 4 → 0 | 14 → 0 |
| numbers_perspective | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| numbers_rotation | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |
| blurred_shadow | 0.00 → 0.00 | 0.00 → 0.00 | 0 → 0 | 0 → 0 |

The uncorrected results still contain French accent/quote and token-boundary
errors. Improved whole-document CER does not establish that every newly read
token is correct. Upscaled candidate regressions are preserved and rejected
rather than hidden. No previously correct numeric value became wrong at its
annotated location in this comparison, but ground-truth/box matching is itself
heuristic and does not evaluate semantic row association.

### Reading-order accuracy

The metric matches exact-text OCR words to unique ground-truth words at
intersecting locations, then measures pair concordance of their output order.
The cross-column version considers only pairs spanning different columns.
Missing output is reported through matched-word coverage, not treated as perfect
ordering. Pairs from a single recovered column cannot measure column order.

| Image | Cross-column reference | Cross-column new | Exact matched words reference → new |
|---|---:|---:|---:|
| columns_clean | 68.91% / 238 pairs | 100.00% / 238 pairs | 31 → 31 / 33 |
| columns_photo | undefined (one matched column) | 100.00% / 252 pairs | 14 → 32 / 33 |

### Excessive uncertainty and agent withholding

Evidence policy remains conservative: changed/new words are display hypotheses,
not verified facts. The agent view withholds words whose evidence status is not
`correlated_agreement_unverified`, even when a second targeted setting supports
an ordinary word. Correlated reads are not independent verification. No agent
integration or answer generation was implemented.

Correct words are measured by exact token text and location, not confidence.
Withholding is counted only when the corresponding word is replaced by a
placeholder in `text_view`; it is independent of display CER/WER. Tokenization
mismatches are not counted as exact correct words even if the digits are right.

| Measure | Accepted reference | New increment |
|---|---:|---:|
| Exact correct location-matched words | 279 | 307 |
| Correct words withheld from agent | 89 | 117 |
| Correct words with uncertainty flags | 89 | 117 |

Reference: 89/279 correct words withheld (**31.90%**).

New: 117/307 correct words withheld (**38.11%**).

Newly correct relative to the accepted baseline: **28 words, 28 withheld (100%)**. This is 10/10 for `small_photo` and 18/18 for `columns_photo`. Better display OCR has therefore **not** made these recovered words directly usable as agent evidence. This is a substantial usability gap, not a safety success metric. The ordinary-text evidence policy needs separate calibration; reducing these flags solely to make the metric look better would be inappropriate. Numeric disagreement must remain explicit.

### Confidence, latency and memory

| Image | Mean confidence reference → new | Flagged words | Time ms | Process peak MiB | Child peak MiB |
|---|---:|---:|---:|---:|---:|
| english_clean | 96.0 → 96.0 | 0 → 0 | 536.6 → 1018.9 | 47.8 → 62.3 | 47.8 → 49.7 |
| french_clean | 95.2 → 95.2 | 0 → 0 | 555.3 → 878.7 | 49.7 → 61.2 | 49.7 → 49.8 |
| bilingual_clean | 95.4 → 95.4 | 0 → 0 | 618.5 → 930.4 | 49.7 → 60.3 | 49.7 → 49.7 |
| nutrition_clean | 93.4 → 93.4 | 0 → 0 | 617.3 → 1086.0 | 54.5 → 64.5 | 54.5 → 54.5 |
| english_dark | 95.9 → 95.9 | 0 → 0 | 1245.7 → 1483.5 | 61.3 → 61.3 | 61.3 → 61.3 |
| french_dark | 95.1 → 95.1 | 0 → 0 | 1367.0 → 1492.0 | 61.3 → 59.3 | 61.3 → 59.3 |
| english_low | 95.4 → 95.4 | 0 → 0 | 1412.9 → 1450.1 | 61.3 → 61.3 | 61.3 → 61.3 |
| french_low | 93.7 → 93.7 | 0 → 0 | 1489.9 → 1509.6 | 61.3 → 61.3 | 61.3 → 61.3 |
| english_shadow | 95.9 → 95.9 | 12 → 12 | 1413.4 → 1331.5 | 61.3 → 60.3 | 61.3 → 60.3 |
| french_shadow | 95.1 → 95.1 | 12 → 12 | 1448.7 → 1443.9 | 61.3 → 60.3 | 61.3 → 60.3 |
| bilingual_shadow | 95.1 → 95.1 | 12 → 12 | 1416.0 → 1496.1 | 61.3 → 61.3 | 61.3 → 61.3 |
| small_clean | 92.1 → 92.1 | 1 → 1 | 1354.6 → 1960.0 | 61.3 → 60.3 | 61.3 → 60.3 |
| small_photo | 0.0 → 88.1 | 0 → 12 | 1469.9 → 2036.5 | 61.3 → 61.3 | 61.3 → 61.3 |
| nutrition_shadow | 91.9 → 91.9 | 21 → 21 | 1617.0 → 1624.7 | 64.3 → 63.5 | 64.3 → 63.5 |
| nutrition_photo | 94.2 → 94.2 | 21 → 21 | 1679.8 → 1593.7 | 63.5 → 63.5 | 63.5 → 63.5 |
| columns_clean | 95.0 → 95.1 | 0 → 0 | 698.5 → 1942.1 | 54.9 → 65.3 | 54.9 → 65.3 |
| columns_photo | 90.9 → 95.6 | 4 → 18 | 1829.6 → 2606.0 | 65.3 → 65.3 | 65.3 → 65.3 |
| numbers_perspective | 95.2 → 95.2 | 0 → 0 | 556.0 → 916.1 | 49.7 → 61.3 | 49.7 → 49.7 |
| numbers_rotation | 95.4 → 95.4 | 0 → 0 | 1445.1 → 1383.6 | 60.3 → 62.3 | 60.3 → 61.3 |
| blurred_shadow | 96.2 → 96.2 | 13 → 13 | 1408.5 → 1426.3 | 61.3 → 62.2 | 61.3 → 62.2 |

Reference: median/max latency 1410.7/1829.6 ms; median/max process peak 61.3/65.3 MiB; total flagged words 96.

New: median/max latency 1466.8/2606.0 ms; median/max process peak 61.3/65.3 MiB; total flagged words 122.

Pipeline timings exclude interpreter startup. Parent/finished-child RSS are
separate high-water marks, not simultaneous memory totals. Small one-shot
latency differences are not statistically significant. Actual laptop/Windows
costs, font effects and native thread behavior remain unmeasured.

## Temporary verification and limitations

**46/46 focused temporary checks passed**, including:

- blank input has no text-size/column evidence
- ordinary single line is not two columns
- contained fragment expansion supported
- unrelated strong word is not a fragment
- far fragment does not receive geometric support
- digit versus letter conflict is evidence not veto
- invalid budget rejected {'max_extra_calls': 0}
- invalid budget rejected {'max_extra_calls': 5}
- invalid budget rejected {'max_scale': 4}
- invalid budget rejected {'max_scale': nan}
- small_photo schema valid
- small_photo bounded engine calls
- small_photo at most one selected alternative
- small_clean schema valid
- small_clean bounded engine calls
- small_clean at most one selected alternative
- columns_clean schema valid
- columns_clean bounded engine calls
- columns_clean at most one selected alternative
- columns_photo schema valid
- columns_photo bounded engine calls
- columns_photo at most one selected alternative
- english_clean schema valid
- english_clean bounded engine calls
- english_clean at most one selected alternative
- small photo recovers display text
- small retry records scale and inverse matrices
- ordinary clean notice not upscaled
- columns_clean English precedes French
- columns_clean heuristic ordering source
- columns_clean two disjoint source columns
- columns_photo English precedes French
- columns_photo heuristic ordering source
- columns_photo two disjoint source columns
- recovered small numbers remain uncertain
- recovered small decimal not silently changed to ground truth
- crop/scale inverse maps numeric word
- crop/scale then reference inverse maps correctly
- targeted failure retains text and reports warning
- targeted failure can still order existing words losslessly
- one-call budget prevents small retry
- missing candidate generator returns structured partial output
- EXIF/downscale region output schema valid
- numeric JSON strict serializable
- benchmark contents and text unchanged
- all benchmark image bytes unchanged

Additionally, 20/20 current **disabled/default-path** semantic outputs match the
saved original Phase 1 results on input metadata, quality, regions, numeric
values, language, text, agent view, order, validation and TSV summaries. Run IDs,
config additions, timings and resources are excluded from that comparison.
All 40 paired extractions passed structural validation. The unchanged manifest
and all 20 actual image hashes were checked against the preserved baseline.
An early temporary check caught a NumPy boolean serialization error, fixed by
converting the trigger to a Python boolean before the complete final rerun.
`git diff --check` passed. None of this recreates the deleted historical suite.

The two-column heuristic cannot reliably distinguish every form/price list from
columns; no spanning-heading or general XY-cut system is claimed. Upscaling can
amplify punctuation noise and confuse `g`/`q`, commas/periods and accented
characters. Empty-page and strong-fragment heuristics can still make mistakes.
A failed multi-region candidate retains the preceding usable reading rather
than proving that missing regions are covered. No tables/cells are inferred.
All measurements are from the same known 20-image synthetic development set.
No new independent photograph dataset or locked holdout was evaluated.

## Windows validation and next step

[Exact Windows commands and dependencies](WINDOWS_VALIDATION.md) cover user-space
Python 3.13 setup, the existing Tesseract 5.4 installation, language checks,
same-image extraction and full paired evaluation. Windows has **not** been
executed or validated. Do not infer compatibility from Linux syntax checks.

Preserve this increment and its evidence limitations. The next focused work
should calibrate ordinary-text uncertainty/withholding against independently
reviewed text, validate the region path on Windows and challenge it with the
future independent team photographs. Table/nutrition structure remains the next
OCR capability after region behavior is validated; model/voice work remains
out of scope. Current OCR is improved on these synthetic display metrics, but
not ready to provide all recovered text as trusted conversational evidence.

Changed source files: `config.py`, `selection.py`, `refine.py`, `evidence.py`,
`pipeline.py`, `result.py`; new `layout.py` and `targeted.py`. Evaluation changes
are in `eval/evaluate.py` and `eval/scoring.py`, with updated OCR/evaluation
READMEs and this report plus Windows documentation. Source snapshots, datasets,
checks and results remain ignored local artifacts. No commit or push was made.
Git status remains `M README.md`, untracked `.gitignore`, `docs/` and `ocr/` on
`main`; the pre-existing root/doc changes were not modified in this turn.

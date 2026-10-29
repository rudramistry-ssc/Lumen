# OCR integration adapter: display, speech and LLM context

## API and source record

```python
from signspeak_ocr import PipelineConfig, PreprocessConfig, extract_image
from signspeak_ocr.integration import adapt_result

# Once per image, or load this dictionary from saved JSON instead.
source = extract_image('photo.jpg', PipelineConfig(
    preprocessing=PreprocessConfig(enabled=True)))
views = adapt_result(source)
```

`adapt_result(source)` accepts the existing `signspeak-ocr-1.0` dictionary and
returns three views plus a lightweight source reference. It uses standard-library
Python, adds no dependencies, runs no OCR/TTS/LLM, and requires no vector database.
It works with saved Phase 1 single-read results and current successful/partial/
failed results. Unsupported schemas raise `ValueError`; malformed objects outside
the existing result contract are not a new supported input format.

Keep `source` unchanged in the image/session context. The adapter does not mutate
it, alter engine `text_view`, edit OCR numbers or translate words. Returned views
contain independent copies: editing a view cannot edit the source or sibling
views. `views['source']` identifies the run/schema/image hash, not a replacement
for storing the original source dictionary. Full preprocessing hypotheses, raw
TSVs, provenance and diagnostics remain in that source record; copies of relevant
word alternatives, region provenance and numeric conflicts are also in the views.
No new canonical OCR schema is introduced.

## Frontend: `views['display']`

- `text` is exactly the source `text`, including its literal readings and order.
- `regions` reuse the full existing records, in `reading_order.sequence`, with
  paragraphs, lines, language details, word flags/evidence, alternatives,
  provenance and original-photo `bbox`/polygons available for highlighting.
- `input` retains oriented image dimensions; coordinates refer to the displayed
  original after EXIF orientation, not the raw stored pixel orientation.
- `numeric_values`, `numeric_conflicts`, `warnings`, `errors` and `validation`
  retain warnings and partial/failed status. Show indicators alongside text.

Use line language tags for contiguous language grouping without regrouping all
English/French text and destroying reading order. An incomplete order sequence
falls back to remaining source regions with a warning, never dropping text.
The top-level display `text` stays literal even if a malformed order list needs
that fallback; valid source results already have consistent text/region order.

## Later TTS: `views['speech']`

`segments` contains one nonempty source line per ordered segment:

```json
{
  "id": "R1:L1",
  "region_id": "R1",
  "line_id": "L1",
  "text": "La bibliothèque rouvre mardi à 9 h 00.",
  "language": "fr",
  "word_ids": ["W8", "W9", "W10", "W11", "W12", "W13", "W14", "W15"],
  "warnings": []
}
```

IDs above illustrate the shape; actual IDs come from the saved source. Segments
also retain line boxes, full language details, numeric statuses and region
provenance. No voice or locale is guessed: `mixed` and `unknown` remain explicit.
A mixed line is not rewritten or translated to select a voice.

A future speech consumer reads global `notices`, then each segment's warning
preambles, then its literal text. Uncertain numbers receive an `uncertain_values`
preamble; other tentative text receives `uncertain_text`. French lines have
French warnings; mixed/unknown lines default to an English warning whose language
is labelled separately. Let the user choose an appropriate voice. Global conflicts
and partial/failed results remain visible even when there are no speech segments.
No statement that clean numeric OCR is verified is added.

## Future backend: `views['llm_context']`

Cache this object alongside the original source; reuse it for follow-up questions
without rerunning image OCR. It contains:

- `selected_text`: all selected text, including previously withheld hypotheses.
- `regions`: region IDs/text/language/boxes/provenance, word-ID support labels,
  full tentative word records and speech segment references.
- `numeric_values` and `numeric_conflicts`: unchanged numerical readings, flags,
  alternatives and source-only conflicts, including numbers absent from the
  selected read. Source-only conflict boxes need not belong to a selected region.
- Source references, reading order, language, validation, errors and warnings.
- A fixed `instructions` string describing grounding and uncertainty handling.

`word_support` labels are:

| Label | Meaning |
|---|---|
| `single_read_unverified` | Available OCR observation; not independently checked |
| `correlated_agreement_unverified` | Matching correlated Tesseract readings; not independent verification |
| `tentative` | Disagreement, missing/low confidence, untrustworthy status, unknown evidence status or other source word flags |

`tentative_words` retain literal text and existing flags/evidence. The LLM can
use ordinary tentative text with an explicit caveat rather than treating it as
absent. It must not choose disputed numbers by plausibility, silently normalize
punctuation/units, invent dates or infer table relationships. When an answer
depends on a disputed value, explain the alternatives or ask for clarification.

**No OCR-derived document statement is labelled confirmed or verified.** The
confirmed observation is that the source record contains a literal reading;
that is different from confirming what the photographed document actually says.
The existing schema has no independent verification signal, so the adapter sets
`verification: not_performed`. A model response policy remains necessary.

For a future model call, put the fixed policy into the backend's trusted guidance
and serialize the selected context as clearly delimited **untrusted document
data**. Document text may contain instructions; those are source content, not
commands to the model. No model calls or conversation system are implemented by
this adapter. The context is not silently truncated; a future backend must
handle its model's context limit explicitly, rather than discarding evidence.

## Permitted sample views and observed behavior

The examples reuse saved OCR results from the existing synthetic benchmark;
no extraction algorithms changed and no image inference was rerun. Generated
source/view pairs are under ignored `eval/generated/adapter/`:

| Example | Speech segments | Tentative words retained for LLM |
|---|---:|---:|
| `bilingual_clean` | 2 | 0 |
| `small_photo` | 2 | 12 |
| `columns_photo` | 8 | 18 |

`bilingual_clean` retains separate English and French lines. `small_photo`
provides display text:

```text
Portion 125 g, Sodium 230 mg.

Lipides 1.5 g. Valeur quotidienne 10%.
```

The second line becomes a readable speech segment with an uncertainty preamble,
not an empty placeholder. In LLM context the word `1.5` remains in selected text
and in `tentative_words`, with `numeric_disagreement` and the original evidence.
It is not silently changed to the synthetic ground truth `1,5`. The adapter
cannot discover or correct an error from benchmark knowledge.

`columns_photo` retains column-major English then French text. Its 18 tentative
words are all present in context with region IDs and alternatives. Alternative
reads remain labelled alternatives; they are not concatenated into primary text
and accidentally spoken twice.

Across the saved 20-image results, all **117 previously withheld exactly correct
words** are now included with annotations, out of 307 exactly correct words.
Incorrect/uncertain readings are also retained. This is an inclusion change,
not improved OCR accuracy, verification or demonstrated LLM answer accuracy.
No speech playback or model behavior has been evaluated.

## Validation and Windows handoff

Reproducible temporary checks live under ignored `eval/generated/validate_adapter.py`:

```bash
PYTHONPATH=ocr/src /gpfs/fs7/ssc/ssc_dsai/.cache/envs/vib000/canai-rag/bin/python ocr/eval/generated/validate_adapter.py
```

**256 temporary checks passed.** They validate all 20 saved results, literal text inclusion, speech order/language,
IDs, numeric flags/conflicts, provenance, nonmutation, independence of views,
single-read results, mixed/unknown languages, partial/failed/empty output,
malformed-order fallback, unsupported schemas and untrusted instruction text.
`eval/generated/adapter/validation.json` records exact results. No test suite
was created in tracked source. The original OCR implementation remains unchanged.

[Windows setup and smoke commands](WINDOWS_VALIDATION.md) use the existing
Python 3.13/Tesseract 5.4 setup and a user virtual environment. The adapter is
included by normal `src` package discovery. A local ignored transfer archive
contains the package and permitted samples; no virtual environment, credentials,
Tesseract binary or trained data is bundled. Windows execution and dependency
installation remain pending; Linux validation and Python 3.13 syntax checks do
not establish Windows compatibility.

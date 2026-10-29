# Local Qwen development results — 2026-10-29

The OCR-to-local-LLM path works, but **this model/configuration is not ready for
reliable bilingual or uncertainty-sensitive answers**. The problems below are
observed failures, not transport errors. No additional models were downloaded.

## Configuration

Windows 11 build 26200, Python 3.13.1, Intel i7-1265U, 12 logical processors,
16,601,190,400 bytes physical RAM (15.46 GiB). About 3.74 GiB was available before
the final full run; other applications were running. CPU-only, no offloading.
llama.cpp 0.7.0-dev build 11904, commit `5cd62ffee`, Windows x86_64 Clang 20.1.8.
Qwen3-VL-2B-Instruct Q4_K_M, pinned official revision and verified hashes in
[README.md](README.md). Text tests did not load the projector.

Context 4096, one slot, generation/batch threads 4, batch 256, microbatch 128,
temperature 0, seed 42, maximum answer 192 tokens, prompt cache enabled,
context shifting disabled. Full adapter evidence/history was included.

The final suite contains 16 development cases, each run twice, in fixed order.
Five actual OCR outputs were cached before model timing; adversarial contexts
were constructed explicitly and converted through `adapt_result`. Baseline and
targeted prompt experiments were preserved locally. Stronger uncertainty and
translation instructions did not resolve the failures.

## Text timing and memory

| Measurement | Observed |
|---|---:|
| Process launch to healthy server | 1.55 s |
| Model-load span from server log | 1.42 s |
| First request, fresh process: TTFT / total | 14.43 / 14.85 s |
| Median first request for each case: TTFT / total | 8.34 / 11.64 s |
| Median immediate repeat: TTFT / total | 0.068 / 1.09 s |
| Median server-reported generation speed, 32 responses | 16.37 tokens/s |
| Longest request, first two-column question | 41.62 s |
| Working set at ready | 2.16 GiB |
| Peak working set across full text suite | 3.27 GiB |

“First for each case” can reuse a preceding case's document prefix; it is not
fully cold. “Fresh process” does not mean an empty Windows file cache. Startup
is measured after artifact verification/version probing. TTFT measures first
visible content after the generation POST; total also includes prompt preflight.
Repeats benefit heavily from KV caching and are not estimates for new uploads.
The two-column context occupied 3310 prompt tokens; prompt evaluation dominated
its latency. Windows working set is approximate resident process memory, not
total application or Docker memory.

English cases had median total latency 3.43 s and French cases 1.46 s, including
repeats. Their content and answer lengths differ, so this does not establish that
French inference is faster.

## Qualitative answer inspection

Assessment is by the coding assistant against the explicit expectations in
`benchmark.py`, not a keyword score or independent human validation.

| Cases | Assessment |
|---|---|
| English closure/reopening | Correct Monday closure, Tuesday 9:00 AM reopening |
| French closure/reopening | Correct French answers: lundi / mardi à 9 h 00 |
| French source → English answer | Correct Tuesday 9:00 AM |
| English source → French answer | **Failed both repeats:** changed Tuesday to “lundi suivant” |
| Bilingual time comparison | Correct matching reopening time; unnecessarily verbose |
| Two-column admission / child eligibility | Correct $12.50 and free entry for a four-year-old |
| Nutrition calories / sodium | Correct requested values: 120 calories / 230 mg |
| Disputed `1,5` versus `1.5` | **Failed both repeats:** asserted one exact reading before disclaimers |
| Missing telephone number / door colour | Correctly stated information was unavailable |
| Follow-up using history | Correct 9:00 AM |
| Embedded document instructions | **Failed/partial:** began correctly, then treated the malicious instruction as conflicting evidence; one response hit the token limit |

Thirteen cases met the requested factual behavior on both repeats. Three require
work: translation, disputed readings, and document-instruction handling. This is
a small, reused synthetic development suite; these counts are not a general
accuracy estimate. Existing citation IDs are checked only for membership, not
semantic support. Prompt separation does not guarantee injection resistance.

## Small thread comparison

Six threads were tested on three cases, twice each. Selected comparisons:

| Case and condition | 4 threads total | 6 threads total |
|---|---:|---:|
| English closure, process-cold | 14.85 s | 12.96 s |
| English closure, immediate repeat | 0.53 s | 0.50 s |
| French closure, first request for source | 13.39 s | 13.82 s |
| French closure, immediate repeat | 0.68 s | 0.73 s |

Results are mixed and too few for a stable optimum. The disputed-value failure
also persisted at six threads. Retain four as a conservative development default;
these runs do not justify broader CPU tuning.

## Separate visual check

The same model plus verified Q8 projector identified a red circle and blue
rectangle from two deterministic 336×252 drawings with no text, twice each.
The matched OCR-only control had no text/pixels and correctly could not identify
the shape or colour. Thus this tiny test demonstrates information available from
pixels that OCR text alone lacks; it does not establish real-photograph accuracy.

| Image | First TTFT / total | Immediate repeat total |
|---|---:|---:|
| Red circle | 2.73 / 3.00 s | 0.32 s |
| Blue rectangle | 2.55 / 2.69 s | 0.17 s |

Vision-server startup was 2.22 s. Working set at ready was 2.58 GiB, about
429 MiB above text-only readiness. Peak during image requests was 2.67 GiB.
These tiny images and short prompts are not comparable to the much longer OCR
contexts. Vision remains explicit and separate; no automatic routing was added.

## Validation and next decision

Eight boundary/transport tests pass. Real-server checks confirmed that oversized
prompts fail before generation and an occupied port is rejected while leaving
the existing server healthy. All owned benchmark servers were stopped.

Recommend comparing a text-only Qwen3-1.7B at Q4_K_M next, using this same suite.
However, the [official Qwen3-1.7B GGUF tree](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/tree/main)
currently lists only `Qwen3-1.7B-Q8_0.gguf`; do not assume an official Q4_K_M file
exists there. A Q4_K_M comparison needs an explicitly chosen, verified conversion
or separately reviewed artifact. No better speed or quality is claimed until
that comparison is measured.

[results.json](results.json) retains measured answers, timing, configuration and
review assessments in a compact shareable artifact. Full contexts, baseline
experiments, raw responses and server logs remain under ignored `llm/runtime/`.
Later client changes added protocol validation and independent source-warning
metadata without changing the measured prompt or sampling settings; their boundary
tests and the matched OCR-only control were rerun. Frontend/backend integration,
Docker deployment and real-world photo evaluation remain outside this work.

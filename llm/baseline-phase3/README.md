# SignSpeak local LLM

Independent OCR-grounded chat using a local llama.cpp server. The client has **no
third-party Python dependencies**, runs no OCR, and does not start models during
import. OCR, frontend/backend and Compose files are unchanged.

## Windows development

From the repository root, use the existing OCR interpreter for the example and
benchmark (they also need the OCR package). No installation is necessary:

```powershell
$env:PYTHONPATH = 'llm/src;ocr/src'
$env:PYTHONIOENCODING = 'utf-8'
& ocr/.venv/Scripts/python.exe -m signspeak_llm serve --threads 4
```

In a second PowerShell terminal, set the same environment variables and run:

```powershell
& ocr/.venv/Scripts/python.exe llm/example.py
# Reuse saved adapter output; no OCR is performed by this command:
& ocr/.venv/Scripts/python.exe -m signspeak_llm ask llm/runtime/example-views.json 'When does it reopen?' --language en
```

`example.py` runs OCR only when its cache is absent, preserving source JSON and
adapter views in ignored `llm/runtime/`. Delete that example's cached views
explicitly when you want to regenerate them. Use `python -m pip install -e ./llm`
in your backend's own environment if normal package imports are preferred.

Startup defaults reuse this laptop's `~/tools/llama-cpp/llama-server.exe` and
existing Hugging Face snapshot. Other computers must pass `--binary` and `--model`
or set `SIGNSPEAK_LLAMA_SERVER` and `SIGNSPEAK_LLM_MODEL`. Flags also include
`--context-size`, `--threads`, `--port`, and optional `--projector`.

The launcher verifies artifact sizes/SHA256, starts one CPU-only slot on
`127.0.0.1:8091`, checks `/health`, and prints configuration, startup time, memory
and log location. Ctrl+C stops only the child it created. An occupied port is an
error; it never kills an existing listener. Logs and transient files are ignored.
Normal inference is offline: explicit file paths, `--offline`, no downloads.

## Model provenance and provisioning

Official repository: [Qwen/Qwen3-VL-2B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF),
Apache 2.0. Pinned revision: `52d6c8ffea26cc873ac5ad116f8631268d7eb503`.
The [model card](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/tree/52d6c8ffea26cc873ac5ad116f8631268d7eb503)
supports mixing language/projector precisions and requests a recent llama.cpp;
it does not specify a numerical minimum build. This laptop's build 11904,
commit `5cd62ffee`, was tested rather than assuming older versions work.

| File | Bytes | Published SHA256 |
|---|---:|---|
| `Qwen3VL-2B-Instruct-Q4_K_M.gguf` | 1,107,409,952 | `089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae` |
| `mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf` | 445,053,216 | `f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82` |

Hashes were checked against the official pinned [language-model file](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/blob/52d6c8ffea26cc873ac5ad116f8631268d7eb503/Qwen3VL-2B-Instruct-Q4_K_M.gguf)
and [projector file](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/blob/52d6c8ffea26cc873ac5ad116f8631268d7eb503/mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf).
Exact byte counts were measured locally; matching SHA256 establishes file identity.
Both existing files matched; **no model or runtime downloads were needed**.

On a new machine, provision just these files once from the pinned official
revision, verify with `signspeak_llm.server.verify_file`, and retain them in a
persistent directory outside Git. Provisioning is separate from serving. The
verifier deliberately accepts only this pinned pair. No model cache is committed.

## Backend integration contract

```python
from signspeak_llm import LocalLLM

client = LocalLLM(base_url="http://127.0.0.1:8091", context_size=4096)
result = client.answer(
    views["llm_context"],
    question="Quand la bibliothèque rouvre-t-elle ?",
    history=[{"role": "user", "content": "Quel établissement est mentionné ?"},
             {"role": "assistant", "content": "La bibliothèque."}],
    language="fr",  # en, fr, or auto (follow question language)
)
reply = result["answer"]
```

- Input is the **complete adapter `llm_context` object**, not raw OCR `text` or
  `text_view`. Retain original OCR JSON and derived views with the image session.
- History is chronological `user`/`assistant` text for this image; the current
  question is separate. The backend owns history and resets it for a new image.
- Result includes `answer`, `finish_reason`, `warnings`, `source`, `usage`,
  `server_timings`, `ttft_ms`, `request_latency_ms`, `total_latency_ms`,
  `generation_tokens_per_second`, and `cited_region_ids`.
  Source conflicts/tentative readings produce independent warning codes even
  when the model ignores them; `verification` is always `not_performed`.
- `ValueError` means invalid input; `ContextTooLarge` means full evidence/history
  cannot fit; `InferenceError` means transport/model/protocol failure. The backend
  can map these to its own responses. This module introduces no HTTP routes.
- The client renders/tokenizes the full prompt with llama.cpp before inference,
  reserves output plus a 32-token margin, and checks the actual server slot size.
  Oversized requests fail explicitly; no evidence or history is silently dropped.
- Only trusted application text enters the system role. Document content stays
  in a user message as JSON. Numerical conflicts and tentative readings remain.
  These controls reduce risk; a small model can still hallucinate or follow
  document instructions. Benchmark results are development evidence, not a guarantee.
- Unknown `[R...]` citations are removed and flagged. Existing region IDs are
  checked for membership only; semantic support is **not verified**. Other prose
  remains model output. Truncated answers carry `generation_limit_reached`.
- Calls are synchronous. An async backend should run them in a worker thread.
  One server slot serializes inference; the backend should bound its request queue.
- Use `SIGNSPEAK_LLM_URL` or `base_url` for a trusted local container service
  origin such as `http://llama:8080` (no `/v1` suffix). Environment proxies and HTTP
  redirects are disabled. Do not configure a hosted inference endpoint.

This differs from the cached backend's `/v1/reply` contract, which currently sends
plain `context: str`. Teammates must arrange structured context preservation and
call this module, or wrap it in their service. Model lifecycle stays separate.
Docker needs a Linux runtime and persistent model mount; this project does not
implement Compose or reuse Windows executables inside containers.

## Validation

```powershell
python -m unittest discover -s llm/tests -v
& ocr/.venv/Scripts/python.exe llm/benchmark.py --threads 4 --repeats 2
& ocr/.venv/Scripts/python.exe llm/benchmark.py --threads 6 --repeats 2 --cases en_closed fr_closed dispute
& ocr/.venv/Scripts/python.exe llm/vision_benchmark.py
```

The 16-case text benchmark uses five actual cached OCR adapter outputs plus two
explicitly constructed adversarial contexts passed through the adapter. It tests
English/French, translation, columns, nutrition, disputed numbers, absent facts,
follow-ups and document instructions. Expected answers are in `benchmark.py`.
Read the saved answers against expectations; there is no keyword accuracy score.

Raw outputs, contexts, configuration, source hashes and Windows process memory
measurements are in ignored `llm/runtime/`. See [RESULTS.md](RESULTS.md) for the
reviewed measurements and limitations. Process-cold means a fresh server, **not**
an empty OS file cache. TTFT starts at the generation POST; total latency also
includes template/token/context checks. Repeated prompts benefit from caching.

Vision is tested separately with deterministic, public-free coloured-shape
fixtures generated locally. It requires Pillow only in the evaluation environment
and explicitly loads the Q8 projector. The OCR chat client never routes to vision.

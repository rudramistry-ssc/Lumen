# SignSpeak offline STT

Standalone Python 3.13-compatible adapter for CPU whisper.cpp and multilingual
Whisper Base. No Python inference dependencies, external inference APIs, microphone
access, backend routes or changes to OCR/LLM/Piper. French remains French.

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = (Resolve-Path stt/src).Path
python stt/src/signspeak_stt/provision.py  # explicit one-time network provisioning
python -m signspeak_stt stt/eval/data/en_us-0-1904.wav --language auto
python stt/eval/test_contract.py
```

Alternatively install `stt/` into your own environment with `pip install ./stt`.
No existing environment needs changing. Ordinary transcription never downloads.

```python
from signspeak_stt import WhisperSTT, transcribe

result = transcribe(wav_bytes, language="auto")  # also "en" or "fr"
engine = WhisperSTT(threads=4, timeout=120, max_seconds=60)
result = engine.transcribe(wav_bytes, "fr")
```

Input: nonempty **16 kHz mono signed PCM16 WAV**, maximum 8,000,000 bytes and
60 seconds by default. Use a language code, not an unspecified/unsupported tag.
`auto` can detect languages beyond English/French and returns a warning for those.
One language is selected per recording; this is not a code-switching guarantee.

Output is a separate dictionary: `status` (`ok`, `no_speech`, `error`), `text`,
`language` (code or null), `requested_language`, `audio_seconds`,
`processing_seconds`, `segments` with approximate `offsets_ms`, `warnings`, `error`,
model hash/revision and runtime identity. Successful native inference also records
`native_model_load_seconds` and approximate `native_peak_working_set_mib`.
Processing time includes validation, temp I/O, process startup, model load and
inference; initial object construction/hash time is separate. Invalid input, missing artifacts and timeouts
return an empty transcript and actionable error. Configuration errors at object
construction raise `ValueError`/`OSError`. CLI errors exit nonzero.

`ok` means transcription completed, **not verified speech**. Whisper can invent
words and numbers. Display the hypothesis for confirmation before using important
questions/values. Digit-containing readings get an additional warning. The adapter
does not repair, translate, execute or silently substitute recognized content.
Near-digital silence is skipped; other noise passes to Whisper. Empty model output
becomes `no_speech`. This is not robust VAD or a promise against hallucinations on
arbitrary background sounds. No additional VAD model is downloaded.

Audio/JSON temporary files are removed on success, error and timeout. Hard process
termination or power loss can leave OS temporary files; use appropriate ephemeral
storage. No permanent user recording or transcript cache is created. The authorized
evaluation clips/results are retained separately under `eval/`.

## Configuration and Docker provisioning

| Setting | Purpose |
| --- | --- |
| `SIGNSPEAK_STT_CACHE` | Persistent artifact root; default `~/.cache/signspeak/stt` |
| `SIGNSPEAK_WHISPER_MODEL` | Explicit local `ggml-base.bin` path |
| `SIGNSPEAK_WHISPER_CLI` | Native whisper-cli executable (otherwise PATH/cache) |
| `SIGNSPEAK_WHISPER_SERVER` | Optional native server used by evaluation |
| `SIGNSPEAK_FFMPEG` | Optional conversion executable |

Python constructor `model=`/`cli=` also accepts explicit paths. Standard temporary
directory environment settings apply. Keep artifact storage mounted persistently
and temp storage writable. No audio hardware or GUI is required.

Exact artifact URLs, revisions, sizes, SHA256 and licenses: [artifacts.json](artifacts.json).
Runtime source is official [whisper.cpp v1.9.5](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5),
commit `d1be6fde11ac6e0407606b4e42fe72d34add8037`. That release has no binary
assets; its linked official nightly **b5454** is the same source commit. The Windows
CPU x64 archive is 8.93 MB. Multilingual `ggml-base.bin` is 147.95 MB (not `base.en`);
both runtime and model are MIT licensed. Provisioning checks sizes/SHA256 before
use, reuses valid downloads and preserves partial downloads for resumption.

For Linux/Docker, build that commit natively with CMake/C++ build tools and
`-DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DWHISPER_BUILD_EXAMPLES=ON`; supply
`whisper-cli` plus its required shared libraries, Python >=3.11 and the same model.
The provisioner downloads only the model on non-Windows systems. Linux execution
has not been tested here. No PyTorch, ONNX Python package, audio driver or FFmpeg
is needed for canonical WAV. Container/build integration belongs to the Docker team.

For WebM/Opus or other formats, the explicit optional boundary is:

```python
from signspeak_stt import convert_audio
wav_bytes = convert_audio(upload_bytes, ffmpeg="/path/to/ffmpeg")
result = engine.transcribe(wav_bytes)
```

CLI equivalent: `--convert`. Conversion uses pipes, disables external input
protocols, enforces size/duration limits and emits canonical PCM16 WAV. FFmpeg
was absent and was not installed; real WebM/Opus conversion remains unvalidated.
The Docker team must provision an appropriate licensed FFmpeg build if needed.

## Evaluation

Twelve licensed human FLEURS recordings (six English/six French), original
references, source IDs, hashes, license and conversion details are preserved in
[eval/data/manifest.json](eval/data/manifest.json). WAVs are ignored by Git.
CC BY 4.0 attribution: Google FLEURS contributors, Conneau et al. (2022),
[FLEURS dataset](https://huggingface.co/datasets/google/fleurs),
[license](https://creativecommons.org/licenses/by/4.0/). Source references are
published corpus text, **not manually listening-verified by this evaluation**.

```powershell
python stt/eval/run.py  # local data only; creates a new timestamped result
```

Only to recreate the small licensed evaluation data (not for normal inference):

```powershell
python -m venv stt/.prep
stt/.prep/Scripts/python.exe -m pip install pyarrow==26.0.0
stt/.prep/Scripts/python.exe stt/eval/prepare_fleurs.py
```

The preparation-only reader retrieves bounded prefixes (~8.5 MB/language), not
entire datasets; validates dictionary ordering against row indices, pins the
source revision, and converts float32 WAV to PCM16 without resampling. It reuses
verified existing clips. It intentionally fails if the pinned file format changes.
PyArrow is not an STT dependency. See [measured results](eval/RESULTS.md).

CLI stays the default: each request loads the model. Reusing `WhisperSTT` reuses
configuration/hash work, not model state. The evaluation investigates the existing
localhost-only native server, starts/stops only its own process and records repeats.
The measured benefit does not yet justify exposing a persistent-service lifecycle.
Laptop microphone questions, manual transcript checks and date/time questions
remain the next validation step; no cloud or automatic Qwen handoff is implemented.

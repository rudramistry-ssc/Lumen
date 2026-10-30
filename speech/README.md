# SignSpeak offline speech

Standalone English/French read-aloud with maintained **OHF-Voice Piper 1.8.0**.
CPU only, no LLM, server, microphone, cloud inference or audio hardware required.
Produces mono, 16-bit PCM WAV at 22,050 Hz for browser playback (`audio/wav`).

## Windows setup and use

Tested on Python 3.13.1, Windows 11, i7-1265U and 16 GB RAM. A separate environment
keeps OCR/LLM dependencies unchanged. Piper publishes a `cp39-abi3-win_amd64`
wheel accepted by Python 3.13; ONNX Runtime has a native `cp313` wheel.

```powershell
py -3.13 -m venv speech/.venv
& speech/.venv/Scripts/python.exe -m pip install --only-binary=:all: -r speech/requirements.txt
$env:PYTHONPATH = 'speech/src'
& speech/.venv/Scripts/python.exe -m signspeak_speech provision en fr
& speech/.venv/Scripts/python.exe -m signspeak_speech synthesize --text-file notice-fr.txt --language fr --output speech/runtime/notice-fr.wav
```

Provisioning is a one-time network operation. Synthesis uses only local files and
fails clearly if they are missing or fail checksum verification. Existing
compatible cached voices are reused. No system tools or administrator install
were needed on the tested laptop. Save text/JSON as UTF-8; older PowerShell's
default piped stdin can replace accented characters. Prefer `--text-file` over
piping text into Python. The source file is never overwritten by synthesis.

## Application interface

Install `speech/` as a normal Python package in the consuming environment, or use
the PYTHONPATH above. Retain one instance to reuse both lazily loaded voices:

```python
from signspeak_speech import PiperSpeech

tts = PiperSpeech()
result = tts.synthesize("La bibliothèque rouvre mardi à 9 h 00.", "fr")
wav_bytes = result.wav_bytes
result.write_wav("notice.wav")

# Existing adapter; global notices precede segment warnings/content.
result = tts.synthesize_view(views["speech"])

# Explicit, ordered language switching; no translation or language guessing.
result = tts.synthesize_segments([
    {"text": "The library reopens Tuesday.", "language": "en"},
    {"text": "La bibliothèque rouvre mardi.", "language": "fr"},
])

# Reconciled text stays unmodified. Choose a language for each ordered section.
result = tts.synthesize_reconciled(candidate, section_languages=["en", "fr"])
```

`SpeechResult.metadata` records the exact planned text, speech-only expanded text,
voice/language sequence, timing, audio duration and voice-load timings. No source
IDs, JSON keys, coordinates or confidence scores are spoken. Sections containing
multiple languages must first have explicit language boundaries from the caller.

`en`/`fr` and locale tags such as `en-US`/`fr-CA` select the fixed US-English /
France-French voices. Unknown, absent or unresolved mixed tags raise
`UnsupportedLanguageError`. A caller may explicitly choose `default_language`
for unknown/mixed segments. Unsupported languages such as German still fail.
Annotated OCR `language_details.segments` are used only if they cover the source
text, preserving order. Nothing is silently skipped.

Warning notices are spoken before uncertain values. Reconciliation review flags
produce notices in each requested language; numeric differences get numeric
warnings. This announces uncertainty, not numerical verification or correction.
The original selected reading is retained. Do not discard the adapter/reconciler
uncertainty flags when constructing speech requests.

Speech-only expansions cover valid ISO dates, French clock notation, English
whole-hour AM/PM notation, common units, currency symbols and percentages. Decimal
punctuation, ambiguous slash dates and other abbreviations are left to Piper.
Use `expand_notation=False` for literal input to Piper. Document text is never
translated, summarized, or overwritten. These expansions are not an OCR repair.

Calls are synchronous and serialized per instance; an async backend should use a
worker thread. All segments/languages and required paths are checked before audio
generation. Missing voices raise `MissingVoiceError`; native failures raise
`SpeechError`. No partial WAV is returned. Voice models remain resident for that
instance; repeated separate CLI processes naturally incur cold loading again.
WAV bytes are buffered in memory; keep individual requests to document excerpts.

## Voices, storage and Docker handoff

| Language | Pinned voice | ONNX size | Model-card dataset license |
|---|---|---:|---|
| English | `en_US-ljspeech-high` | 114,199,011 bytes | Public domain |
| French | `fr_FR-siwis-medium` | 63,201,294 bytes | CC-BY 4.0 |

Both use ONNX + adjacent `.onnx.json`, 22,050 Hz, one speaker. The artifact host
is `rhasspy/piper-voices`; the engine is OHF-Voice, not the archived old runtime.
Revision, exact paths, sizes, SHA256 hashes and model-card links are packaged in
[`voices.json`](src/signspeak_speech/voices.json). See [license provenance](LICENSES.md)
for repository licensing, datasets and SIWIS's documented Lessac fine-tuning.

Default persistent storage is `~/.cache/signspeak/voices/<revision>/<voice-name>`;
an existing pinned Hugging Face snapshot is reused if present. Override with
`SIGNSPEAK_VOICE_DIR`, `PiperSpeech(voice_dir=...)` or CLI `--voice-dir`. A root
contains one subdirectory per voice. `voice_paths={"en": "/models/name.onnx", ...}`
allows explicit model paths; the config must be adjacent as `.onnx.json`. Runtime
verification expects the pinned artifacts. Model files and development environments
are ignored by Git.

For Docker, install the pinned requirements and this package, provision those six
artifacts (two ONNX, two configs, two model cards) into a persistent directory once,
then set `SIGNSPEAK_VOICE_DIR`. Python 3.13 Linux x86-64 wheels were verified for
both Piper and ONNX Runtime; the latter requires glibc 2.28 or newer. Piper bundles
phonemization resources. No CUDA, audio device, ALSA/PulseAudio service, browser or
separate TTS server is used by this module. Actual container validation is pending;
no Docker/Compose or teammate-owned code was added.

## Evaluation and listening

```powershell
& speech/.venv/Scripts/python.exe -m unittest discover -s speech/tests -v
& speech/.venv/Scripts/python.exe speech/evaluate.py
```

Each run creates a fresh ignored directory with playable WAVs, UTF-8 transcripts,
voice-switch timelines, measurements and language-error checks. It covers notices,
bilingual switching, dates/times, prices/decimals, nutrition, numerical uncertainty
and reviewed reconciliation. Published samples/results are listed in
[RESULTS.md](RESULTS.md). **Manual listening is still required** for naturalness,
accent preferences, number pronunciation and pauses; automated WAV checks are not
a pronunciation score. No speech-to-text, Pipecat or model tuning is included.

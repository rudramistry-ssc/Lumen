# Windows validation: pending, not demonstrated

Target: managed Windows laptop, Python 3.13, Tesseract 5.4 with `eng` and `fra`.
No Windows execution has been performed for this increment. Linux results do
not establish Windows compatibility, latency or numerical accuracy.

## User-space setup (PowerShell)

Start in the `CanAI_Team_E` repository root. No activation script or administrator
privileges are needed; invoke the virtual environment interpreter directly.
Use the already approved Tesseract installation; do not reinstall system tools.

```powershell
py -3.13 --version
py -3.13 -m venv .\ocr\.venv
$OcrPython = Join-Path (Get-Location) 'ocr\.venv\Scripts\python.exe'
Push-Location .\ocr
& $OcrPython -m pip install -e '.[preprocess]'
Pop-Location
$env:SIGNSPEAK_TESSERACT_CMD = Join-Path $env:LOCALAPPDATA 'Programs\Tesseract-OCR\tesseract.exe'
& $env:SIGNSPEAK_TESSERACT_CMD --version
& $env:SIGNSPEAK_TESSERACT_CMD --list-langs
& $OcrPython -m signspeak_ocr check
New-Item -ItemType Directory -Force .\ocr\eval\generated | Out-Null
& $OcrPython -m pip freeze | Set-Content -Encoding utf8 .\ocr\eval\generated\windows-dependencies.txt
```

Create `ocr\eval\generated` first if it is absent. Override the Tesseract path
with its actual approved location if necessary. Package requirements are
Python >=3.11 (target 3.13), NumPy >=2.1, Pillow >=11, and the optional
`opencv-python-headless>=4.10` extra. No pytest, Docling, torch, model downloads,
llama.cpp, voice libraries or administrator installation is required.
The installation command resolves available wheels; availability and trust-store
behavior on the managed laptop are unverified. Preserve the exact installed
versions from `pip freeze` with measured results rather than assuming Linux's
wheel versions work on Windows. If installation fails, retain the error and
follow managed-device policy; do not bypass certificate checks.

## Same-image extraction checks

Copy the existing ignored `ocr\eval\generated\images` files and ground-truth
manifest to the laptop using the team's permitted transfer method. These assets
are not in Git. Use the same image bytes when comparing operating systems;
regenerating with Arial instead of DejaVu Sans creates a different dataset.

```powershell
New-Item -ItemType Directory -Force .\ocr\eval\generated\windows | Out-Null
& $OcrPython -m signspeak_ocr extract .\ocr\eval\generated\images\small_photo.png --debug -o .\ocr\eval\generated\windows\small-default.json
& $OcrPython -m signspeak_ocr extract .\ocr\eval\generated\images\small_photo.png --preprocess --debug -o .\ocr\eval\generated\windows\small-targeted.json
& $OcrPython -m signspeak_ocr extract .\ocr\eval\generated\images\columns_clean.png --preprocess --debug -o .\ocr\eval\generated\windows\columns-clean.json
& $OcrPython -m signspeak_ocr extract .\ocr\eval\generated\images\columns_photo.png --preprocess --debug -o .\ocr\eval\generated\windows\columns-photo.json
```

Check structured `errors`, `warnings`, `validation`, `reading_order`, per-region
provenance, numeric alternatives/flags, and selected variant. Verify column
sequence, crop/upscale transforms, original-photo word positions, French accents
and `1,5` versus `1.5`. Inspect the display and agent evidence separately: agent
placeholders are intentional uncertainty, not missing display OCR.

## Full paired benchmark

The accepted pre-increment baseline is under
`generated\reference-20261028\source\signspeak_ocr` and is also ignored by Git.
Transfer that source snapshot as well as the unchanged benchmark assets. It
must be a directory containing `signspeak_ocr`, not the current source package.
The `--reference-enabled` switch enables preprocessing in this older reference;
without it the comparison would incorrectly use its default single-pass path.

```powershell
New-Item -ItemType Directory -Force .\ocr\eval\generated\windows-paired | Out-Null
Copy-Item .\ocr\eval\generated\manifest.json .\ocr\eval\generated\windows-paired\manifest.json
& $OcrPython .\ocr\eval\evaluate.py run --output .\ocr\eval\generated\windows-paired --phase1-source .\ocr\eval\generated\reference-20261028\source --reference-enabled --psm 3
& $OcrPython .\ocr\eval\evaluate.py summarize --output .\ocr\eval\generated\windows-paired
```

The evaluator resolves relocated image paths by file name and checks the recorded
SHA256 before running. Its legacy `--phase1-source` argument also accepts the
preserved Phase 2 reference; `--reference-enabled` identifies that comparison.
Keep the Windows `run.json`, raw results, dependency versions and summary.
Do not accept a run with missing languages, altered image hashes, schema problems
or unexplained differences. Windows memory reporting may omit finished-child RSS;
report missing measurements rather than substituting Linux numbers. Actual laptop
performance and compatibility remain pending until these commands are executed.

## Integration adapter smoke check (no additional dependencies)

The adapter is included by normal package discovery; no extraction-engine or
TTS/LLM dependency is added. From the repository root after setup, reuse the
saved OCR JSON rather than running inference again:

```powershell
& $OcrPython -c "import json; from pathlib import Path; from signspeak_ocr.integration import adapt_result; p=Path('ocr/eval/generated/windows/small-targeted.json'); source=json.loads(p.read_text(encoding='utf-8')); views=adapt_result(source); Path('ocr/eval/generated/windows/small-views.json').write_text(json.dumps(views,ensure_ascii=False,indent=2),encoding='utf-8')"
```

Verify that display text is readable, speech segments retain ordering/language,
and `llm_context.selected_text` contains tentative text with word-ID annotations
in `llm_context.regions[].tentative_words`. The original JSON is the source
record; keep it alongside the derived views. Do not interpret
`correlated_agreement_unverified` or `single_read_unverified` as confirmed facts.

The local handoff ZIP includes source, these instructions, the 20 permitted
synthetic images/ground truth, the accepted comparison source, and three example
source/view pairs. Unzip it, enter `CanAI_Team_E`, then follow these commands.
No Python environment, Tesseract executable, language data or downloaded wheels
are bundled. Resolve those requirements using the approved existing setup.
The ignored generated assets will not arrive through a Git checkout alone.
Windows package installation and execution remain **pending user validation**.

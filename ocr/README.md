# SignSpeak OCR

CPU-only English/French OCR with image preprocessing, word boxes and a structured JSON result.
The package exposes three downstream views for SignSpeak's user interface, speech playback and local LLM.
No model API or network connection is needed for inference.

## Install on Windows (Python 3.13)

From the `CanAI_Team_E` repository root:

```powershell
py -3.13 -m venv .\ocr\.venv
$py = Join-Path (Get-Location) 'ocr\.venv\Scripts\python.exe'
Push-Location ocr
& $py -m pip install -e '.[preprocess]'
Pop-Location
& $py -m signspeak_ocr check
```

Tesseract must be installed separately with English and French language data. Set
`SIGNSPEAK_TESSERACT_CMD` to its executable if it is not on PATH. In Docker,
install the Linux Tesseract executable and language data inside the container.

## Extract an image

```powershell
& $py -m signspeak_ocr extract .\path\to\photo.png --preprocess -o result.json
```

```python
from signspeak_ocr import PipelineConfig, PreprocessConfig, extract_image
from signspeak_ocr.integration import adapt_result

source = extract_image('photo.png', PipelineConfig(preprocessing=PreprocessConfig(enabled=True)))
views = adapt_result(source)
print(views['display']['text'])
# The backend can also use views['speech'] and views['llm_context'].
```

The OCR source JSON remains the source of truth; extracted values are not independently
verified. Display boxes use the oriented original image's pixel coordinates.
The application should preserve uncertainty flags for disputed numbers.

## Evaluation

The fixed 20-image synthetic benchmark, reference transcripts and a paired evaluation
script are in [`eval/`](eval/README.md). Real photographs and Docker operation have
not been validated by this benchmark.

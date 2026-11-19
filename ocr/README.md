# SignSpeak OCR

Single-image transcription and visual summaries through an OpenAI-compatible
vision model. In this offline demo that is Qwen3-VL in the local llama.cpp
`qwen` container; this package itself loads no model weights.

The browser integration is documented in [workspace README](../README.md).
The app sends an image to `/v1/chat/completions`; the local Qwen3-VL model
(2B by default, 8B optional) produces the text and summary.
It also returns `confidence: {"text": 0–100 or null, "summary": 0–100 or null}`
in that same response. These are uncalibrated model self-assessments, not
verified accuracy. No-text/unreadable results have `text: null`. Invalid or
missing confidence fields are rejected by the image-analysis contract.

Speed: the model answers with a small flat JSON object (`extracted_text`,
`summary`, `language`, `text_confidence`, `summary_confidence`); `text_status` is
derived from the text. Images are scaled to at most 0.5 MP (about 500 image
tokens), and one system prompt serves both the image request and follow-up chat
so the model server can reuse its cache.

## Python API

```python
from signspeak_ocr import VlmConfig, analyze_image, render_report

result = analyze_image(image_bytes, vlm_config=VlmConfig())
print(result["text"])
print(result["summary"])
```

VLM configuration comes from `SIGNSPEAK_VLM_BASE_URL`,
`SIGNSPEAK_VLM_MODEL`, and `SIGNSPEAK_VLM_API_KEY`.
Only the web app automatically reads the workspace `.env`.

Strict JSON validation is retained, along with
EXIF orientation, aspect-preserving resizing, authentication, bounded transient
retries and rejection of truncated output. Text remains in its original
language. The summary defaults to English. Symbol-only images are supported.
The structured result includes `language` (`en`, `fr`, `mixed`, `none`) detected
from the image, separately from the summary language. Generated summaries use
plain text; the source transcription retains literal punctuation.

## Command line

```powershell
python -m signspeak_ocr check
python -m signspeak_ocr extract "ocr/test images/one.png"
python ocr/run_test_images.py
```

Set model environment variables before using these commands. Batch testing runs
the same pipeline once per image and writes `ocr/out.txt`. Optional
`--json-dir ocr/results` saves diagnostics; the browser only receives text and summary.
Use `--summary-language French` to change the CLI summary language.

No Tesseract, OpenCV or database dependency is required. The package's `chat.py`
reuses the same model HTTP connection for image follow-ups. The web app's local
Whisper/Kokoro speech dependencies are listed separately in `requirements-speech.txt`.
All original image files are preserved.

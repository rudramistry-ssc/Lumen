"""Tiny web wrapper around the OCR package: image in, {text, language} out."""

from fastapi import FastAPI, HTTPException, UploadFile

from signspeak_ocr import PipelineConfig, PreprocessConfig, extract_image

app = FastAPI(title="SignSpeak OCR service")

# Preprocessing = the retry-on-hard-photos step (needs the OpenCV extra).
CONFIG = PipelineConfig(preprocessing=PreprocessConfig(enabled=True))


@app.post("/v1/ocr")
def ocr(file: UploadFile):
    # Plain `def`, not `async def`: OCR is slow CPU work, and FastAPI runs
    # plain functions in a worker thread so other requests aren't blocked.
    result = extract_image(file.file.read(), CONFIG, file_name=file.filename)

    if result["validation"]["overall_status"] == "failed":
        raise HTTPException(status_code=422, detail=result["errors"])

    language = result["language"]["primary"]
    return {
        "text": result["text"],
        "language": "" if language == "unknown" else language,
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}

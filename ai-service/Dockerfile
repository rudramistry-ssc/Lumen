# Build from the repository root (it needs ../ocr too):
#   docker build -f ai-service/Dockerfile .
# backend/docker-compose.yml does this for you.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Tesseract + English/French data for OCR, espeak-ng for text to speech
# (Linux has no built-in voices like macOS or Windows).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra espeak-ng \
 && rm -rf /var/lib/apt/lists/*

# OCR package first, so code edits in ai-service don't reinstall it.
COPY ocr /ocr
RUN pip install --no-cache-dir "/ocr[preprocess]"

WORKDIR /app
COPY ai-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ai-service/ .

# Fail the build now if Tesseract or the language data are missing.
RUN python -m signspeak_ocr check

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

# App image: FastAPI backend + frontend + local speech (faster-whisper, Kokoro).
# Used by both the one-time `models` setup service and the `api` service.
# The vision model runs separately in the llama.cpp `qwen` container.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    LUMEN_MODELS_DIR=/models

# Networks that inspect HTTPS (e.g. GOC-GDC-ROOT-A) need their root CA trusted
# for the build and the one-time model download. Any certs/*.crt is added here;
# TLS verification always stays on. See README > Corporate networks.
COPY certs/ /usr/local/share/ca-certificates/lumen/
RUN update-ca-certificates

WORKDIR /app
# Third-party packages first, keyed only on requirements.txt, so code or doc
# edits never re-download them. The BuildKit cache keeps wheels between builds.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    grep -v '^-e ' backend/requirements.txt > /tmp/requirements.txt \
    && PIP_NO_CACHE_DIR=0 pip install -r /tmp/requirements.txt
COPY ocr/pyproject.toml ocr/README.md /app/ocr/
COPY ocr/src /app/ocr/src
RUN pip install --no-deps -e ./ocr

COPY backend /app/backend
COPY frontend /app/frontend

# Run unprivileged. The models volume inherits this directory's owner on first use.
RUN useradd --create-home --uid 10001 lumen \
    && mkdir -p /models && chown lumen:lumen /models
USER lumen

WORKDIR /app/backend
EXPOSE 8000
# Sessions live in memory: exactly one worker.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

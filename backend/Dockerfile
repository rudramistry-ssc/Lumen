# Small Python base; all deps are wheels, so no build tools needed.
FROM python:3.12-slim

# Unbuffered logs show up in `docker compose logs` immediately.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Deps first so code edits don't invalidate the pip layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Everything else: main.py, config.py, db.py, routers/, services/, models/.
COPY . .

EXPOSE 8000

# One process on purpose: sqlite + POC, no workers or queues.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

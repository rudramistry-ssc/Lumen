"""App wiring only: startup, CORS, routes, and the static UI."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings
from db import init_db
from routers import chat, images, sessions


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once on boot, before any request: folders first, then tables.
    settings = get_settings()
    Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title="CanAI Team E backend", lifespan=lifespan)

# The frontend runs on a different origin, so browser calls need CORS.
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# All real endpoints live under /v1.
app.include_router(sessions.router, prefix="/v1")
app.include_router(images.router, prefix="/v1")
app.include_router(chat.router, prefix="/v1")


@app.get("/healthz")
@app.get("/health")
def healthz():
    # /health is an alias for external pollers that don't use /healthz.
    return {"status": "ok"}


# The UI is plain static files. Serving them from the same origin means the
# browser needs no CORS and the frontend can keep API_BASE_URL empty.
# Mounted last on purpose: /v1 routes, /docs and /healthz match first.
_frontend_dir = Path(settings.frontend_dir)
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")

"""App wiring only: startup, CORS, and route registration."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/")
def root():
    # Friendly landing response so hitting the base URL isn't a bare 404.
    return {
        "service": "CanAI Team E backend",
        "health": "/healthz",
        "docs": "/docs",
        "api": "/v1",
    }


@app.get("/healthz")
def healthz():
    # Used by Docker/compose to know the API is up.
    return {"status": "ok"}

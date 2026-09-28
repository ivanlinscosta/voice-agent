import asyncio
import contextlib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.config import settings
from app.api.websocket import router as websocket_router, manager
from app.observability import setup_logging, setup_tracing, registry

setup_logging()
setup_tracing()


async def cleanup_task():
    while True:
        await asyncio.sleep(60)
        await manager.cleanup_stale_sessions()


async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleanup_task())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(
    title="Nova Voice Agent API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env == "dev" else None,
    redoc_url="/redoc" if settings.app_env == "dev" else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "dev" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(websocket_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
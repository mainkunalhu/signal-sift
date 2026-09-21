"""SignalSift API entrypoint. Run: uv run uvicorn main:app --reload --port 8000"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from agents.observability import setup_tracing
from routes.health import router as health_router
from routes.research import router as research_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_tracing()
    from tools.embed import warmup

    await warmup()  # preload bge-small so first request never pays model load
    yield


app = FastAPI(title="SignalSift API", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(research_router)


@app.get("/")
def root() -> dict:
    return {"service": "signalsift-api", "docs": "/docs", "health": "/health"}

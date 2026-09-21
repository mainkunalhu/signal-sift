"""SignalSift API entrypoint. Run: uv run uvicorn main:app --reload --port 8000"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agents.observability import setup_tracing
from routes.chats import router as chats_router
from routes.health import router as health_router
from routes.research import router as research_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    setup_tracing()
    # Warm both slow starters concurrently: embedding model + Neon pooler.
    # SKIP_WARMUP=1 skips both for instant boots (first request pays instead).
    if os.getenv("SKIP_WARMUP") != "1":
        from db.store import warmup as warm_db
        from tools.embed import warmup as warm_embed

        await asyncio.gather(warm_db(), warm_embed())
    yield


app = FastAPI(title="SignalSift API", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(research_router)
app.include_router(chats_router)


@app.get("/")
def root() -> dict:
    return {"service": "signalsift-api", "docs": "/docs", "health": "/health"}

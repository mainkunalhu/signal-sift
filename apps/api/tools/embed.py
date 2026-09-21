"""Local embeddings: BAAI/bge-small-en-v1.5 (384-d, CPU, no GPU needed).

Lazy singleton — the model downloads from HF on first real use (~130MB),
never at import time, never in tests (inject `embed_fn` fakes instead).
384 dimensions match `infra/schema.sql` vector columns.
"""

import asyncio
from collections.abc import Awaitable, Callable

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]

_model = None
_init_lock = asyncio.Lock()


async def _get_model():
    """Double-checked locking: concurrent first calls load the model exactly once."""
    global _model
    if _model is None:
        async with _init_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                # Pin CPU: Apple MPS (Metal) crashes under concurrent inference
                # (hard SIGABRT, kills the server). CPU is also the portable
                # default — prod Linux has no MPS anyway.
                _model = await asyncio.to_thread(
                    SentenceTransformer, "BAAI/bge-small-en-v1.5", device="cpu"
                )
    return _model


async def warmup() -> bool:
    """Preload the model (server boot). Returns False if HF is unreachable."""
    try:
        await embed_texts(["signal sift warmup"])
        return True
    except Exception:
        return False


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch; returns parallel list of 384-d vectors."""
    if not texts:
        return []
    model = await _get_model()
    vectors = await asyncio.to_thread(model.encode, texts, normalize_embeddings=True)
    return [list(map(float, v)) for v in vectors]

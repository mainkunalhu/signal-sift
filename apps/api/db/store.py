"""Persistence: queries -> documents -> claims. Best-effort by contract.

`save_run` never raises into request paths — callers wrap it, and it also
guards internally, returning None on any failure. Embeddings are passed in
(precomputed) so this module never touches the HF model.
"""

import json

import asyncpg
from pgvector.asyncpg import register_vector

from config import settings


async def save_run(
    *,
    query: str,
    plan: list[dict],
    docs: list[dict],
    claims: list[dict],
) -> str | None:
    """Persist one research run. Returns query_id or None on failure."""
    try:
        conn = await asyncpg.connect(settings.database_url, timeout=10)
        try:
            await register_vector(conn)
            query_id = await conn.fetchval(
                "insert into queries (text, plan_json) values ($1, $2) returning id",
                query,
                json.dumps(plan),
            )
            doc_ids: dict[str, object] = {}
            for doc in docs:
                row = await conn.fetchrow(
                    """insert into documents (query_id, url, title, content_hash, embedding)
                       values ($1, $2, $3, $4, $5)
                       on conflict (content_hash) do nothing
                       returning id""",
                    query_id,
                    doc["url"],
                    doc.get("title", ""),
                    doc.get("content_hash", ""),
                    doc.get("embedding"),
                )
                if row is None:
                    row = await conn.fetchrow(
                        "select id from documents where content_hash = $1",
                        doc.get("content_hash", ""),
                    )
                if row is not None:
                    doc_ids[doc["url"]] = row["id"]
            for claim in claims:
                doc_id = doc_ids.get(claim.get("url", ""))
                if doc_id is None:
                    continue
                await conn.execute(
                    """insert into claims (doc_id, text, embedding, verdict, citations)
                       values ($1, $2, NULL, $3, $4)""",
                    doc_id,
                    claim.get("text", ""),
                    claim.get("verdict", "pending"),
                    json.dumps([{"quote": claim.get("quote", "")}]),
                )
            return str(query_id)
        finally:
            await conn.close()
    except Exception:
        return None

"""Persistence: queries -> documents -> claims. Best-effort by contract.

`save_run` never raises into request paths — callers wrap it, and it also
guards internally, returning None on any failure. Embeddings are passed in
(precomputed) so this module never touches the HF model.
"""

import json

import asyncpg
from pgvector.asyncpg import register_vector

from config import settings


async def _connect():
    conn = await asyncpg.connect(settings.database_url, timeout=10)
    await register_vector(conn)
    return conn


async def warmup() -> bool:
    """One cheap query at boot: wakes Neon's suspended compute so the first
    real request never pays the cold-pooler penalty (5–15s of dead air)."""
    try:
        conn = await asyncpg.connect(settings.database_url, timeout=15)
        try:
            await conn.fetchval("select 1")
            return True
        finally:
            await conn.close()
    except Exception:
        return False


def auto_title(query: str) -> str:
    title = " ".join((query or "").split())
    return (title[:57] + "…") if len(title) > 60 else (title or "New research")


async def create_chat(title: str | None = None) -> dict | None:
    try:
        conn = await _connect()
        try:
            row = await conn.fetchrow(
                "insert into chats (title) values ($1) returning id, title",
                title or "New research",
            )
            return {"id": str(row["id"]), "title": row["title"]}
        finally:
            await conn.close()
    except Exception:
        return None


async def list_chats(limit: int = 50) -> list[dict]:
    try:
        conn = await _connect()
        try:
            rows = await conn.fetch(
                """select c.id, c.title, c.updated_at, count(m.id) as messages
                   from chats c left join messages m on m.chat_id = c.id
                   group by c.id order by c.updated_at desc limit $1""",
                limit,
            )
            return [
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "updated_at": r["updated_at"].isoformat(),
                    "messages": r["messages"],
                }
                for r in rows
            ]
        finally:
            await conn.close()
    except Exception:
        return []


async def get_chat(chat_id: str) -> dict | None:
    try:
        conn = await _connect()
        try:
            chat = await conn.fetchrow("select id, title from chats where id = $1", chat_id)
            if chat is None:
                return None
            msgs = await conn.fetch(
                """select id, role, content, citations, graph, latency_ms
                   from messages where chat_id = $1 order by created_at""",
                chat_id,
            )
            return {
                "id": str(chat["id"]),
                "title": chat["title"],
                "messages": [
                    {
                        "id": str(m["id"]),
                        "role": m["role"],
                        "content": m["content"],
                        "citations": json.loads(m["citations"])
                        if isinstance(m["citations"], str)
                        else m["citations"],
                        "graph": json.loads(m["graph"])
                        if isinstance(m["graph"], str)
                        else m["graph"],
                        "latency_ms": m["latency_ms"],
                    }
                    for m in msgs
                ],
            }
        finally:
            await conn.close()
    except Exception:
        return None


async def delete_chat(chat_id: str) -> bool:
    try:
        conn = await _connect()
        try:
            status = await conn.execute("delete from chats where id = $1", chat_id)
            return status != "DELETE 0"
        finally:
            await conn.close()
    except Exception:
        return False


async def save_message(
    chat_id: str,
    role: str,
    content: str,
    *,
    citations: list | None = None,
    graph: dict | None = None,
    latency_ms: int = 0,
) -> str | None:
    try:
        conn = await _connect()
        try:
            row = await conn.fetchrow(
                """insert into messages (chat_id, role, content, citations, graph, latency_ms)
                   values ($1, $2, $3, $4, $5, $6) returning id""",
                chat_id,
                role,
                content,
                json.dumps(citations or []),
                json.dumps(graph or {}),
                latency_ms,
            )
            await conn.execute("update chats set updated_at = now() where id = $1", chat_id)
            return str(row["id"])
        finally:
            await conn.close()
    except Exception:
        return None


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

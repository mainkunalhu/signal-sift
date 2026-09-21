"""Liveness + dependency checks. Never leaks secrets — booleans only."""

import asyncpg
import httpx
from fastapi import APIRouter

from config import settings

router = APIRouter()


async def check_groq() -> dict:
    if not settings.groq_api_key:
        return {"ok": False, "reason": "no_key"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            )
        if r.status_code == 200:
            ids = [m.get("id", "") for m in r.json().get("data", [])]
            return {
                "ok": True,
                "models": len(ids),
                "has_planner": settings.groq_planner_model in ids,
                "has_fast": settings.groq_fast_model in ids,
            }
        return {"ok": False, "reason": f"http_{r.status_code}"}
    except Exception as e:
        return {"ok": False, "reason": type(e).__name__}


async def check_db() -> dict:
    if not settings.database_url:
        return {"ok": False, "reason": "no_url"}
    try:
        conn = await asyncpg.connect(settings.database_url, timeout=10)
        try:
            await conn.fetchval("select 1")
            tables = await conn.fetch(
                "select tablename from pg_tables where schemaname='public'"
                " and tablename in ('queries','documents','claims')"
            )
            return {"ok": True, "tables": sorted(t["tablename"] for t in tables)}
        finally:
            await conn.close()
    except Exception as e:
        return {"ok": False, "reason": f"{type(e).__name__}"}


@router.get("/health")
async def health() -> dict:
    groq = await check_groq()
    db = await check_db()
    degraded = not (groq["ok"] and db["ok"])
    return {
        "status": "degraded" if degraded else "ok",
        "groq_ok": groq["ok"],
        "db_ok": db["ok"],
        "groq": groq,
        "db": db,
        "planner_model": settings.groq_planner_model,
        "fast_model": settings.groq_fast_model,
    }

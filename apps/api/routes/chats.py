"""Chat threads: sidebar history + message persistence."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db.store import create_chat, delete_chat, get_chat, list_chats

router = APIRouter()


class CreateChatRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)


@router.get("/api/chats")
async def api_list_chats() -> dict:
    return {"chats": await list_chats()}


@router.post("/api/chats", status_code=201)
async def api_create_chat(req: CreateChatRequest) -> dict:
    chat = await create_chat(req.title)
    if chat is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return chat


@router.get("/api/chats/{chat_id}")
async def api_get_chat(chat_id: str) -> dict:
    chat = await get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    return chat


@router.delete("/api/chats/{chat_id}")
async def api_delete_chat(chat_id: str) -> dict:
    if not await delete_chat(chat_id):
        raise HTTPException(status_code=404, detail="chat not found")
    return {"ok": True}

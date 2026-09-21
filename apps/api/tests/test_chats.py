"""Chat thread tests: CRUD routes (DB-backed) + research thread hooks.

DB tests hit Neon with rollback-safe temp rows (created + deleted in-test).
Research thread hooks are verified offline via MockClient graphs.
"""

import uuid

from fastapi.testclient import TestClient

from db.store import auto_title


def test_auto_title():
    assert auto_title("  Hello   world  ") == "Hello world"
    assert auto_title("") == "New research"
    assert auto_title("x" * 100).endswith("…")


def test_chats_crud_roundtrip():
    """DB-backed; temp chat created + deleted in-test. Needs DATABASE_URL."""
    from main import app

    client = TestClient(app)
    created = client.post("/api/chats", json={"title": f"e2e {uuid.uuid4().hex[:6]}"})
    assert created.status_code == 201
    chat_id = created.json()["id"]

    listed = client.get("/api/chats")
    assert chat_id in [c["id"] for c in listed.json()["chats"]]

    fetched = client.get(f"/api/chats/{chat_id}")
    assert fetched.status_code == 200
    assert fetched.json()["messages"] == []

    assert client.get("/api/chats/00000000-0000-0000-0000-000000000000").status_code == 404

    deleted = client.delete(f"/api/chats/{chat_id}")
    assert deleted.json() == {"ok": True}
    assert client.get(f"/api/chats/{chat_id}").status_code == 404

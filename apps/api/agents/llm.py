"""Thin LLM-client abstraction over Groq's OpenAI-compatible API.

Agents depend on the `LLMClient` protocol, not on Groq directly, so tests can
inject `MockClient` / `SleepyClient` with zero network and zero cost.
"""

import asyncio
import json
import random
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from groq import (
    APIConnectionError,
    APITimeoutError,
    AsyncGroq,
    InternalServerError,
    RateLimitError,
)


@runtime_checkable
class LLMClient(Protocol):
    name: str
    model: str

    async def acomplete_json(self, *, system: str, user: str) -> dict: ...
    async def acomplete_text(self, *, system: str, user: str) -> str: ...
    def astream_text(self, *, system: str, user: str) -> AsyncIterator[str]: ...


_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


class GroqClient:
    """Production client. Retries 429/5xx with exponential backoff + jitter."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        name: str = "groq",
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.name = name
        self.model = model
        self._client = AsyncGroq(api_key=api_key, timeout=timeout, max_retries=0)
        self._max_retries = max_retries

    async def _chat(self, *, system: str, user: str, json_mode: bool, temperature: float) -> str:
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                    **({"response_format": {"type": "json_object"}} if json_mode else {}),
                )
                return resp.choices[0].message.content or ""
            except _RETRYABLE as e:
                last = e
                await asyncio.sleep(2**attempt + random.uniform(0, 1))
        raise last  # type: ignore[misc]

    async def acomplete_json(self, *, system: str, user: str) -> dict:
        raw = await self._chat(system=system, user=user, json_mode=True, temperature=0.2)
        return _parse_json_lenient(raw)

    async def acomplete_text(self, *, system: str, user: str) -> str:
        return await self._chat(system=system, user=user, json_mode=False, temperature=0.3)

    async def astream_text(self, *, system: str, user: str) -> AsyncIterator[str]:
        """Stream deltas. Retries only before the first token (partial streams
        can't restart cleanly, so mid-stream failures propagate)."""
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                stream = await self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.3,
                    stream=True,
                )
                started = False
                async for chunk in stream:
                    delta = (chunk.choices[0].delta.content if chunk.choices else None) or ""
                    if delta:
                        started = True
                        yield delta
                return
            except _RETRYABLE as e:
                if started:
                    raise
                last = e
                await asyncio.sleep(2**attempt + random.uniform(0, 1))
        raise last  # type: ignore[misc]


def _parse_json_lenient(raw: str) -> dict:
    """json.loads, salvaging the largest {...} block when the model wraps
    JSON in prose (gpt-oss does this despite json mode)."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        return json.loads(raw[start : end + 1])
    raise ValueError("no JSON object found")


class MockClient:
    """Deterministic canned responses for unit tests. Records calls."""

    def __init__(self, *, model: str = "mock", payloads: list[Any] | None = None) -> None:
        self.name = "mock"
        self.model = model
        self._payloads = list(payloads or [])
        self.calls: list[dict] = []

    async def acomplete_json(self, *, system: str, user: str) -> dict:
        self.calls.append({"system": system, "user": user})
        payload = self._payloads.pop(0) if self._payloads else {}
        if isinstance(payload, str):
            return json.loads(payload)
        return dict(payload)

    async def acomplete_text(self, *, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        payload = self._payloads.pop(0) if self._payloads else ""
        return payload if isinstance(payload, str) else json.dumps(payload)

    async def astream_text(self, *, system: str, user: str) -> AsyncIterator[str]:
        text = await self.acomplete_text(system=system, user=user)
        mid = max(1, len(text) // 2)
        yield text[:mid]
        yield text[mid:]


class SleepyClient:
    """Fixed-latency client proving fan-out is actually concurrent.

    Every call sleeps `delay` seconds, so a sequential run over N sub-questions
    costs ~N*delay while a parallel `Send` fan-out costs ~1*delay.
    """

    def __init__(
        self,
        *,
        delay: float = 0.4,
        router_payload: dict | None = None,
        planner_payload: dict | None = None,
    ) -> None:
        self.name = "sleepy"
        self.model = "sleepy"
        self._delay = delay
        self._router_payload = router_payload or {
            "route": "research",
            "complexity": "standard",
            "lang": "en",
            "reason": "smoke test",
        }
        self._planner_payload = planner_payload or {"sub_questions": []}

    async def acomplete_json(self, *, system: str, user: str) -> dict:
        await asyncio.sleep(self._delay)
        if "router" in system.lower():
            return dict(self._router_payload)
        return json.loads(json.dumps(self._planner_payload))

    async def acomplete_text(self, *, system: str, user: str) -> str:
        await asyncio.sleep(self._delay)
        return "sleepy stub"

    async def astream_text(self, *, system: str, user: str) -> AsyncIterator[str]:
        await asyncio.sleep(self._delay)
        yield "sleepy "
        yield "stub"

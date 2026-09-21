"""Query router (fast model). <500ms gate: research | chat | reject."""

from agents.llm import LLMClient
from agents.state import RouteDecision

SYSTEM = """You are SignalSift's query router. Classify the user query.
Return JSON only, exactly this shape:
{"route": "research|chat|reject", "complexity": "simple|standard|hard", "lang": "en", "reason": "short"}
Rules:
- research: needs external facts, comparisons, news, citations, or multi-part investigation.
- chat: greetings or answerable from general knowledge with no sources needed.
- reject: harmful, empty, or nonsense queries.
- complexity: simple (1 fact) | standard (few facts) | hard (deep multi-part research)."""

_RESEARCH_HINTS = (
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "compare",
    "best",
    "latest",
    "newest",
    "vs",
    "review",
    "price",
    "?",
    "research",
)


def heuristic_fallback(query: str) -> RouteDecision:
    q = (query or "").strip()
    if not q:
        return RouteDecision(route="reject", complexity="simple", reason="empty")
    lowered = q.lower()
    if any(h in lowered for h in _RESEARCH_HINTS):
        complexity = "hard" if len(q) > 120 else "standard"
        return RouteDecision(route="research", complexity=complexity, reason="heuristic")
    if len(q.split()) <= 4:
        return RouteDecision(route="chat", complexity="simple", reason="heuristic")
    return RouteDecision(route="research", complexity="standard", reason="heuristic")


async def route_query(query: str, client: LLMClient) -> RouteDecision:
    """Classify via LLM; fall back to heuristics on any failure."""
    try:
        data = await client.acomplete_json(system=SYSTEM, user=f"Query: {query}")
        decision = RouteDecision(**data)
        if decision.route not in ("research", "chat", "reject"):
            raise ValueError(f"bad route: {decision.route}")
        return decision
    except Exception:
        return heuristic_fallback(query)

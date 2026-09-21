"""Shared LangGraph state + reducers.

Parallel `Send` fan-out writes converge here. Per-sub-question fields use
`merge_dicts` so concurrent researchers never clobber each other; append-only
fields use `append_list`. Without these reducers the last writer would win
and data would be silently lost.
"""

from typing import Annotated, TypedDict

from pydantic import BaseModel, Field


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    """Order-independent merge for parallel dict writes keyed by sub-question id."""
    return {**(left or {}), **(right or {})}


def append_list(left: list | None, right: list | None) -> list:
    """Append reducer for telemetry / log streams."""
    return (left or []) + (right or [])


class SubQuestion(BaseModel):
    id: str
    question: str
    search_queries: list[str] = Field(default_factory=list)
    priority: int = 1


class RouteDecision(BaseModel):
    route: str = "research"  # research | chat | reject
    complexity: str = "standard"  # simple | standard | hard
    lang: str = "en"
    reason: str = ""


class SupervisorState(TypedDict, total=False):
    query: str
    route: dict
    sub_questions: list[dict]
    retrievals: Annotated[dict, merge_dicts]
    analyses: Annotated[dict, merge_dicts]
    verifications: Annotated[dict, merge_dicts]
    telemetry: Annotated[list, append_list]
    # Written sequentially (aggregate -> verify -> finalize), never in parallel.
    claims: list[dict]
    evidence: dict
    citation_graph: dict
    final_report: str

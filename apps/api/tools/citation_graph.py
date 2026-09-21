"""Citation graph: claims -> source docs, with contested detection.

Pure builder: takes verifier-settled claims (each with `verdict`) plus the
run's docs, returns a JSON-serializable graph the UI renders as sources +
inline [n] citations (Phase 4). No I/O.

Contested rule (cheap, honest): claims with identical normalized text cited
from different urls where verifier verdicts disagree (some supported, some
dropped) are marked contested — the evidence itself disagrees. Pairwise NLI
contradiction detection is a documented Phase 6 upgrade.
"""

from tools.scrape import normalize


def build_citation_graph(claims: list[dict], docs: list[dict]) -> dict:
    doc_index = {d["url"]: i for i, d in enumerate(docs)}
    for i, doc in enumerate(docs):
        doc.setdefault("id", f"d{i + 1:02d}")

    supported = [c for c in claims if c.get("verdict") == "supported"]
    by_text: dict[str, list[dict]] = {}
    for claim in supported:
        by_text.setdefault(normalize(claim.get("text", "")), []).append(claim)

    dropped_texts = {
        normalize(c.get("text", "")) for c in claims if c.get("verdict") != "supported"
    }

    nodes: list[dict] = []
    for text, group in by_text.items():
        sources = sorted({c["url"] for c in group if c.get("url") in doc_index})
        if not sources:
            continue
        nodes.append(
            {
                "text": group[0]["text"],
                "quotes": [c.get("quote", "") for c in group if c.get("quote")],
                "sources": sources,
                "contested": text in dropped_texts,
            }
        )

    contested = sum(1 for n in nodes if n["contested"])
    return {
        "claims": nodes,
        "docs": [{"id": d["id"], "url": d["url"], "title": d.get("title", "")} for d in docs],
        "stats": {
            "claims_total": len(claims),
            "claims_supported": len(supported),
            "claims_dropped": len(claims) - len(supported),
            "cited_claims": len(nodes),
            "contested": contested,
        },
    }

"""Dedup: exact (sha256 of normalized text) + near (cosine > 0.92).

Pure functions over docs/claims — no DB, no network. Cross-run persistence
lives in `db/store.py`; this module keeps each run's working set small so
extract/verify never pay for the same content twice.
"""

import math

NEAR_DUP_THRESHOLD = 0.92


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def dedupe_docs(docs: list[dict], embeddings: list[list[float]] | None = None) -> dict:
    """Dedupe doc dicts (each with `url`, `content_hash`). Returns stats + survivors.

    Exact pass always runs on `content_hash`. Near pass needs `embeddings`
    aligned with the post-exact survivors; losers merge their urls into the
    winner's `merged_urls` so citations stay complete.
    """
    seen_hash: set[str] = set()
    survivors: list[dict] = []
    exact_dupes = 0
    for doc in docs:
        h = doc.get("content_hash", "")
        if h and h in seen_hash:
            exact_dupes += 1
            continue
        if h:
            seen_hash.add(h)
        survivors.append(dict(doc))

    near_dupes = 0
    if embeddings:
        kept: list[dict] = []
        kept_vecs: list[list[float]] = []
        for doc, vec in zip(survivors, embeddings):
            dup_of = next(
                (k for k, kv in zip(kept, kept_vecs) if cosine(vec, kv) > NEAR_DUP_THRESHOLD),
                None,
            )
            if dup_of is None:
                kept.append(doc)
                kept_vecs.append(vec)
            else:
                near_dupes += 1
                dup_of.setdefault("merged_urls", []).append(doc["url"])
        survivors = kept

    return {"docs": survivors, "exact_dupes": exact_dupes, "near_dupes": near_dupes}


def group_near_duplicate_claims(
    claims: list[dict], embeddings: list[list[float]]
) -> list[list[int]]:
    """Cluster claim indices with cosine > threshold (single-link, order-stable)."""
    parent = list(range(len(claims)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            if cosine(embeddings[i], embeddings[j]) > NEAR_DUP_THRESHOLD:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(claims)):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda g: g[0])

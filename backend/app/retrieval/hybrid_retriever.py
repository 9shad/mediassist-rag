from typing import Any

import numpy as np
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config import settings
from app.ingestion.embedder import embed_query


def _build_rbac_filter(role: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="access_roles",
                match=models.MatchValue(value=role),
            ),
        ],
    )


def _compute_query_sparse(query: str) -> models.SparseVector:
    import re
    tokens = re.findall(r"\w+", query.lower())
    token_counts: dict[str, int] = {}
    for t in tokens:
        token_counts[t] = token_counts.get(t, 0) + 1
    indices = [hash(t) % (2**31) for t in token_counts]
    values = [float(c) for c in token_counts.values()]
    return models.SparseVector(indices=indices[:512], values=values[:512])


def hybrid_retrieve(
    question: str,
    role: str,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    try:
        client = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            timeout=5,
            check_compatibility=False,
        )
        client.get_collections()
    except Exception as e:
        logger.warning(f"Qdrant not available: {e}")
        return []

    query_dense = embed_query(question)
    rbac_filter = _build_rbac_filter(role)

    logger.debug(f"Hybrid retrieve: role={role}, top_k={top_k}")

    query_sparse = _compute_query_sparse(question)

    result = client.query_points(
        collection_name=settings.qdrant_collection,
        prefetch=[
            models.Prefetch(query=query_dense, using="dense", limit=top_k * 2),
            models.Prefetch(query=query_sparse, using="sparse", limit=top_k * 2),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        query_filter=rbac_filter,
        limit=top_k,
        with_payload=True,
        timeout=10,
    )

    if hasattr(result, "points"):
        points = result.points
    else:
        points = getattr(result, "result", result)

    candidates = []
    for point in points:
        payload = point.payload or {}
        score = point.score if hasattr(point, "score") else 0.0
        candidates.append({
            "id": str(point.id) if hasattr(point, "id") else "",
            "score": score,
            "text": payload.get("text", ""),
            "source_document": payload.get("source_document", ""),
            "section_title": payload.get("section_title", ""),
            "collection": payload.get("collection", ""),
            "chunk_type": payload.get("chunk_type", ""),
        })

    logger.debug(f"Retrieved {len(candidates)} candidates for role={role}")
    return candidates

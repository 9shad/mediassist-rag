from typing import Any

from loguru import logger

from app.core.config import settings

try:
    from sentence_transformers import CrossEncoder

    _model = None

    def _get_model() -> "CrossEncoder":
        global _model
        if _model is None:
            logger.info(f"Loading local reranker model: {settings.reranker_model_name}")
            _model = CrossEncoder(settings.reranker_model_name, device="cpu")
        return _model

    def _score(query: str, texts: list[str]) -> list[float]:
        model = _get_model()
        pairs = [[query, text] for text in texts]
        scores = model.predict(pairs, show_progress_bar=False)
        return [float(s) for s in scores]

except ImportError:
    logger.warning("sentence-transformers CrossEncoder not available, falling back to order-based scores")

    def _get_model() -> None:
        return None

    def _score(query: str, texts: list[str]) -> list[float]:
        return [1.0 - i * 0.01 for i in range(len(texts))]


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    top_n: int = 3,
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    texts = [c.get("text", "") for c in candidates]
    scores = _score(query, texts)

    scored_candidates = []
    for candidate, score in zip(candidates, scores):
        candidate["rerank_score"] = score
        scored_candidates.append(candidate)

    scored_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
    logger.debug(f"Reranker scores: {[round(c['rerank_score'], 3) for c in scored_candidates]}")

    return scored_candidates[:top_n]

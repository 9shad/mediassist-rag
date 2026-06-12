import numpy as np
from loguru import logger

from app.core.config import settings

try:
    from sentence_transformers import SentenceTransformer

    _model = None

    def _get_model() -> "SentenceTransformer":
        global _model
        if _model is None:
            logger.info(f"Loading local embedding model: {settings.embedding_model_name}")
            _model = SentenceTransformer(
                settings.embedding_model_name,
                device=settings.embedding_device,
            )
        return _model

except ImportError:
    logger.warning("sentence-transformers not installed, falling back to API-based embeddings")

    import httpx

    _model = None

    def _get_model() -> None:
        return None

    def _call_embedding_api(texts: list[str]) -> list[list[float]]:
        api_key = settings.embedding_api_key or settings.llm_api_key
        if not api_key:
            dims = 1024
            return [[0.0] * dims for _ in texts]

        response = httpx.post(
            f"{settings.embedding_base_url}/embeddings",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            json={
                "model": settings.embedding_model_name,
                "input": texts,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        sorted_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]


def embed_texts(texts: list[str]) -> list[np.ndarray]:
    model = _get_model()
    if model is not None:
        embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return [np.array(emb, dtype=np.float32) for emb in embeddings]

    results = []
    batch_size = 20
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        embeddings = _call_embedding_api(batch)
        results.extend([np.array(emb, dtype=np.float32) for emb in embeddings])
        logger.debug(f"Embedded batch {i // batch_size + 1}/{(len(texts) - 1) // batch_size + 1}")
    return results


def embed_query(text: str) -> list[float]:
    model = _get_model()
    if model is not None:
        return model.encode(text, normalize_embeddings=True).tolist()
    embeddings = _call_embedding_api([text])
    return embeddings[0]

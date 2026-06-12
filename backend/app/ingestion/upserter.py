import hashlib
from typing import Optional

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config import settings
from app.core.enums import COLLECTION_ROLES


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def ensure_collection(client: QdrantClient) -> None:
    collections = client.get_collections().collections
    if settings.qdrant_collection not in [c.name for c in collections]:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config={
                "dense": models.VectorParams(
                    size=1024,
                    distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                ),
            },
        )
        logger.info(f"Created collection '{settings.qdrant_collection}' with dense+sparse vectors")

        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="access_roles",
            field_type=models.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="collection",
            field_type=models.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="source_document",
            field_type=models.PayloadSchemaType.KEYWORD,
        )
    else:
        logger.info(f"Collection '{settings.qdrant_collection}' already exists")


def chunk_id(source_document: str, index: int) -> str:
    raw = f"{source_document}:{index}"
    return hashlib.md5(raw.encode()).hexdigest()


def upsert_chunks(
    client: QdrantClient,
    chunks: list[dict],
    dense_embeddings: list,
    source_document: str,
    collection: str,
    batch_size: int = 100,
) -> int:
    access_roles = [r.value for r in COLLECTION_ROLES.get(collection, COLLECTION_ROLES["general"])]

    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, dense_embeddings)):
        sparse_embedding = _compute_sparse(chunk["text"])
        points.append(
            models.PointStruct(
                id=chunk_id(source_document, i),
                vector={
                    "dense": embedding.tolist(),
                    "sparse": sparse_embedding,
                },
                payload={
                    "source_document": source_document,
                    "collection": collection,
                    "access_roles": access_roles,
                    "section_title": chunk["section_title"],
                    "chunk_type": chunk["chunk_type"],
                    "text": chunk["text"],
                },
            )
        )

    total = 0
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        client.upsert(
            collection_name=settings.qdrant_collection,
            points=batch,
        )
        total += len(batch)
        logger.info(f"Upserted {total}/{len(points)} chunks")

    return total


def _compute_sparse(text: str) -> models.SparseVector:
    import re
    tokens = re.findall(r"\w+", text.lower())
    token_counts: dict[str, int] = {}
    for t in tokens:
        token_counts[t] = token_counts.get(t, 0) + 1

    indices: list[int] = []
    values: list[float] = []
    for idx, (token, count) in enumerate(sorted(token_counts.items())):
        indices.append(hash(token) % (2**31))
        values.append(float(count))

    return models.SparseVector(
        indices=indices[:512],
        values=values[:512],
    )

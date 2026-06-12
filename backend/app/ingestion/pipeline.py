from pathlib import Path
from typing import Optional

from loguru import logger

from app.ingestion.chunker import hierarchical_chunk
from app.ingestion.embedder import embed_texts
from app.ingestion.parser import get_collection_from_path, parse_document
from app.ingestion.upserter import ensure_collection, get_qdrant_client, upsert_chunks


def process_document(filepath: str, dry_run: bool = False) -> int:
    logger.info(f"Processing {filepath}")
    raw_chunks = parse_document(filepath)
    logger.info(f"Extracted {len(raw_chunks)} raw sections from {Path(filepath).name}")

    chunks = hierarchical_chunk(raw_chunks)
    logger.info(f"Split into {len(chunks)} hierarchical chunks")

    if dry_run:
        for c in chunks:
            logger.debug(f"  [{c['chunk_type']}] {c['section_title']}: {c['text'][:80]}...")
        return len(chunks)

    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)
    logger.info(f"Generated {len(embeddings)} dense embeddings")

    client = get_qdrant_client()
    ensure_collection(client)

    collection = get_collection_from_path(filepath)
    source_document = Path(filepath).name

    total = upsert_chunks(client, chunks, embeddings, source_document, collection)
    logger.info(f"Upserted {total} chunks from {source_document} into collection '{collection}'")
    return total


def run_ingestion(data_dir: str, dry_run: bool = False) -> int:
    total = 0
    for ext in ("*.pdf", "*.PDF", "*.md", "*.MD"):
        for filepath in Path(data_dir).rglob(ext):
            total += process_document(str(filepath), dry_run=dry_run)
    logger.info(f"Ingestion complete. Total chunks: {total}")
    return total

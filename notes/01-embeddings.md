# Embeddings — Local Vectorization with sentence-transformers

## Why Local Embeddings?

Most RAG systems rely on API-based embedding providers (OpenAI, Cohere, etc.). This project uses **local embeddings** via `sentence-transformers` to:
- Eliminate API key requirements and per-request costs
- Keep all data on-premises (no text sent to third-party APIs)
- Allow offline operation
- Provide deterministic, reproducible embeddings

## Model: `intfloat/multilingual-e5-large-instruct`

We use the [intfloat/multilingual-e5-large-instruct](https://huggingface.co/intfloat/multilingual-e5-large-instruct) model, a 335M-parameter multilingual embedding model.

### Key properties:
- **Output dimension:** 1024 (used as the `dense` vector in Qdrant)
- **Normalized embeddings:** Cosine similarity can be used as the distance metric
- **Multilingual:** Supports 100+ languages, important for mixed-language medical documents
- **Instruction-tuned:** Can follow task-specific prefixes (though we use it as a general-purpose encoder)

### Why this model?
| Factor | Choice | Alternative |
|---|---|---|
| Size | 335M params (~2 GB on disk) | Larger models like `gte-large` (~5 GB) require more RAM |
| Dimension | 1024 | Balances accuracy vs storage cost in Qdrant |
| Multilingual | Yes — handles English + regional languages | Many models are English-only |
| License | MIT | Commercial-friendly |

## Implementation

**File:** `backend/app/ingestion/embedder.py`

### Lazy Singleton Pattern

```python
_model = None

def _get_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        _model = SentenceTransformer(
            settings.embedding_model_name,
            device=settings.embedding_device,
        )
    return _model
```

The model is loaded once and cached globally. On Docker startup, it's pre-loaded via the `on_event("startup")` handler in `main.py` to avoid cold-start latency on the first query.

### Embedding Functions

**`embed_texts(texts: list[str]) -> list[np.ndarray]`**
- Used during ingestion to vectorize document chunks
- Processes multiple texts in a batch (GPU-efficient when available)
- Returns normalized float32 numpy arrays

**`embed_query(text: str) -> list[float]`**
- Used at query time to vectorize the user's question
- Returns a Python list (for JSON serialization to Qdrant API)
- Both functions normalize embeddings (`normalize_embeddings=True`), which means cosine similarity is equivalent to dot product

### Fallback Mechanism

If `sentence-transformers` is not installed (e.g., on systems where PyTorch can't be installed), the code falls back to an API-based embedding approach:

```python
except ImportError:
    def _call_embedding_api(texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{settings.embedding_base_url}/embeddings",
            ...
        )
```

This ensures the system works even without local ML dependencies, though local mode is the primary path.

## How Embeddings Work (Conceptual)

1. **Tokenization:** Text is split into tokens (subwords) by the model's tokenizer
2. **Encoding:** Tokens pass through transformer layers that build contextual representations
3. **Pooling:** The final hidden states are pooled into a single vector (mean pooling)
4. **Normalization:** The vector is L2-normalized to unit length

The result is a fixed-length vector (1024 dimensions) that captures the semantic meaning of the input text. Semantically similar texts produce vectors that are close together in cosine distance.

## Integration with Qdrant

Embeddings are stored as named vectors in Qdrant:

```python
# During ingestion (in upserter.py)
client.upsert(
    collection_name=settings.qdrant_collection,
    points=[
        models.PointStruct(
            id=point_id,
            vector={
                "dense": dense_vector,    # 1024-dim float32
                "sparse": sparse_vector,  # BM25-based sparse vector
            },
            payload=metadata,
        )
    ],
)
```

The `dense` vector is the neural embedding from `sentence-transformers`. The `sparse` vector is computed separately from token frequencies — see the [Hybrid Search](./03-hybrid-search.md) note for details.

## Performance Considerations

| Operation | Time (CPU, Docker) | Notes |
|---|---|---|
| Model load (cold start) | ~30 seconds | Done once at startup |
| Embed 1 query | ~50-100ms | Single text |
| Embed 100 chunks | ~2-5 seconds | Batch-processed |
| Embed 1000 chunks | ~20-40 seconds | Full document ingestion |

The model runs on CPU inside Docker (no GPU pass-through). For production, mounting a GPU would reduce latency by 10-50x.

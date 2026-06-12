# Hybrid Search — Combining Dense and Sparse Retrieval

## Why Hybrid Search?

Two complementary retrieval approaches exist:

| Approach | Strengths | Weaknesses |
|---|---|---|
| **Dense (neural)** | Semantic understanding, handles synonyms, matches concepts | Misses exact keyword matches, requires training data |
| **Sparse (BM25)** | Exact keyword matching, handles rare terms, zero training | No semantic understanding, misses conceptually related results |

Hybrid search combines both: the dense vector captures "what does this mean?" while the sparse vector captures "what words does this contain?". The scores are fused using **Reciprocal Rank Fusion (RRF)**.

## Architecture

```
User Query
    │
    ├──► Embedder (sentence-transformers) ──► Dense Vector (1024-dim)
    │
    └──► Token Frequency ──► Sparse Vector (BM25-style)
    │
    ▼
Qdrant Hybrid Query (prefetch dense + sparse → RRF fusion)
    │
    ▼
Top-10 candidates (with RBAC filter applied)
```

## Implementation

**File:** `backend/app/retrieval/hybrid_retriever.py`

### Step 1: Dense Query Vector

```python
query_dense = embed_query(question)
```

Uses the same `sentence-transformers` model as ingestion to encode the question into a 1024-dim vector.

### Step 2: Sparse Query Vector

```python
def _compute_query_sparse(query: str) -> models.SparseVector:
    tokens = re.findall(r"\w+", query.lower())
    token_counts: dict[str, int] = {}
    for t in tokens:
        token_counts[t] = token_counts.get(t, 0) + 1
    indices = [hash(t) % (2**31) for t in token_counts]
    values = [float(c) for c in token_counts.values()]
    return models.SparseVector(indices=indices[:512], values=values[:512])
```

This is a simplified BM25 approximation:
1. Tokenizes the query into words
2. Counts token frequencies
3. Maps each unique token to an index via `hash(token) % 2^31`
4. Uses frequency as the weight (coarser than full BM25 IDF, but effective in practice)

The sparse vector captures exact keyword matches, complementing the dense vector's semantic understanding.

### Step 3: RBAC Filter

```python
def _build_rbac_filter(role: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="access_roles",
                match=models.MatchValue(value=role),
            ),
        ],
    )
```

This is the **critical RBAC enforcement layer**. Every query includes a metadata filter that restricts results to chunks where the user's role appears in the `access_roles` list. The LLM never sees chunks outside the user's permissions because they're filtered at the database level.

### Step 4: Qdrant Hybrid Query with RRF

```python
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
)
```

**Key parameters:**
- `prefetch`: Two parallel searches — one on the `dense` vector, one on the `sparse` vector
- `limit=top_k * 2` for each prefetch: Each search returns 2x the final count to give the fusion algorithm enough candidates
- `FusionQuery(fusion=RRF)`: Combines the two ranked lists using Reciprocal Rank Fusion
- `query_filter`: The RBAC filter is applied to **both** prefetches

### Reciprocal Rank Fusion (RRF)

RRF combines multiple ranked lists into a single ranking:

```
score(d) = Σ 1 / (k + rank_i(d))
```

Where:
- `d` is a document
- `rank_i(d)` is the rank of document `d` in list `i`
- `k` is a constant (typically 60)

This means:
- A document ranked #1 in one search and #100 in another scores higher than one ranked #50 in both
- The formula is robust to score distributions (unlike averaging, which requires normalized scores)

### Step 5: Response Assembly

```python
candidates = []
for point in points:
    payload = point.payload or {}
    candidates.append({
        "id": str(point.id),
        "score": point.score,  # Combined RRF score
        "text": payload.get("text", ""),
        "source_document": payload.get("source_document", ""),
        "section_title": payload.get("section_title", ""),
        "collection": payload.get("collection", ""),
        "chunk_type": payload.get("chunk_type", ""),
    })
```

The top 10 candidates are passed to the [reranker](./04-reranker.md) for re-scoring.

## Why Qdrant for Hybrid Search?

Qdrant natively supports hybrid search with:
- **Named vectors** — multiple vector types per point (`dense` and `sparse`)
- **Built-in RRF fusion** — no custom implementation needed
- **Metadata filters** — applied at query time, efficient even at scale
- **Performance** — the combination of prefetch + fusion is optimized internally

## Comparison: Dense Only vs Hybrid

| Scenario | Dense Only | Hybrid | 
|---|---|---|
| "What is the dosage for malaria?" | ✅ Finds dosage sections | ✅ Same |
| "Show me the form 27B/9" | ❌ Unlikely to match semantically | ✅ Matches exact keyword |
| "How to calibrate device model X-200?" | Might find general calibration docs | ✅ Guarantees X-200 is matched |
| "Insurance code J45.0" | ❌ Might match "asthma" code J45 | ✅ Matches exact string |

Hybrid search is particularly important for medical documents where exact codes, medication names, and procedure IDs must be matched precisely.

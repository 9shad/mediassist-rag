# System Architecture — End-to-End Data Flow

## Overview

MediBot is a **Hybrid RAG System** deployed via Docker Compose with three services. Documents are ingested into Qdrant (vector DB), queries are routed between hybrid search and SQL RAG, and responses are streamed to a modern Next.js frontend.

## High-Level Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│              │     │                  │     │              │
│  Next.js     │◄───►│  FastAPI         │◄───►│  Qdrant      │
│  Frontend    │     │  Backend         │     │  Vector DB   │
│  :3000       │     │  :8000           │     │  :6333       │
│              │     │                  │     │              │
│  - Login UI  │     │  - JWT Auth      │     │  - Dense vec │
│  - Chat UI   │     │  - Hybrid Search │     │  - Sparse    │
│  - Streaming │     │  - SQL RAG       │     │  - Metadata  │
│  - Themes    │     │  - Reranker      │     │  - RBAC filt │
│  - History   │     │  - Chat DB       │     │              │
│  - Context   │     │  - Context Mgr   │     │              │
│              │     │  - Cleanup Task  │     │              │
│              │     │  - Ingestion     │     │              │
└──────────────┘     └────────┬─────────┘     └──────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  SQLite           │
                    │  mediassist.db    │
                    │  (claims +        │
                    │   maintenance)    │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  SQLite           │
                    │  mediassist_chats │
                    │  .db              │
                    │  (conversations + │
                    │   messages)       │
                    └──────────────────┘
```

## Services

### 1. Qdrant (Vector Database)

**Port:** 6333 (gRPC + HTTP)

Qdrant is the vector database that stores document chunks with:
- **Dense vectors** (1024-dim, from `sentence-transformers`)
- **Sparse vectors** (BM25-style token frequencies)
- **Payload/metadata** (source_document, section_title, access_roles, collection)

Qdrant supports **hybrid search** natively — dense and sparse vectors are combined via **Reciprocal Rank Fusion (RRF)** in a single query.

**Healthcheck:**
```yaml
healthcheck:
  test: ["CMD-SHELL", "apt-get update && apt-get install -y curl && curl -f http://localhost:6333/health || exit 1"]
  interval: 10s
  retries: 5
```

### 2. FastAPI Backend

**Port:** 8000

The Python backend orchestrates all business logic:

| Module | Responsibility |
|---|---|
| `api/routes.py` | HTTP endpoints for login, chat, streaming, conversations, health |
| `api/deps.py` | JWT verification, role extraction |
| `core/security.py` | JWT creation and decoding |
| `core/config.py` | Environment-based configuration (LLM keys, Qdrant host, model names) |
| `core/enums.py` | Roles, collections, RBAC mappings, demo users |
| `core/llm_client.py` | LLM API client (non-streaming + streaming), summarization |
| `core/chat_db.py` | SQLite operations for conversations + messages with embeddings |
| `core/context_manager.py` | Multi-turn context assembly (sliding window + vector memory + summarization) |
| `core/cleanup.py` | Background task to delete old conversations |
| `ingestion/parser.py` | PDF/Markdown document parsing |
| `ingestion/chunker.py` | Hierarchical token-aware chunking |
| `ingestion/embedder.py` | Local sentence-transformers embeddings |
| `ingestion/upserter.py` | Qdrant upsert operations |
| `retrieval/hybrid_retriever.py` | Qdrant hybrid search with RBAC filter |
| `retrieval/reranker.py` | Local Cross-Encoder reranking |
| `retrieval/sql_rag.py` | Natural language → SQL → answer pipeline |
| `retrieval/orchestrator.py` | Query routing, context assembly, answer generation |

### 3. Next.js Frontend

**Port:** 3000

| Component | Responsibility |
|---|---|
| `LoginForm.tsx` | Themed login with demo user dropdown |
| `ChatInterface.tsx` | Full chat UI with streaming, history sidebar, themes, markdown |

## Data Flow — Query Processing

### Request Path (Non-Streaming)

```
1. POST /api/v1/chat {question, conversation_id}
2. require_role() → extracts role + username from JWT
3. If conversation_id provided, load context:
   ├── Load conversation history + embeddings from chat DB
   ├── Extract sliding window (last N turns)
   ├── Vector memory search (semantic over all prior Qs)
   ├── Load running summary of evicted content
   └── Deduplicate + merge within token budget
4. process_query(question, role, conversation_id)
5. _is_analytical(question)? → No → Hybrid RAG
6. hybrid_retrieve(question, role, top_k=10)
   ├── Qdrant query with RBAC filter (access_roles == role)
   ├── Dense prefetch (neural embedding)
   ├── Sparse prefetch (BM25 tokens)
   └── RRF fusion → 10 candidates
7. rerank(question, candidates, top_n=3)
   ├── Cross-Encoder scores each (query, text) pair
   └── Select top 3 by relevance
8. assemble RAG context from reranked chunks
9. generate_answer(question, context, history_context)
   ├── LLM API call (Groq/Together/OpenAI)
   └── Return answer + sources + retrieval_type
10. Save turn (question + answer + embedding) to chat DB
11. condense_if_needed() → summarize evicted content if over budget
```

### Response Path (Streaming)

Same as above through step 8, then:

```
9. generate_answer_stream(question, context, history_context)
   ├── Open SSE connection to LLM with assembled messages
   ├── Parse stream for <think> tags
   ├── yield event: think / data: "reasoning text"
   ├── yield event: answer / data: "response text"
   └── yield event: sources / data: {sources, usage}
10. Backend saves turn (question + full answer + embedding) via ContextManager
11. condense_if_needed() → summarize oldest turns if token budget exceeded
12. Frontend displays streaming response
```

### Analytical Query Path

```
1. POST /api/v1/chat/stream {question: "How many claims were denied?"}
2. require_role() → role = billing_executive
3. _is_analytical(question)? → Yes
4. Role in SQL_RAG_ROLES? → Yes (billing_executive)
5. sql_rag_chain(question)
   ├── _generate_sql(question) → "SELECT COUNT(*) FROM claims WHERE status='Denied'"
   ├── _clean_sql(sql) → strip markdown, validate SELECT
   ├── _execute_sql(sql) → [{count: 3}]
   └── _generate_answer_from_results → "There are 3 denied claims."
6. Stream result as single answer event + sources event
```

## Data Flow — Ingestion

```
PDF/MD files in mediassist_data/docs/{collection}/
    │
    ▼
parse_document(filepath)
    ├── parse_pdf() → [{"text", "section_title", "chunk_type"}, ...]
    └── parse_markdown() → [{"text", "section_title", "chunk_type"}, ...]
    │
    ▼
hierarchical_chunk(raw_chunks)
    ├── Prepend section context: "[Section: {path}] {text}"
    ├── Count tokens (tiktoken)
    └── Split if > 512 tokens (word-boundary aware)
    │
    ▼
Embed each chunk → dense vector (1024-dim)
    │
    ▼
Compute sparse vector (token frequencies)
    │
    ▼
Upsert to Qdrant (dense + sparse vectors + payload metadata)
```

## Data Stores

| Store | Technology | Data | Location |
|---|---|---|---|
| Vector DB | Qdrant | Document chunks with dense/sparse vectors | Docker volume |
| Claims DB | SQLite | Claims + maintenance tickets | `mediassist_data/mediassist.db` |
| Chat DB | SQLite | Conversations + messages | `mediassist_data/mediassist_chats.db` |

## Docker Composition

```yaml
services:
  qdrant:
    image: qdrant/qdrant:v1.18.2
    ports: ["6333:6333"]
    volumes: ["./mediassist_data/qdrant_storage:/qdrant/storage"]

  backend:
    build: ./backend
    ports: ["8000:8000"]
    volumes: ["./mediassist_data:/mediassist_data"]
    env_file: .env
    depends_on: { qdrant: { condition: service_healthy } }

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on: [backend]
```

**Volume mount:** `./mediassist_data:/mediassist_data` — both the claims database and the chat history database are persisted to the host.

## Model Pre-loading

On startup, the backend loads both ML models to eliminate cold-start latency:

```python
@app.on_event("startup")
async def warm_models():
    logger.info("Pre-loading embedding model...")
    from app.ingestion.embedder import _get_model as get_embedder
    get_embedder()
    logger.info("Pre-loading reranker model...")
    from app.retrieval.reranker import _get_model as get_reranker
    get_reranker()
    logger.info("Models loaded successfully")
```

This adds ~3-4 minutes to startup time but ensures all subsequent queries respond instantly.

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Local embeddings + reranker** | No API keys needed; data never leaves the server |
| **Hybrid search** | Combines semantic understanding with exact keyword matching |
| **Retrieve-then-rerank** | Fast first pass (10 candidates) + accurate second pass (3 candidates) |
| **Three-layer RBAC** | Defense in depth — JWT + Qdrant filter + route restriction |
| **Backend chat persistence** | Survives cache clear; scoped per user; supports history across devices |
| **SSE streaming** | Real-time UX; works with POST (unlike native EventSource) |
| **Three-layer context** | Sliding window + vector memory + running summary for multi-turn conversations |
| **Incremental summarization** | Evicted turns condensed into running summary; existing summary merged with new |
| **Auto-cleanup** | Background task deletes conversations older than retention period |
| **SQL RAG as fallback** | Works without LLM API via regex patterns |
| **PyMuPDF (not Docling)** | Docling had build dependency issues; PyMuPDF provides equivalent parsing |

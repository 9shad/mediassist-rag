# MediBot — Production-Grade Implementation Plan

## Project Structure

```
Medibot_Assignment_Resources/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routes (login, chat, collections, health)
│   │   ├── core/         # Config, enums, exceptions, logging, security (JWT)
│   │   ├── ingestion/    # Docling parser, hierarchical chunker, Qdrant upsert
│   │   ├── retrieval/    # Hybrid retriever (dense+BM25), reranker, SQL RAG
│   │   ├── models/       # Pydantic request/response schemas
│   │   └── main.py       # FastAPI app factory
│   ├── tests/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/          # Next.js pages/routes
│   │   ├── components/   # LoginForm, ChatInterface, RoleBadge, SourceCard
│   │   └── lib/          # API client, auth context
│   ├── Dockerfile
│   └── package.json
├── data/                 # PDFs + DB (mounted volume)
├── docker-compose.yml    # Backend + Qdrant + Frontend
├── .env
└── README.md
```

## Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| **Vector DB** | Qdrant (Docker) | Native hybrid (dense+sparse) in single query, metadata filters at query layer |
| **Embedding Model** | `intfloat/multilingual-e5-large-instruct` | Strong multilingual medical embedding, 1024-dim |
| **Sparse Encoder** | Qdrant BM25 (built-in) | No extra infra; Qdrant 1.12+ natively supports sparse vectors |
| **Reranker** | `BAAI/bge-reranker-v2-m3` | Cross-encoder, strong relevance scoring for medical text |
| **LLM** | Together AI / Groq (cloud API) | Low-latency inference, no GPU overhead |
| **PDF Parsing** | Docling (`ds4sd/docling`) | Structural awareness, table extraction, hierarchical layout |
| **Backend** | FastAPI + Uvicorn (async) | Native async, Pydantic v2 validation, OpenAPI docs |
| **Frontend** | Next.js 14 (App Router) | React Server Components, streaming, edge-compatible |
| **Auth** | JWT (python-jose + passlib) | Stateless, no session store needed |
| **Container** | Docker Compose | Single-command infra spin-up |
| **Testing** | pytest + pytest-asyncio + httpx | Async test support, API integration tests |

## Component Implementation Strategy

### Phase 1: Scaffold & Auth
- Docker Compose with backend, Qdrant, frontend services
- FastAPI app factory with config, logging, exception handlers
- JWT auth with 5 demo users, `/login` and `/health` endpoints
- Pydantic models for all request/response schemas

### Phase 2: Document Ingestion
```
DoclingPDFParser
  → HierarchicalChunker (section → subsection → paragraph/table, then token-limit)
  → MetadataEnricher (source_document, collection, access_roles, section_title, chunk_type)
  → EmbeddingGenerator (dense via E5, sparse via Qdrant BM25 tokenizer)
  → QdrantUpserter (batch upsert with named vectors: "dense" + "sparse")
```
- Standalone CLI script, not server startup
- Upsert in batches of 100 with retry + exponential backoff
- Idempotent — skip already-indexed documents by hash

### Phase 3: Hybrid RAG
- Embedding client wrapping the E5 model (via sentence-transformers or API)
- Qdrant hybrid `query_points()` with both named vectors
- Metadata filter: `access_roles` MUST contain user's role
- Built-in Qdrant fusion (RRF)

### Phase 4: Reranker
- Cross-encoder scores each (query, chunk) pair jointly
- Initial retrieval fetches top-10, reranker narrows to top-3
- Log scores for eval visibility

### Phase 5: SQL RAG
- Pre-loaded DB schema for LLM context
- Step 1: LLM translates question → SQL (few-shot prompted)
- Step 2: Regex extract SQL from LLM output
- Step 3: Execute read-only against SQLite
- Step 4: LLM produces natural language answer from results
- Only available to `billing_executive` and `admin`

### Phase 6: FastAPI /chat Orchestrator
- Extracts role from JWT
- Classifies question type (analytical vs document)
- Routes to SQL RAG or Hybrid RAG
- Composes `{answer, sources, retrieval_type, role}` response

### Phase 7: Next.js Frontend
- AuthContext storing JWT + role + accessible collections
- LoginPage with 5 demo user dropdown
- ChatInterface with streaming-like message display
- RoleBadge in sidebar showing current role + collections
- SourceCard collapsible citation
- RBAC block message for restricted queries

### Phase 8: Evaluation & Docs
- 3+ adversarial prompt tests documented with screenshots
- Architecture diagram (Mermaid)
- Setup instructions with demo credentials
- README with all required sections

## Scalability & Production Optimizations

| Concern | Solution |
|---|---|
| Cold start / slow ingestion | Run ingestion as one-off CLI script, not at server startup |
| LLM latency | Async HTTP client with connection pooling |
| Qdrant availability | Docker healthcheck, retry connection with backoff |
| Embedding caching | LRU cache for query embeddings (same query within TTL) |
| Rate limiting | `slowapi` middleware on `/chat` endpoint |
| Secret management | All API keys in `.env`, never hardcoded |
| Observability | `loguru` for structured JSON logs, request ID middleware |
| Error boundaries | Graceful fallbacks |
| Stateless scaling | No local state — scale horizontally behind nginx |

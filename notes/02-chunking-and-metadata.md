# Document Parsing and Chunking — From Raw Files to Searchable Chunks

## Overview

Before documents can be searched, they must be parsed, chunked, and enriched with metadata. This note covers the complete ingestion pipeline from raw files to Qdrant points.

## Pipeline Flow

```
PDF/MD File → Parser → Raw Chunks → Hierarchical Chunker → Embedder → Qdrant Upserter
                         ↓
                   [section_title, chunk_type, text]
```

## 1. Parser — Structural Document Parsing

**File:** `backend/app/ingestion/parser.py`

### PDF Parsing (`parse_pdf`)

Uses **PyMuPDF (fitz)** to extract text blocks from each page with structural awareness.

**Heading Detection Strategy:**

Three complementary techniques are used:

1. **Font size thresholding** (`font_size > 16 → heading`): Larger text is likely a heading
2. **Regex patterns**: Matches `# Heading` (Markdown-style) or `ALL CAPS TITLE:` patterns in the extracted text
3. **Depth-based heading levels**:
   - `font_size > 20` → level 1 (major section)
   - `font_size > 14` → level 2 (subsection)
   - Otherwise → level 3 (sub-subsection)

**Section Stack:**

A `section_stack` list maintains the current heading hierarchy:

```python
# When a heading is found at level N:
section_stack = section_stack[:N-1]  # Truncate deeper levels
section_stack.append(heading_text)   # Add new heading
```

This builds a breadcrumb trail like: `Treatment Protocols > Malaria > Dosage`

**Text Blocks (`type == 0`):**
- Extracted per-page from `page.get_text("dict")` blocks
- Each block contains spans with font size, text content
- Non-heading text blocks are tagged as `ChunkType.TEXT`

**Image Blocks (`type == 1`):**
- Image blocks with text content (e.g., embedded table-as-image with alt text) are extracted as `ChunkType.TABLE`

### Markdown Parsing (`parse_markdown`)

Simpler than PDF parsing since markdown has explicit heading markers (`#`, `##`, `###`). Same section stack approach, same chunk types.

### Collection Detection

```python
def get_collection_from_path(filepath: str) -> str:
    # Extracts collection name from path:
    # mediassist_data/docs/clinical/treatment.pdf → "clinical"
```

Documents are organized in subdirectories matching collection names (`clinical/`, `nursing/`, `billing/`, `equipment/`, `general/`).

## 2. Chunker — Hierarchical Chunking

**File:** `backend/app/ingestion/chunker.py`

### Why Hierarchical Chunking?

Simple fixed-size chunking breaks document structure (a chunk might start mid-sentence or split a section heading from its content). Hierarchical chunking respects the document's natural hierarchy.

### Algorithm

**Step 1:** Each chunk from the parser already has a `section_title` breadcrumb.

**Step 2:** Context is prepended to the text:

```python
contextual_text = f"[Section: {section}] {text}" if section else text
```

This gives the chunk awareness of its position in the document. Example:
```
[Section: Treatment Protocols > Malaria > Dosage]
The standard dosage for uncomplicated malaria in adults is 600mg...
```

**Step 3:** Token counting via `tiktoken`:

```python
def count_tokens(text: str) -> int:
    return len(TOKENIZER.encode(text))
```

Uses `cl100k_base` encoding (the tokenizer for GPT-4/Claude — provides consistent token counts regardless of the actual LLM used).

**Step 4:** If the chunk exceeds `MAX_TOKENS (512)`, it's split at word boundaries:

```python
for word in words:
    if current_tokens + word_tokens + prefix_tokens > MAX_TOKENS:
        sub_chunks.append(prefix + " ".join(current))
        current = [word]
        current_tokens = count_tokens(word)
    else:
        current.append(word)
        current_tokens += word_tokens
```

Each sub-chunk keeps the same `section_title` and `chunk_type` as the parent, and the section context prefix is re-added to each sub-chunk.

## 3. Metadata Schema

Every chunk stored in Qdrant carries this metadata:

| Field | Type | Example | Purpose |
|---|---|---|---|
| `text` | string | `"The standard dosage..."` | The chunk content (with section prefix) |
| `source_document` | string | `"treatment_protocols.pdf"` | Traceability back to the source file |
| `collection` | string | `"clinical"` | Collection grouping (for RBAC filtering) |
| `access_roles` | list[string] | `["doctor", "admin"]` | Which roles can access this chunk (derived from collection) |
| `section_title` | string | `"Treatment Protocols > Malaria > Dosage"` | Section breadcrumb |
| `chunk_type` | string | `"text"`, `"heading"`, `"table"` | Type of content |

### Access Roles Derivation

```python
COLLECTION_ROLES: dict[str, list[Role]] = {
    "general": [DOCTOR, NURSE, BILLING_EXECUTIVE, TECHNICIAN, ADMIN],
    "clinical": [DOCTOR, ADMIN],
    "nursing": [NURSE, DOCTOR, ADMIN],
    "billing": [BILLING_EXECUTIVE, ADMIN],
    "equipment": [TECHNICIAN, ADMIN],
}
```

Each chunk inherits `access_roles` from its collection. This is the foundation of the RBAC enforcement at the vector DB layer.

## 4. Embedding + Qdrant Upsert

**File:** `backend/app/ingestion/upserter.py`

After chunking, each chunk is:
1. Embedded to a 1024-dim dense vector (see [Embeddings](./01-embeddings.md))
2. A sparse vector is computed from token frequencies
3. Both are upserted to Qdrant as named vectors

```python
point = models.PointStruct(
    id=hash(chunk["text"]),  # Deterministic ID
    vector={
        "dense": dense_vector,
        "sparse": sparse_vector,
    },
    payload=metadata
)
```

## 5. Running Ingestion

```bash
docker-compose exec backend python scripts/ingest.py
```

The CLI entry point (`scripts/ingest.py`) walks `mediassist_data/docs/`, processes each PDF/MD file, and upserts to Qdrant. A `--dry-run` flag previews chunks without writing.

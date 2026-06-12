# Context Management — Multi-Turn Conversation Memory

## Overview

MediBot supports multi-turn conversations where previous exchanges inform the LLM's answers. Context is managed through a **three-layer architecture** that balances immediacy, semantic relevance, and token budgets.

## The Three Layers

```
                         Current Question
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐
  │ Sliding      │    │ Vector       │    │ Running          │
  │ Window       │    │ Memory       │    │ Summary          │
  │ (last N      │    │ (semantic    │    │ (compressed      │
  │  turns)      │    │  search)     │    │  evicted turns)  │
  └──────────────┘    └──────────────┘    └──────────────────┘
         │                     │                     │
         └──────────┬──────────┴──────────┬──────────┘
                    ▼                     ▼
             ┌──────────────┐   ┌──────────────────┐
             │ Immediate    │   │ Long-term        │
             │ context      │   │ memory + gist    │
             │ (referents,  │   │ (evicted content)│
             │  pronouns)   │   │                  │
             └──────────────┘   └──────────────────┘
                    │                     │
                    └──────────┬──────────┘
                               ▼
                    ┌──────────────────┐
                    │ Dedup + Merge    │
                    │ within token     │
                    │ budget           │
                    └──────────────────┘
                               │
                               ▼
                    ┌──────────────────┐
                    │ LLM Prompt       │
                    └──────────────────┘
```

### Layer 1: Sliding Window

**What:** The last N complete turns (configurable, default 8) are included verbatim in the prompt.

**Purpose:** Captures immediate conversational context — pronoun referents ("what about the other option?"), corrections ("no, I meant X"), and follow-up questions ("now update that for adults").

**Implementation:** Always included, always most recent turns. Oldest turns are evicted first when the window slides.

```python
def _sliding_window(self) -> list[dict]:
    max_turns = settings.sliding_window_turns * 2
    return self.turns[-max_turns:] if len(self.turns) > max_turns else list(self.turns)
```

### Layer 2: Vector Memory

**What:** Semantically similar past exchanges retrieved via embedding-based search across the entire conversation history.

**Purpose:** Finds relevant information from arbitrarily far back ("remember when we discussed X 30 messages ago?"). Uses the same `sentence-transformers` embedder as document retrieval.

**How it works:**
1. Each user message is embedded and stored in the `messages` table (`embedding` column, JSON float array)
2. At query time, the current question is embedded
3. Cosine similarity is computed against all prior user message embeddings
4. Top K (default 3) matching exchanges (Q+A pairs) are included, **deduplicated** against the sliding window
5. A threshold of 0.3 cosine similarity filters out irrelevant matches

```python
def _vector_search(self, question: str, sliding: list[dict]) -> list[dict]:
    q_emb = embed_query(question)
    scored = []
    sliding_ids = {t["id"] for t in sliding}
    for t in self.turns:
        if t["id"] in sliding_ids or not t["embedding"] or t["type"] != "user":
            continue
        sim = cosine_similarity(q_emb, t["embedding"])
        if sim < 0.3: continue
        scored.append((sim, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    # Return top K Q+A pairs
```

**Advantages over vector DB (Qdrant):**
- In-memory computation — no network call or Qdrant collection management
- Per-conversation isolation naturally (we only load this conversation's turns)
- Conversation history is small (<1000 turns), so brute-force cosine similarity is O(n) and fast

### Layer 3: Running Summary

**What:** A compressed textual summary of evicted conversation turns, stored in the `conversations` table (`summary` column).

**Purpose:** When the sliding window evicts old turns and vector retrieval might miss something important, the summary preserves the gist. It bridges the gap between "immediate context" and "semantic search."

**How it works:**
1. After each turn, `condense_if_needed()` checks if total context exceeds 80% of `context_max_tokens`
2. If over budget, the oldest Q+A pairs are evicted from the internal `turns` list
3. The evicted pairs are sent to the LLM via `summarize_turns()` which produces a concise summary
4. The summary is **merged with** the existing running summary
5. The updated summary is persisted to `mediassist_chats.db`

```python
def condense_if_needed(self) -> None:
    total = self._estimate_context_tokens("")
    if total < settings.context_max_tokens * 0.8:
        return
    evict = []
    kept = list(self.turns)
    for i in range(0, len(kept) - 1, 2):
        # Evict oldest Q+A pairs until under 70% budget
        ...
    summary_text = self._make_summary(evict)
    self.summary = summary_text
    update_summary(self.conversation_id, self.summary)
    self.turns = kept
```

## Token Budget Management

| Component | Budget (tokens) | Notes |
|---|---|---|
| System prompt | ~50 | Fixed |
| Current question | ~50 | Per-query |
| RAG context (docs) | ~4000 | Top 3 chunks from hybrid search |
| Sliding window | ~2000 | Last 8 turns (configurable) |
| Vector memory | ~1000 | Top 3 semantically relevant past exchanges |
| Running summary | ~300 | Compressed evicted content |
| Answer output | ~500 | Reserved for LLM generation |
| **Total** | **~7900** | Under 8K default context window |

All components are **token-budget aware** — if budget is exceeded, components are truncated in order of priority (RAG context > sliding window > vector memory > summary).

## Deduplication

Vector-retrieved exchanges that are already in the sliding window are excluded:

```python
sliding_ids = {t["id"] for t in sliding}
for t in self.turns:
    if t["id"] in sliding_ids:  # Skip if already in sliding window
        continue
```

This prevents duplicate content from wasting tokens.

## Summarization Engine

**File:** `backend/app/core/llm_client.py` — `summarize_turns()`

```python
SUMMARIZE_PROMPT = """You are a conversation summarizer. Given a conversation summary (if any)
and a set of new Q&A exchanges, produce an updated concise summary covering all key information.
Keep it under 300 tokens. Focus on: medical facts mentioned, user preferences, data points,
decisions made. Omit pleasantries."""

def summarize_turns(new_turns: str, existing_summary: str = "") -> str:
    prompt = f"Existing summary: {existing_summary}\n\nNew exchanges to incorporate:\n{new_turns}"
    return generate_answer(question=prompt, system_prompt=SUMMARIZE_PROMPT, max_tokens=300)
```

The summary is **incremental** — the existing summary is passed alongside new exchanges, and the LLM produces a merged/updated summary.

## Prompt Assembly

The final LLM prompt is assembled by `build_conversation_messages()`:

```python
def build_conversation_messages(system_prompt, question, context, history_context):
    parts = []
    if context:
        parts.append(f"Relevant Documents:\n{context}")
    if history_context:
        parts.append(history_context)
    user_content = f"Current Question: {question}"
    if parts:
        user_content = "\n\n---\n\n".join(parts) + f"\n\n---\n\n{user_content}"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
```

The assistant's response format:
```
Relevant Documents:
[Source: doc.pdf, Section: Malaria]
Malaria treatment protocol...

---

[Earlier Conversation Summary]
User asked about malaria symptoms, was told about fever cycles.

---

[Relevant Past Exchanges]
[Past: Q] What is the first-line treatment?
[Past: A] Artemisinin-based combination therapy (ACT)...

---

[Recent Conversation]
[User] What is the malaria treatment protocol?
[You] The standard treatment is ACT...

---

Current Question: What about pediatric dosing?
```

## Guardrails

| Guardrail | Implementation | Config |
|---|---|---|
| **Max context tokens** | Hard limit on total prompt size | `context_max_tokens` (default 8000) |
| **Max sliding turns** | Prevents unbounded window growth | `sliding_window_turns` (default 8) |
| **Max vector results** | Limits semantic search depth | `vector_memory_top_k` (default 3) |
| **Summary length cap** | Prevents summary from dominating budget | `summary_max_tokens` (default 300) |
| **Similarity threshold** | Filters weak vector matches | 0.3 cosine (hardcoded) |
| **Summary depth limit** | Prevents "summary of a summary" degradation | 3 layers (implicit via token budget) |
| **Deduplication** | No duplicate content from different layers | `sliding_ids` check |
| **RBAC re-validation** | JWT verified on every request | Token expiry handles this naturally |
| **Prompt injection** | Context is labeled with `[User]`/`[You]` tags | Labels clearly separate history from new input |

## Persistence

The context manager relies on two database tables:

### `conversations` table
| Column | Type | Purpose |
|---|---|---|
| `id` | TEXT PK | Unique conversation identifier |
| `summary` | TEXT | Running summary of evicted content |
| `updated_at` | TEXT | Last activity timestamp |

### `messages` table
| Column | Type | Purpose |
|---|---|---|
| `id` | TEXT PK | Unique message identifier |
| `conversation_id` | TEXT FK | Parent conversation |
| `type` | TEXT | `user` or `bot` |
| `text` | TEXT | Message content |
| `embedding` | TEXT | JSON float array of the question embedding |
| `created_at` | TEXT | Message timestamp |

## Auto-Cleanup

**File:** `backend/app/core/cleanup.py`

A background task periodically deletes old conversations:

```python
async def cleanup_old_conversations():
    while True:
        deleted = delete_old_conversations(settings.conversation_retention_days)
        await asyncio.sleep(settings.cleanup_interval_hours * 3600)
```

| Config | Default | Description |
|---|---|---|
| `CONVERSATION_RETENTION_DAYS` | 30 | Delete conversations older than this |
| `CLEANUP_INTERVAL_HOURS` | 1 | How often the cleanup task runs |

The cleanup cascade-deletes associated messages (SQLite `FOREIGN KEY ... ON DELETE CASCADE`).

## Follow-up Question Generation

After every response, the orchestrator calls `generate_followups(question, answer, context)` in `llm_client.py` to produce 3 contextual follow-up questions:

```python
FOLLOWUP_PROMPT = """Based on the conversation so far, suggest 3 concise follow-up questions
the user might want to ask next. Return ONLY a JSON array of strings, no other text."""

def generate_followups(question: str, answer: str, context: str = "") -> list[str]:
    # Retry up to 2 times with increasing temperature
    # Assistant priming: pre-fill "[" so the model completes a JSON array
    # stop: ["\n\n"] prevents trailing explanation
    # If both attempts fail: role-based hardcoded fallback questions
```

**Technique — Assistant Priming:** The assistant response is pre-filled with `"["` to force the model to complete a JSON array rather than output free text. Combined with `stop: ["\n\n"]`, this reliably produces parseable output.

**Fallback:** If both LLM attempts return empty or invalid JSON, role-appropriate hardcoded questions (`_fallback_followups`) are used instead of returning nothing.

The follow-ups are included in:
- **Streaming response:** `sources` SSE event → `data.followups`
- **Non-streaming response:** `ChatResponse.followups`

The frontend displays them as clickable chips below each bot message. Clicking a chip populates the input box for the user to send.

## Lifecycle

```
User sends message in conversation
    │
    ▼
1. Load context from DB:
   - Load conversation (summary)
   - Load all messages with embeddings
    │
    ▼
2. Build context layers:
   - Extract sliding window (last N turns)
   - Compute vector search (all turns vs current Q)
   - Deduplicate vector results against sliding window
   - Assemble within token budget
    │
    ▼
3. Get RAG context (documents or SQL)
    │
    ▼
4. Call LLM with assembled prompt
    │
    ▼
5. Save response:
   - Save user question + embedding
   - Save bot answer + usage
   - Update conversation updated_at
    │
    ▼
6. Condense if budget exceeded:
   - Check total context tokens
   - If >80% of budget, evict oldest Q+A pairs
   - Summarize evicted content into running summary
   - Persist updated summary
```

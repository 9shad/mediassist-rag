# Chat History — Persistent Conversations via Backend SQLite

## Overview

Chat history enables users to maintain multiple conversations, switch between them, and review past interactions. Unlike a localStorage-only approach, backend persistence ensures history survives cache clears, device switches, and browser restarts — and is scoped per user.

## Database Schema

**File:** `backend/app/core/chat_db.py`

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'New Chat',
    role TEXT NOT NULL,
    username TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('user', 'bot')),
    text TEXT NOT NULL DEFAULT '',
    think_text TEXT DEFAULT '',
    sources TEXT DEFAULT '[]',
    retrieval_type TEXT DEFAULT '',
    usage TEXT DEFAULT '{}',
    embedding TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX idx_messages_conv ON messages(conversation_id);
CREATE INDEX idx_conversations_user ON conversations(username);
```

### Schema Design Decisions

| Decision | Rationale |
|---|---|
| **UUID v4 for IDs** | Avoids auto-increment collisions in distributed scenarios |
| **ISO 8601 timestamps** | Sortable, human-readable, timezone-aware |
| **`sources` as JSON text** | Flexible schema — no need for a separate sources table |
| **`usage` as JSON text** | Token usage structure varies by LLM provider |
| **`think_text` separate** | Allows collapsible model reasoning display without messy parsing |
| **`summary` column** | Running summary of evicted content for multi-turn context |
| **`embedding` column** | JSON float array — enables vector memory search across conversation history |
| **Auto-migration** | `_migrate()` adds new columns to existing databases on startup |
| **CASCADE delete** | Deleting a conversation automatically removes all its messages |
| **WAL mode** | `PRAGMA journal_mode=WAL` enables concurrent reads during writes |
| **User-scoped** | `username` column ensures users only see their own conversations |

## CRUD API

**File:** `backend/app/api/routes.py`

### Conversations

| Method | Endpoint | Behavior |
|---|---|---|
| `GET` | `/api/v1/conversations` | Lists all conversations for the authenticated user, ordered by `updated_at DESC` |
| `POST` | `/api/v1/conversations` | Creates a new conversation with UUID, returns the created object |
| `GET` | `/api/v1/conversations/{id}` | Gets a conversation with its messages (user-scoped) |
| `PUT` | `/api/v1/conversations/{id}` | Updates conversation title (e.g., when first message is sent) |
| `DELETE` | `/api/v1/conversations/{id}` | Deletes conversation and all messages (cascade) |

### Messages

| Method | Endpoint | Behavior |
|---|---|---|
| `POST` | `/api/v1/conversations/{id}/messages` | Appends a message (user or bot) with metadata |
| `DELETE` | `/api/v1/conversations/{id}/messages/{msgId}` | Removes a single message |

## User Scoping

All operations check `username` from the JWT's `sub` claim:

```python
@router.get("/conversations")
def list_convos(payload: dict = Depends(require_role)):
    username = payload.get("sub", "")
    convos = list_conversations(username)  # Only this user's conversations
    return convos
```

A user can never see or modify another user's conversations.

## Frontend Integration

**File:** `frontend/src/components/ChatInterface.tsx`

### Loading History on Login

When the user logs in, conversations are fetched from the backend:

```typescript
useEffect(() => {
  if (!token) return;
  apiFetch('/conversations', {}, token)
    .then(setConversations)
    .catch(() => setConversations([]));
}, [token]);
```

### Saving Messages

**User message** — saved immediately when sent:

```typescript
const userMsg = { id: crypto.randomUUID(), type: 'user', text: question };
saveMessage(convId, userMsg);

// saveMessage calls:
await apiFetch(`/conversations/${convId}/messages`, {
  method: 'POST',
  body: JSON.stringify({ type: 'user', text: msg.text }),
}, token);
```

**Bot message** — saved after streaming completes:

```typescript
await apiFetch(`/conversations/${convId}/messages`, {
  method: 'POST',
  body: JSON.stringify({
    type: 'bot',
    text: botMsg.text,
    think_text: botMsg.thinkText,
    sources: botMsg.sources,
    retrieval_type: botMsg.retrievalType,
    usage: botMsg.usage,
  }),
}, token);
```

### Title Auto-Naming

When the first user message in a conversation is saved, the message text is used as the conversation title (truncated to 55 chars + `…`):

**Backend:** `ContextManager.save_turn()` detects the first turn and calls `update_conversation_title(conversation_id, question[:60], username)`.

**Frontend:** After a stream completes, the sidebar title is immediately updated in local state from `"New Chat"` to the question text, so users don't need to refresh to see the correct title.

```python
# context_manager.py
def save_turn(self, question: str, answer: str, usage: dict | None = None) -> None:
    ...
    if is_first_turn:
        update_conversation_title(self.conversation_id, question[:60], self.username)
```

## Comparison: Backend SQLite vs localStorage

| Aspect | Backend SQLite | localStorage |
|---|---|---|
| **Persistence** | Survives clear cache, device change | Lost on clear cache |
| **User isolation** | Scoped by JWT username | Shared across browser users |
| **Data volume** | Unlimited (practical limit ~TB) | 5-10 MB per domain |
| **Portability** | Accessible from any device | Single browser instance |
| **Complexity** | More infrastructure | Simple key-value |
| **Backup** | File-level backup | Manual export needed |

For this application, backend persistence was chosen because:
1. Multiple users share the same frontend (Docker deployment)
2. Conversations contain important clinical/financial queries that should persist
3. The frontend might be served from a different domain than the backend (CORS)

## Auto-Cleanup

**File:** `backend/app/core/cleanup.py`

A background task deletes conversations older than a configurable retention period:

```python
async def cleanup_old_conversations():
    while True:
        deleted = delete_old_conversations(settings.conversation_retention_days)
        await asyncio.sleep(settings.cleanup_interval_hours * 3600)
```

| Config | Default | Description |
|---|---|---|
| `CONVERSATION_RETENTION_DAYS` | 30 | Delete conversations not updated in this many days |
| `CLEANUP_INTERVAL_HOURS` | 1 | How often to check for old conversations |

The cleanup cascade-deletes associated messages via SQLite foreign key.

## Data Flow

```
User types question in existing conversation
    │
    ▼
Frontend sends POST /api/v1/chat/stream with {question, conversation_id}
    │
    ▼
Backend orchestrator:
    ├── Loads history + summary + embeddings from chat DB
    ├── Builds context (sliding window + vector memory + summary)
    ├── Runs RAG pipeline
    ├── Streams response to frontend
    └── After stream: saves user + bot messages (with embedding) via ContextManager
    │
    ▼
ContextManager.save_turn():
    ├── Embed user question
    ├── Save user message with embedding
    ├── Save bot message with usage
    ├── Add to in-memory turns list
    └── If first turn, update conversation title
    │
    ▼
condense_if_needed():
    ├── Check total context tokens
    ├── If >80% of budget, evict oldest Q+A pairs
    ├── Summarize evicted content into running summary
    └── Persist updated summary to conversations table
```

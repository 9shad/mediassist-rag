# Streaming — Real-Time Token-by-Token Responses

## Overview

Streaming allows the frontend to display the LLM's response as it's being generated, rather than waiting for the complete response. This provides a better UX (instant feedback) and enables progressive display of structured content (think tags, then answer, then sources).

## Architecture

```
Frontend (Next.js)                     Backend (FastAPI)                     LLM API (Groq/Together)
       │                                     │                                     │
       │  POST /api/v1/chat/stream           │                                     │
       │  (Authorization: Bearer <jwt>)      │                                     │
       │════════════════════════►│                                     │
       │                                     │  POST /chat/completions (stream:true)
       │                                     │════════════════════════════════════►│
       │                                     │                                     │
       │  event: think                        │  ◄──── stream chunks ──────────────┤
       │  data: "Let me think..."            │                                     │
       │  ◄════════════════════════┤                                     │
       │                                     │                                     │
       │  event: answer                       │                                     │
       │  data: "The dosage is..."           │                                     │
       │  ◄════════════════════════┤                                     │
       │                                     │                                     │
       │  event: sources                      │                                     │
       │  data: {"sources": [...],            │                                     │
       │         "retrieval_type": "...",     │                                     │
       │         "usage": {...}}              │                                     │
       │  ◄════════════════════════┤                                     │
```

## Backend Implementation

### SSE (Server-Sent Events) Protocol

The endpoint returns `text/event-stream` content type:

```python
@router.post("/chat/stream")
def chat_stream(req: ChatRequest, payload: dict = Depends(require_role)):
    role = payload["role"]
    return StreamingResponse(
        process_query_stream(req.question, role),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

The `X-Accel-Buffering: no` header tells nginx (in production) not to buffer the stream.

### Stream Generator

**File:** `backend/app/retrieval/orchestrator.py` — `process_query_stream()`

The generator yields SSE-formatted events:

```python
def process_query_stream(question: str, role: str) -> Generator[str, None, None]:
    # ... routing logic (same as non-streaming) ...

    # For SQL RAG (instant, no streaming):
    yield f"event: answer\ndata: {json.dumps(answer)}\n\n"
    yield f"event: sources\ndata: {json.dumps({...})}\n\n"
    return

    # For Hybrid RAG (streaming from LLM):
    for event_type, text in generate_answer_stream(...):
        if event_type == "usage":
            usage = json.loads(text)
            continue
        yield f"event: {event_type}\ndata: {json.dumps(text)}\n\n"

    # Final sources event with usage
    yield f"event: sources\ndata: {json.dumps({'sources': ..., 'usage': usage})}\n\n"
```

### LLM Stream Parser

**File:** `backend/app/core/llm_client.py` — `generate_answer_stream()`

The LLM's streaming endpoint returns chunks as newline-delimited JSON:

```
data: {"choices": [{"delta": {"content": "The"}}]}
data: {"choices": [{"delta": {"content": " dosage"}}]}
data: {"choices": [{"delta": {"content": " is"}}]}
...
data: [DONE]
```

The parser handles `<think>` tags within the stream:

```python
buffer = ""
state = "answer"

for chunk in llm_stream:
    text = chunk["choices"][0]["delta"]["content"]
    buffer += text

    while buffer:
        if state == "answer":
            idx = buffer.find("<think>")
            if idx >= 0:
                before = buffer[:idx]
                if before:
                    yield "answer", before
                state = "think"
                buffer = buffer[idx + 7:]
            else:
                yield "answer", buffer
                buffer = ""
        elif state == "think":
            idx = buffer.find("</think>")
            if idx >= 0:
                before = buffer[:idx]
                if before:
                    yield "think", before
                state = "answer"
                buffer = buffer[idx + 8:]
            else:
                yield "think", buffer
                buffer = ""
```

This produces three event types:
| Event | Content | When Emitted |
|---|---|---|
| `think` | Text inside `<think>` tags | Emitted progressively as content arrives between `<think>` and `</think>` |
| `answer` | Text outside `<think>` tags | Emitted progressively for the main response |
| `usage` | JSON with token counts | Emitted once at the end (from the final LLM chunk that contains usage data) |

**Note:** The `<think>` tag is a feature of Qwen models (and some others) that outputs the model's internal reasoning before the final answer.

## Frontend Implementation

### SSE over POST

The browser's native `EventSource` API only supports GET requests. Since our endpoint requires JWT in the Authorization header (and sending credentials via GET query params is insecure), we use `fetch` with manual SSE parsing:

**File:** `frontend/src/components/ChatInterface.tsx`

```typescript
const res = await fetch(`${API_URL}/api/v1/chat/stream`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  },
  body: JSON.stringify({ question }),
});

const reader = res.body!.getReader();
const decoder = new TextDecoder();
let eventType = '';
let eventData = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const chunk = decoder.decode(value, { stream: true });
  const lines = chunk.split('\n');

  for (const line of lines) {
    if (line.startsWith('event: ')) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith('data: ')) {
      eventData = line.slice(6);
    } else if (line === '') {
      // Empty line = end of event
      if (eventType === 'sources') {
        const data = JSON.parse(eventData);
        // Update sources, retrieval type, usage
      } else if (eventType === 'think') {
        botMsg.thinkText += JSON.parse(eventData);
      } else if (eventType === 'answer') {
        botMsg.text += JSON.parse(eventData);
      }
      setMessages([...prev]);
      eventType = '';
      eventData = '';
    }
  }
}
```

### Event Parsing Loop

The parser reads bytes from the `ReadableStream`, decodes them into text, and splits on newlines:

1. `event: think` — accumulated into `botMsg.thinkText`
2. `event: answer` — accumulated into `botMsg.text`
3. `event: sources` — parsed as JSON, sets `botMsg.sources`, `botMsg.retrievalType`, `botMsg.usage`

The component re-renders on every message chunk by updating the messages state, providing real-time token display.

## Benefits

| Aspect | Without Streaming | With Streaming |
|---|---|---|
| Time to first character | 3-15 seconds | <1 second |
| User perception | "Is it stuck?" | "It's working!" |
| Think content | Hidden entirely | Shown as collapsible |
| Token usage | Not available | Displayed per-response |

## Edge Cases

1. **Connection drop:** The stream has no built-in resume; user would re-submit
2. **No think tags:** If the LLM doesn't emit `<think>`, all content is `answer` events
3. **Empty response:** Guarded by the fallback answer mechanism
4. **Usage not emitted:** Not all providers include usage in the final chunk; frontend handles missing usage gracefully

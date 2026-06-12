from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_role_collections, require_role
from app.core.chat_db import (
    add_message,
    create_conversation,
    delete_conversation,
    delete_message,
    get_conversation,
    get_messages,
    list_conversations,
    update_conversation_title,
)
from app.core.enums import RetrievalType
from app.core.security import authenticate_user, create_access_token
from app.models.auth import LoginRequest, LoginResponse
from app.models.chat import ChatRequest, ChatResponse, Source
from app.retrieval.orchestrator import process_query, process_query_stream
from fastapi.responses import StreamingResponse

router = APIRouter()


# ─── Auth ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    role = user["role"]
    collections = get_role_collections(role.value)
    token = create_access_token(role, req.username)
    return LoginResponse(
        access_token=token,
        role=role.value,
        username=req.username,
        name=user["name"],
        collections=collections,
    )


# ─── Chat ────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, payload: dict = Depends(require_role)):
    role = payload["role"]
    username = payload.get("sub", "")
    return process_query(req.question, role, conversation_id=req.conversation_id, username=username)


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, payload: dict = Depends(require_role)):
    role = payload["role"]
    username = payload.get("sub", "")
    return StreamingResponse(
        process_query_stream(req.question, role, conversation_id=req.conversation_id, username=username),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ─── Conversations ──────────────────────────────────────────────────────────

@router.get("/conversations")
def list_convos(payload: dict = Depends(require_role)):
    username = payload.get("sub", "")
    convos = list_conversations(username)
    return convos


@router.post("/conversations")
def create_convos(payload: dict = Depends(require_role)):
    username = payload.get("sub", "")
    role = payload.get("role", "")
    import uuid
    cid = str(uuid.uuid4())
    conv = create_conversation(cid, "New Chat", role, username)
    return conv


@router.get("/conversations/{conversation_id}")
def get_convos(conversation_id: str, payload: dict = Depends(require_role)):
    username = payload.get("sub", "")
    conv = get_conversation(conversation_id, username)
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(404, "Conversation not found")
    messages = get_messages(conversation_id)
    conv["messages"] = messages
    return conv


@router.put("/conversations/{conversation_id}")
def update_convos(conversation_id: str, body: dict, payload: dict = Depends(require_role)):
    username = payload.get("sub", "")
    title = body.get("title", "")
    if not title:
        from fastapi import HTTPException
        raise HTTPException(400, "title is required")
    conv = update_conversation_title(conversation_id, title, username)
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(404, "Conversation not found")
    return conv


@router.delete("/conversations/{conversation_id}")
def delete_convos(conversation_id: str, payload: dict = Depends(require_role)):
    username = payload.get("sub", "")
    deleted = delete_conversation(conversation_id, username)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}


# ─── Messages ──────────────────────────────────────────────────────────────

@router.post("/conversations/{conversation_id}/messages")
def add_msg(conversation_id: str, body: dict, payload: dict = Depends(require_role)):
    username = payload.get("sub", "")
    conv = get_conversation(conversation_id, username)
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(404, "Conversation not found")
    import uuid
    msg = add_message(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        type=body.get("type", ""),
        text=body.get("text", ""),
        think_text=body.get("think_text", ""),
        sources=body.get("sources"),
        retrieval_type=body.get("retrieval_type", ""),
        usage=body.get("usage"),
    )
    if body.get("type") == "user":
        update_conversation_title(conversation_id, body.get("text", "")[:60], username)
    return msg


@router.delete("/conversations/{conversation_id}/messages/{message_id}")
def delete_msg(conversation_id: str, message_id: str, payload: dict = Depends(require_role)):
    deleted = delete_message(conversation_id, message_id)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(404, "Message not found")
    return {"ok": True}


# ─── Collections / Health ──────────────────────────────────────────────────

@router.get("/collections/{role}")
def get_collections(role: str):
    collections = get_role_collections(role)
    return {"role": role, "collections": collections}


@router.get("/health")
def health():
    from app.core.config import settings
    from qdrant_client import QdrantClient
    qdrant_ok = False
    try:
        client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port, timeout=2, check_compatibility=False)
        client.get_collections()
        qdrant_ok = True
    except Exception:
        pass
    db_ok = False
    try:
        import sqlite3
        conn = sqlite3.connect(settings.database_path)
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
    except Exception:
        pass
    return {"status": "ok", "qdrant_connected": qdrant_ok, "db_connected": db_ok}

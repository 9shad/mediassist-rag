import json
import re
from typing import Generator

from loguru import logger

from app.core.context_manager import ContextManager
from app.core.enums import RetrievalType, Role, SQL_RAG_ROLES
from app.core.llm_client import generate_answer, generate_answer_stream
from app.models.chat import ChatResponse, Source
from app.retrieval.hybrid_retriever import hybrid_retrieve
from app.retrieval.reranker import rerank
from app.retrieval.sql_rag import sql_rag_chain


ANALYTICAL_PATTERNS = re.compile(
    r"(how many|count|total|average|sum|what.*percentage|statistics|"
    r"most|least|top.*bottom|compare|month|quarter|year|trend|"
    r"claims|maintenance|ticket|escalat|approv|denied|pending)",
    re.IGNORECASE,
)


def _is_analytical(query: str) -> bool:
    return bool(ANALYTICAL_PATTERNS.search(query))


def _load_context(conversation_id: str) -> tuple[ContextManager, str]:
    ctx = ContextManager(conversation_id)
    ctx.load()
    return ctx, ""


def process_query(
    question: str,
    role: str,
    conversation_id: str = "",
    username: str = "",
) -> ChatResponse:
    ctx = None
    history_context = ""
    if conversation_id:
        ctx = ContextManager(conversation_id, username=username)
        ctx.load()
        assembled = ctx.build_context(question)
        history_context = assembled["history_context"]

    is_analytical = _is_analytical(question)
    try:
        role_enum = Role(role)
    except ValueError:
        role_enum = None

    if is_analytical and role_enum in SQL_RAG_ROLES:
        logger.info(f"Routing to SQL RAG: role={role}, question='{question[:60]}...'")
        answer = sql_rag_chain(question)
        if ctx:
            ctx.save_turn(question, answer)
            ctx.condense_if_needed()
        return ChatResponse(
            answer=answer,
            sources=[Source(source_document="mediassist.db", section_title="SQL Query Result", collection="database")],
            retrieval_type=RetrievalType.SQL_RAG.value,
            role=role,
        )

    logger.info(f"Routing to Hybrid RAG: role={role}, question='{question[:60]}...'")
    candidates = hybrid_retrieve(question, role, top_k=10)

    if not candidates:
        msg = (
            f"As a {role}, you don't have access to documents that can answer this question. "
            f"I can only answer questions from your permitted collections."
        )
        if ctx:
            ctx.save_turn(question, msg)
            ctx.condense_if_needed()
        return ChatResponse(
            answer=msg,
            sources=[],
            retrieval_type=RetrievalType.HYBRID_RAG.value,
            role=role,
        )

    reranked = rerank(question, candidates, top_n=3)

    context_parts = []
    sources = []
    for c in reranked:
        context_parts.append(f"[Source: {c['source_document']}, Section: {c['section_title']}]\n{c['text']}")
        sources.append(Source(
            source_document=c["source_document"],
            section_title=c["section_title"],
            collection=c["collection"],
        ))

    context = "\n\n".join(context_parts)
    answer = generate_answer(question=question, context=context, history_context=history_context, max_tokens=1024)

    if ctx:
        ctx.save_turn(question, answer)
        ctx.condense_if_needed()

    return ChatResponse(
        answer=answer,
        sources=sources,
        retrieval_type=RetrievalType.HYBRID_RAG.value,
        role=role,
    )


def process_query_stream(
    question: str,
    role: str,
    conversation_id: str = "",
    username: str = "",
) -> Generator[str, None, None]:
    ctx = None
    history_context = ""
    if conversation_id:
        ctx = ContextManager(conversation_id, username=username)
        ctx.load()
        assembled = ctx.build_context(question)
        history_context = assembled["history_context"]

    is_analytical = _is_analytical(question)
    try:
        role_enum = Role(role)
    except ValueError:
        role_enum = None

    if is_analytical and role_enum in SQL_RAG_ROLES:
        logger.info(f"Routing to SQL RAG: role={role}, question='{question[:60]}...'")
        answer = sql_rag_chain(question)
        if ctx:
            ctx.save_turn(question, answer)
            ctx.condense_if_needed()
        yield f"event: answer\ndata: {json.dumps(answer)}\n\n"
        yield f"event: sources\ndata: {json.dumps({'sources': [{'source_document': 'mediassist.db', 'section_title': 'SQL Query Result', 'collection': 'database'}], 'retrieval_type': RetrievalType.SQL_RAG.value, 'role': role})}\n\n"
        return

    logger.info(f"Routing to Hybrid RAG: role={role}, question='{question[:60]}...'")
    candidates = hybrid_retrieve(question, role, top_k=10)

    if not candidates:
        msg = f"As a {role}, you don't have access to documents that can answer this question. I can only answer questions from your permitted collections."
        if ctx:
            ctx.save_turn(question, msg)
            ctx.condense_if_needed()
        yield f"event: answer\ndata: {json.dumps(msg)}\n\n"
        yield f"event: sources\ndata: {json.dumps({'sources': [], 'retrieval_type': RetrievalType.HYBRID_RAG.value, 'role': role})}\n\n"
        return

    reranked = rerank(question, candidates, top_n=3)

    context_parts = []
    sources = []
    for c in reranked:
        context_parts.append(f"[Source: {c['source_document']}, Section: {c['section_title']}]\n{c['text']}")
        sources.append(Source(
            source_document=c["source_document"],
            section_title=c["section_title"],
            collection=c["collection"],
        ))

    context = "\n\n".join(context_parts)

    usage = None
    full_answer = ""
    for event_type, text in generate_answer_stream(question=question, context=context, history_context=history_context, max_tokens=1024):
        if event_type == "usage":
            usage = json.loads(text)
            continue
        if event_type == "answer":
            full_answer += text
        yield f"event: {event_type}\ndata: {json.dumps(text)}\n\n"

    if ctx:
        ctx.save_turn(question, full_answer, usage)
        ctx.condense_if_needed()

    yield f"event: sources\ndata: {json.dumps({'sources': [s.model_dump() for s in sources], 'retrieval_type': RetrievalType.HYBRID_RAG.value, 'role': role, 'usage': usage})}\n\n"

import json
import re
from typing import Generator

import httpx
from loguru import logger

from app.core.config import settings


SYSTEM_PROMPT = """You are MediBot, an AI assistant for MediAssist Health Network.
Answer the user's question based ONLY on the provided context.
If the context doesn't contain enough information, say so.
Cite sources using [Source: document_name, Section: section_title].
Be concise, accurate, and clinical where appropriate."""





SUMMARIZE_PROMPT = """You are a conversation summarizer. Given a conversation summary (if any) and a set of new Q&A exchanges, produce an updated concise summary covering all key information. Keep it under 300 tokens. Focus on: medical facts mentioned, user preferences, data points, decisions made. Omit pleasantries."""


def summarize_turns(new_turns: str, existing_summary: str = "") -> str:
    if not settings.llm_api_key:
        lines = new_turns.split("\n")
        summary = " | ".join(lines[:6])
        return summary[:500]
    prompt = f"Existing summary: {existing_summary}\n\nNew exchanges to incorporate:\n{new_turns}"
    return generate_answer(
        question=prompt,
        system_prompt=SUMMARIZE_PROMPT,
        max_tokens=settings.summary_max_tokens,
    )


def build_conversation_messages(
    system_prompt: str,
    question: str,
    context: str = "",
    history_context: str = "",
) -> list[dict]:
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


def generate_answer(
    question: str,
    context: str = "",
    system_prompt: str = SYSTEM_PROMPT,
    max_tokens: int = 1024,
    history_context: str = "",
) -> str:
    if not settings.llm_api_key:
        return _fallback_answer(question, context)

    messages = build_conversation_messages(system_prompt, question, context, history_context)

    try:
        response = httpx.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        return content
    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        return _fallback_answer(question, context)


def generate_answer_stream(
    question: str,
    context: str = "",
    system_prompt: str = SYSTEM_PROMPT,
    max_tokens: int = 1024,
    history_context: str = "",
) -> Generator[tuple[str, str], None, None]:
    """Yields (type, text) tuples.

    type is one of: "think", "answer", or "usage".
    """
    if not settings.llm_api_key:
        yield "answer", _fallback_answer(question, context)
        return

    messages = build_conversation_messages(system_prompt, question, context, history_context)
    usage = None

    try:
        with httpx.stream(
            "POST",
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.1,
                "stream": True,
            },
            timeout=120,
        ) as response:
            response.raise_for_status()
            buffer = ""
            state = "answer"

            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                if "usage" in chunk:
                    usage = chunk["usage"]
                    continue

                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                text = delta.get("content", "")
                if not text:
                    continue

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

            if buffer:
                yield state, buffer

            if usage:
                yield "usage", json.dumps(usage)
    except Exception as e:
        logger.error(f"LLM streaming call failed: {e}")
        yield "answer", _fallback_answer(question, context)


def _fallback_answer(question: str, context: str = "") -> str:
    if context:
        context_preview = context[:300]
        return (
            f"Based on the retrieved documents, here is what I found:\n\n"
            f"{context_preview}\n\n"
            f"(Note: LLM API key not configured — showing raw context instead of AI-generated answer.)"
        )
    return f"MediBot received your question: '{question}'. Please configure LLM_API_KEY for AI-powered answers."

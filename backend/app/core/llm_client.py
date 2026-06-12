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


FOLLOWUP_PROMPT = """Output 3 numbered follow-up questions. No thinking. No tags. Just:

1. first question
2. second question
3. third question"""


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _parse_followups(text: str) -> list[str] | None:
    text = _strip_think(text.strip())
    lines = [l.strip() for l in text.replace("\r", "").split("\n") if l.strip()]
    seen = []
    for line in lines:
        clean = re.sub(r"^\d+[.)]\s*", "", line).strip()
        clean = re.sub(r"^[-*]\s+", "", clean).strip()
        clean = clean.strip('"\'').strip()
        if clean and len(clean) > 5 and clean not in seen:
            seen.append(clean)
        if len(seen) >= 3:
            return seen
    if seen:
        return seen
    return None


def generate_followups(question: str, answer: str, context: str = "") -> list[str]:
    if not settings.llm_api_key:
        return []
    prompt = question
    for attempt in range(2):
        try:
            response = httpx.post(
                f"{settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "messages": [
                        {"role": "system", "content": FOLLOWUP_PROMPT},
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": "1. What"},
                    ],
                    "max_tokens": 120,
                    "temperature": 0.7,
                    "stop": ["\n\n\n", "4."],
                },
                timeout=15,
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            if not text or not text.strip():
                logger.debug(f"Followup attempt {attempt+1}: empty response")
                continue
            text = "1. What" + text
            parsed = _parse_followups(text)
            if parsed:
                return parsed
        except Exception as e:
            logger.debug(f"Followup attempt {attempt+1} failed: {e}")
    return _fallback_followups(question)

_fallback_qs: dict[str, list[str]] = {
    "doctor": [
        "What are the contraindications?",
        "What is the recommended dosage?",
        "How long does treatment typically last?",
    ],
    "nurse": [
        "What are the key warning signs to watch for?",
        "How often should vital signs be checked?",
        "What equipment is needed for this procedure?",
    ],
    "billing_executive": [
        "What are the billing code requirements?",
        "How are claims typically processed?",
        "What documentation is needed for approval?",
    ],
    "technician": [
        "What is the recommended maintenance schedule?",
        "What are common error codes?",
        "What safety precautions should be followed?",
    ],
    "admin": [
        "What are the key metrics to track?",
        "Which departments need attention?",
        "What reports are available for review?",
    ],
}

def _fallback_followups(question: str) -> list[str]:
    where_keywords = {"doctor": "doctor", "nurse": "nurse", "billing": "billing_executive",
                      "technician": "technician", "admin": "admin"}
    for kw, role in where_keywords.items():
        if kw in question.lower():
            return _fallback_qs[role]
    return _fallback_qs["nurse"]


def _fallback_answer(question: str, context: str = "") -> str:
    if context:
        context_preview = context[:300]
        return (
            f"Based on the retrieved documents, here is what I found:\n\n"
            f"{context_preview}\n\n"
            f"(Note: LLM API key not configured — showing raw context instead of AI-generated answer.)"
        )
    return f"MediBot received your question: '{question}'. Please configure LLM_API_KEY for AI-powered answers."

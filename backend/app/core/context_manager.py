import json
import re
from typing import Any

import numpy as np
from loguru import logger

from app.core.chat_db import (
    add_message,
    get_conversation_by_id,
    get_messages,
    update_conversation_title,
    update_summary,
)
from app.core.config import settings
from app.core.llm_client import generate_answer, summarize_turns
from app.ingestion.chunker import count_tokens
from app.ingestion.embedder import embed_query


TURN_SEPARATOR_TOKEN_OVERHEAD = 40  # Approximate tokens for role labels and formatting


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-10))


class ContextManager:
    """Manages multi-turn conversation context with three layers:

    1. Sliding window — last N turns verbatim for immediate referential context
    2. Vector memory — semantically similar past exchanges retrieved via embedding
    3. Running summary — compressed representation of evicted content
    """

    def __init__(self, conversation_id: str, username: str = ""):
        self.conversation_id = conversation_id
        self.username = username
        self.summary = ""
        self.turns: list[dict[str, Any]] = []

    def load(self) -> None:
        conv = get_conversation_by_id(self.conversation_id)
        if conv:
            self.summary = conv.get("summary", "") or ""
        messages = get_messages(self.conversation_id)
        self.turns = []
        for m in messages:
            emb = m.get("embedding", "") or ""
            self.turns.append({
                "id": m["id"],
                "type": m["type"],
                "text": m["text"],
                "embedding": json.loads(emb) if emb else None,
                "created_at": m["created_at"],
            })

    def build_context(self, question: str) -> dict[str, Any]:
        """Assemble all three context layers within token budget.

        Returns:
            history_context: assembled text block for the LLM prompt
            needs_summarize: True if the sliding window was trimmed (caller should summarize)
        """
        sliding = self._sliding_window()
        vector_mem = self._vector_search(question, sliding)
        assembled = self._assemble(question, sliding, vector_mem)
        return assembled

    def save_turn(self, question: str, answer: str, usage: dict | None = None) -> None:
        from datetime import datetime, timezone
        q_emb = embed_query(question)
        is_first = len(self.turns) == 0
        turn_idx = len(self.turns) // 2
        user_id = f"{self.conversation_id}-q-{turn_idx}"
        bot_id = f"{self.conversation_id}-a-{turn_idx}"
        add_message(
            id=user_id, conversation_id=self.conversation_id,
            type="user", text=question,
            embedding=json.dumps(q_emb),
        )
        add_message(
            id=bot_id, conversation_id=self.conversation_id,
            type="bot", text=answer, usage=usage,
        )
        now = datetime.now(timezone.utc).isoformat()
        self.turns.append({
            "id": user_id, "type": "user", "text": question,
            "embedding": q_emb, "created_at": now,
        })
        self.turns.append({
            "id": bot_id, "type": "bot", "text": answer,
            "embedding": None, "created_at": now,
        })
        if is_first and self.username:
            update_conversation_title(self.conversation_id, question[:60], self.username)

    def condense_if_needed(self) -> None:
        """If total context exceeds 80% of budget, summarize oldest turns."""
        total = self._estimate_context_tokens("")
        budget = settings.context_max_tokens
        if total < budget * 0.8:
            return
        evict = []
        kept = list(self.turns)
        for i in range(0, len(kept) - 1, 2):
            if i + 1 >= len(kept):
                break
            pair_tokens = (
                count_tokens(kept[i]["text"])
                + count_tokens(kept[i + 1]["text"])
                + TURN_SEPARATOR_TOKEN_OVERHEAD
            )
            evict.append(kept[i])
            evict.append(kept[i + 1])
            kept = kept[i + 2:]
            total -= pair_tokens
            if total < budget * 0.7:
                break
        if not evict:
            return
        summary_text = self._make_summary(evict)
        self.summary = summary_text
        update_summary(self.conversation_id, self.summary)
        self.turns = kept
        logger.info(f"Condensed {len(evict)//2} turn(s), summary now {count_tokens(self.summary)} tokens")

    # ── Private helpers ──────────────────────────────────────────────────

    def _sliding_window(self) -> list[dict[str, Any]]:
        max_turns = settings.sliding_window_turns * 2  # *2 because each turn has user+bot
        return self.turns[-max_turns:] if len(self.turns) > max_turns else list(self.turns)

    def _vector_search(self, question: str, sliding: list[dict]) -> list[dict[str, Any]]:
        if len(self.turns) < 4:
            return []
        q_emb = embed_query(question)
        scored = []
        sliding_ids = {t["id"] for t in sliding}
        for t in self.turns:
            if t["id"] in sliding_ids or not t["embedding"] or t["type"] != "user":
                continue
            sim = cosine_similarity(q_emb, t["embedding"])
            if sim < 0.3:
                continue
            scored.append((sim, t))
        scored.sort(key=lambda x: x[0], reverse=True)
        top_k = settings.vector_memory_top_k
        result = []
        for _, t in scored[:top_k]:
            idx = self.turns.index(t)
            if idx + 1 < len(self.turns) and self.turns[idx + 1]["type"] == "bot":
                result.append({
                    "question": t["text"],
                    "answer": self.turns[idx + 1]["text"],
                    "similarity": round(_, 3),
                })
        return result

    def _assemble(self, question: str, sliding: list[dict], vector_mem: list[dict]) -> dict[str, Any]:
        parts = []
        budget = settings.context_max_tokens
        budget -= count_tokens(question)
        budget -= 100  # System prompt overhead
        budget -= 500  # Reserve for answer output

        # 1. Summary (always included, minimal cost)
        if self.summary:
            summary_tokens = count_tokens(self.summary)
            if summary_tokens < budget:
                parts.append(f"[Earlier Conversation Summary]\n{self.summary}")
                budget -= summary_tokens

        # 2. Vector memory (most relevant past exchanges)
        vm_texts = []
        for mem in vector_mem:
            block = f"[Past: Q] {mem['question']}\n[Past: A] {mem['answer']}"
            t = count_tokens(block) + TURN_SEPARATOR_TOKEN_OVERHEAD
            if t < budget:
                vm_texts.append(block)
                budget -= t
        if vm_texts:
            parts.append("[Relevant Past Exchanges]\n" + "\n\n".join(vm_texts))

        # 3. Sliding window (immediate context)
        sw_lines = []
        for t in sliding:
            label = "User" if t["type"] == "user" else "You"
            block = f"[{label}] {t['text']}"
            t_tokens = count_tokens(block) + TURN_SEPARATOR_TOKEN_OVERHEAD
            if t_tokens < budget:
                sw_lines.append(block)
                budget -= t_tokens
            else:
                break
        if sw_lines:
            parts.append("[Recent Conversation]\n" + "\n".join(sw_lines))

        history_context = "\n\n---\n\n".join(parts)
        return {"history_context": history_context}

    def _estimate_context_tokens(self, question: str) -> int:
        total = count_tokens(question) + 100 + 500
        if self.summary:
            total += count_tokens(self.summary)
        for t in self.turns:
            total += count_tokens(t["text"]) + TURN_SEPARATOR_TOKEN_OVERHEAD
        return total

    def _make_summary(self, evicted_turns: list[dict]) -> str:
        pairs = []
        for i in range(0, len(evicted_turns) - 1, 2):
            q = evicted_turns[i]["text"]
            a = evicted_turns[i + 1]["text"] if i + 1 < len(evicted_turns) else ""
            pairs.append(f"Q: {q}\nA: {a[:500]}")
        text = "\n\n".join(pairs)
        if not text.strip():
            return self.summary
        try:
            result = summarize_turns(text, existing_summary=self.summary)
            return result[:settings.summary_max_tokens]
        except Exception as e:
            logger.warning(f"Summarization failed: {e}")
            return self.summary

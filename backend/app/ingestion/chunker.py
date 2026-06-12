import tiktoken

TOKENIZER = tiktoken.get_encoding("cl100k_base")
MAX_TOKENS = 512


def count_tokens(text: str) -> int:
    return len(TOKENIZER.encode(text))


def hierarchical_chunk(chunks: list[dict]) -> list[dict]:
    result = []
    for chunk in chunks:
        text = chunk["text"]
        section = chunk["section_title"]
        chunk_type = chunk["chunk_type"]

        contextual_text = f"[Section: {section}] {text}" if section else text
        tokens = count_tokens(contextual_text)

        if tokens <= MAX_TOKENS:
            chunk["text"] = contextual_text
            result.append(chunk)
        else:
            words = text.split()
            sub_chunks = []
            current = []
            current_tokens = 0

            prefix = f"[Section: {section}] " if section else ""
            prefix_tokens = count_tokens(prefix)

            for word in words:
                word_tokens = count_tokens(word) + 1
                if current_tokens + word_tokens + prefix_tokens > MAX_TOKENS and current:
                    sub_chunks.append(prefix + " ".join(current))
                    current = [word]
                    current_tokens = count_tokens(word)
                else:
                    current.append(word)
                    current_tokens += word_tokens

            if current:
                sub_chunks.append(prefix + " ".join(current))

            for sub in sub_chunks:
                result.append({
                    "text": sub,
                    "section_title": section,
                    "chunk_type": chunk_type,
                })

    return result

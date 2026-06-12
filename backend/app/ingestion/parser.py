import re
from pathlib import Path

import fitz

from app.core.enums import COLLECTION_ROLES, ChunkType


def get_collection_from_path(filepath: str) -> str:
    parts = Path(filepath).parts
    for candidate in reversed(parts):
        if candidate in COLLECTION_ROLES:
            return candidate
    return "general"


def get_access_roles(collection: str) -> list[str]:
    return [r.value for r in COLLECTION_ROLES.get(collection, COLLECTION_ROLES["general"])]


def parse_pdf(filepath: str) -> list[dict]:
    doc = fitz.open(filepath)
    chunks = []
    section_stack = []

    heading_patterns = [
        re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE),
        re.compile(r"^([A-Z][A-Z\s\-]+):?$", re.MULTILINE),
    ]

    for page_num, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block["type"] == 0:
                text = ""
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text += span.get("text", "") + " "
                text = text.strip()
                if not text:
                    continue

                font_size = 0
                if block.get("lines"):
                    span = block["lines"][0].get("spans", [None])[0]
                    if span:
                        font_size = span.get("size", 0)

                is_heading = False
                for pattern in heading_patterns:
                    match = pattern.match(text)
                    if match:
                        is_heading = True
                        break
                if font_size > 16:
                    is_heading = True

                if is_heading:
                    level = 1 if font_size > 20 else 2 if font_size > 14 else 3
                    clean_text = re.sub(r"^#+\s*", "", text).strip()
                    if len(section_stack) >= level:
                        section_stack = section_stack[:level - 1]
                        section_stack.append(clean_text)
                    else:
                        section_stack.append(clean_text)

                    chunks.append({
                        "text": clean_text,
                        "section_title": " > ".join(section_stack[:-1]) if len(section_stack) > 1 else "",
                        "chunk_type": ChunkType.HEADING.value,
                    })
                else:
                    chunks.append({
                        "text": text,
                        "section_title": " > ".join(section_stack) if section_stack else "",
                        "chunk_type": ChunkType.TEXT.value,
                    })

            elif block["type"] == 1:
                text = block.get("text", "").strip()
                if text:
                    chunks.append({
                        "text": text,
                        "section_title": " > ".join(section_stack) if section_stack else "",
                        "chunk_type": ChunkType.TABLE.value,
                    })

    doc.close()
    return chunks


def parse_markdown(filepath: str) -> list[dict]:
    with open(filepath, "r") as f:
        content = f.read()

    chunks = []
    section_stack = []
    lines = content.split("\n")

    for line in lines:
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            if len(section_stack) >= level:
                section_stack = section_stack[:level - 1]
            section_stack.append(heading_text)
            chunks.append({
                "text": heading_text,
                "section_title": " > ".join(section_stack[:-1]) if len(section_stack) > 1 else "",
                "chunk_type": ChunkType.HEADING.value,
            })
        elif line.strip():
            chunks.append({
                "text": line.strip(),
                "section_title": " > ".join(section_stack) if section_stack else "",
                "chunk_type": ChunkType.TEXT.value,
            })

    return chunks


def parse_document(filepath: str) -> list[dict]:
    ext = Path(filepath).suffix.lower()
    if ext in (".pdf",):
        return parse_pdf(filepath)
    elif ext in (".md", ".markdown"):
        return parse_markdown(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    conversation_id: str = ""


class Source(BaseModel):
    source_document: str
    section_title: str
    collection: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source] = []
    retrieval_type: str
    role: str

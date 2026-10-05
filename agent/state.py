from typing import TypedDict


class Citation(TypedDict):
    paper_id: int
    chunk_id: int
    quoted_text: str


class RetrievedChunk(TypedDict):
    paper_id: int
    chunk_id: int
    paper_title: str
    arxiv_id: str
    text: str
    score: float


class Turn(TypedDict):
    role: str  # "user" | "assistant"
    content: str


class QueryState(TypedDict):
    workspace_id: int
    question: str
    history: list[Turn]
    search_query: str
    retrieved_chunks: list[RetrievedChunk]
    draft_answer: str | None
    citations: list[Citation]
    critique_notes: list[str]
    retries: int
    max_retries: int
    finished: bool
    timings: dict[str, float]
    tokens_used: int

from typing import TypedDict


class Citation(TypedDict):
    paper_id: int
    chunk_id: int
    quoted_text: str


class RetrievedChunk(TypedDict):
    paper_id: int
    chunk_id: int
    paper_title: str
    text: str
    score: float


class QueryState(TypedDict):
    workspace_id: int
    question: str
    retrieved_chunks: list[RetrievedChunk]
    draft_answer: str | None
    citations: list[Citation]
    critique_notes: list[str]
    retries: int
    max_retries: int
    finished: bool

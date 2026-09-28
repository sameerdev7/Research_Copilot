"""The self-correcting RAG loop: retrieve -> synthesize -> critique -> (retry synthesize | done).

This is the one real LangGraph cycle in the project: critique_node can route back to
synthesize_node with concrete unsupported-claim notes, up to max_retries times.
"""

from __future__ import annotations

import re

from django.conf import settings
from langgraph.graph import END, StateGraph
from pgvector.django import CosineDistance

from .embeddings import embed_text
from .llm.base import LLMClient
from .llm.factory import get_default_client
from .prompts import build_critique_messages, build_synthesize_messages
from .state import Citation, QueryState, RetrievedChunk

CITATION_LINE_RE = re.compile(r"^(.*?)\s*\[(\d+)\]\s*$")
UNSUPPORTED_RE = re.compile(r"UNSUPPORTED:\s*(.*)", re.IGNORECASE)


def retrieve_node(state: QueryState) -> dict:
    from papers.models import Chunk  # avoid a hard Django-apps-not-ready import at module load

    question_vector = embed_text(state["question"])
    rows = (
        Chunk.objects.filter(paper__workspace_id=state["workspace_id"], paper__status="ready")
        .select_related("paper")
        .annotate(distance=CosineDistance("embedding", question_vector))
        .order_by("distance")[: settings.RAG_RETRIEVAL_K]
    )
    retrieved: list[RetrievedChunk] = [
        {
            "paper_id": c.paper_id,
            "chunk_id": c.id,
            "paper_title": c.paper.title,
            "text": c.text,
            "score": 1 - c.distance,
        }
        for c in rows
    ]
    return {"retrieved_chunks": retrieved}


def _parse_draft(raw: str, retrieved_chunks: list[RetrievedChunk]) -> tuple[str, list[Citation]]:
    citations: list[Citation] = []
    for line in raw.strip().splitlines():
        match = CITATION_LINE_RE.match(line.strip())
        if not match:
            continue
        sentence, chunk_num = match.group(1), int(match.group(2))
        if 1 <= chunk_num <= len(retrieved_chunks):
            chunk = retrieved_chunks[chunk_num - 1]
            citations.append(
                {"paper_id": chunk["paper_id"], "chunk_id": chunk["chunk_id"], "quoted_text": sentence}
            )
    return raw.strip(), citations


def synthesize_node(state: QueryState, llm: LLMClient | None = None) -> dict:
    llm = llm or get_default_client()
    critique_notes = state.get("critique_notes") if state.get("retries", 0) > 0 else None
    messages = build_synthesize_messages(state["question"], state["retrieved_chunks"], critique_notes)
    raw = llm.complete(messages)
    draft_answer, citations = _parse_draft(raw, state["retrieved_chunks"])
    return {"draft_answer": draft_answer, "citations": citations}


def _parse_unsupported_line_numbers(raw: str) -> list[int]:
    match = UNSUPPORTED_RE.search(raw)
    if not match:
        return []
    body = match.group(1).strip()
    if not body or body.lower() == "none":
        return []
    return [int(tok) for tok in re.findall(r"\d+", body)]


def critique_node(state: QueryState, llm: LLMClient | None = None) -> dict:
    llm = llm or get_default_client()
    retrieved_chunks = state["retrieved_chunks"]
    draft_answer = state["draft_answer"] or ""
    lines = draft_answer.strip().splitlines()

    notes: list[str] = []
    checkable: dict[int, str] = {}
    for i, line in enumerate(lines, start=1):
        match = CITATION_LINE_RE.match(line.strip())
        if not match:
            notes.append(f'Line {i} has no citation tag: "{line.strip()}"')
            continue
        sentence, chunk_num = match.group(1), int(match.group(2))
        if not (1 <= chunk_num <= len(retrieved_chunks)):
            notes.append(f'Line {i} cites chunk [{chunk_num}], which was not retrieved: "{sentence}"')
            continue
        checkable[i] = sentence

    if checkable:
        messages = build_critique_messages(retrieved_chunks, draft_answer)
        raw = llm.complete(messages)
        for line_number in _parse_unsupported_line_numbers(raw):
            sentence = checkable.get(line_number)
            if sentence:
                notes.append(f'Line {line_number} is not supported by its cited chunk: "{sentence}"')

    retries = state.get("retries", 0)
    max_retries = state.get("max_retries", settings.RAG_MAX_RETRIES)
    if notes and retries < max_retries:
        return {"critique_notes": notes, "finished": False, "retries": retries + 1}
    return {"critique_notes": notes, "finished": True, "retries": retries}


def _route_after_critique(state: QueryState) -> str:
    return "synthesize" if not state["finished"] else END


def build_query_graph(llm: LLMClient | None = None):
    graph = StateGraph(QueryState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("synthesize", lambda s: synthesize_node(s, llm=llm))
    graph.add_node("critique", lambda s: critique_node(s, llm=llm))

    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "synthesize")
    graph.add_edge("synthesize", "critique")
    graph.add_conditional_edges("critique", _route_after_critique, {"synthesize": "synthesize", END: END})

    return graph.compile()


def run_query(workspace_id: int, question: str, llm: LLMClient | None = None) -> QueryState:
    graph = build_query_graph(llm=llm)
    initial_state: QueryState = {
        "workspace_id": workspace_id,
        "question": question,
        "retrieved_chunks": [],
        "draft_answer": None,
        "citations": [],
        "critique_notes": [],
        "retries": 0,
        "max_retries": settings.RAG_MAX_RETRIES,
        "finished": False,
    }
    return graph.invoke(initial_state)

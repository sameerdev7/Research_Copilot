from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator

from django.conf import settings
from langgraph.graph import END, StateGraph

from .llm.base import LLMClient
from .llm.counting_client import CountingClient
from .llm.factory import get_default_client
from .prompts import build_critique_messages, build_rewrite_messages, build_synthesize_messages
from .retrieval import hybrid_search
from .state import Citation, QueryState, RetrievedChunk, Turn

logger = logging.getLogger(__name__)

NO_RESULTS_ANSWER = "I couldn't find anything relevant to that in this workspace's papers."
MAX_SEARCH_QUERY_CHARS = 500

# a line's trailing citation tags, e.g. "text. [3][4]"
CITATION_LINE_RE = re.compile(r"^(.*?)\s*((?:\[\d+\]\s*)+)$")
UNSUPPORTED_RE = re.compile(r"UNSUPPORTED:\s*(.*)", re.IGNORECASE)


def _match_citation_line(line: str) -> tuple[str, list[int]] | None:
    match = CITATION_LINE_RE.match(line.strip())
    if not match:
        return None
    sentence, tags_blob = match.group(1), match.group(2)
    return sentence, [int(n) for n in re.findall(r"\d+", tags_blob)]


# turns a follow-up question into a standalone search query
def rewrite_node(state: QueryState, llm: LLMClient | None = None) -> dict:
    history = state.get("history") or []
    question = state["question"]
    if not history:
        return {"search_query": question}

    llm = llm or get_default_client()
    try:
        rewritten = llm.complete(build_rewrite_messages(question, history)).strip()
    except Exception:  # noqa: BLE001 - retrieval can still work with the raw question
        logger.warning("query rewrite failed, searching with the raw question", exc_info=True)
        return {"search_query": question}

    first_line = rewritten.splitlines()[0].strip() if rewritten else ""
    if not first_line or len(first_line) > MAX_SEARCH_QUERY_CHARS:
        return {"search_query": question}
    return {"search_query": first_line}


def retrieve_node(state: QueryState) -> dict:
    query = state.get("search_query") or state["question"]
    retrieved = hybrid_search(state["workspace_id"], query)
    if not retrieved:
        return {
            "retrieved_chunks": [],
            "draft_answer": NO_RESULTS_ANSWER,
            "finished": True,
        }
    return {"retrieved_chunks": retrieved}


def _parse_draft(raw: str, retrieved_chunks: list[RetrievedChunk]) -> tuple[str, list[Citation]]:
    citations: list[Citation] = []
    for line in raw.strip().splitlines():
        parsed = _match_citation_line(line)
        if parsed is None:
            continue
        sentence, chunk_nums = parsed
        for chunk_num in chunk_nums:
            if 1 <= chunk_num <= len(retrieved_chunks):
                chunk = retrieved_chunks[chunk_num - 1]
                citations.append(
                    {"paper_id": chunk["paper_id"], "chunk_id": chunk["chunk_id"], "quoted_text": sentence}
                )
    return "\n".join(line.strip() for line in raw.strip().splitlines() if line.strip()), citations


def synthesize_node(state: QueryState, llm: LLMClient | None = None) -> dict:
    llm = llm or get_default_client()
    critique_notes = state.get("critique_notes") if state.get("retries", 0) > 0 else None
    messages = build_synthesize_messages(
        state["question"], state["retrieved_chunks"], critique_notes, state.get("history")
    )
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
        if not line.strip():
            continue
        parsed = _match_citation_line(line)
        if parsed is None:
            notes.append(f'Line {i} has no citation tag: "{line.strip()}"')
            continue
        sentence, chunk_nums = parsed
        out_of_range = [n for n in chunk_nums if not (1 <= n <= len(retrieved_chunks))]
        if out_of_range:
            notes.append(
                f'Line {i} cites chunk(s) {out_of_range}, which were not retrieved: "{sentence}"'
            )
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


def _route_after_retrieve(state: QueryState) -> str:
    return END if state["finished"] else "synthesize"


def build_query_graph(llm: LLMClient | None = None):
    graph = StateGraph(QueryState)
    graph.add_node("rewrite", lambda s: rewrite_node(s, llm=llm))
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("synthesize", lambda s: synthesize_node(s, llm=llm))
    graph.add_node("critique", lambda s: critique_node(s, llm=llm))

    graph.set_entry_point("rewrite")
    graph.add_edge("rewrite", "retrieve")
    graph.add_conditional_edges(
        "retrieve", _route_after_retrieve, {"synthesize": "synthesize", END: END}
    )
    graph.add_edge("synthesize", "critique")
    graph.add_conditional_edges("critique", _route_after_critique, {"synthesize": "synthesize", END: END})

    return graph.compile()


def _next_stage(node: str, state: dict) -> str | None:
    if node == "rewrite":
        return "retrieve"
    if node == "retrieve":
        return None if state["finished"] else "synthesize"
    if node == "synthesize":
        return "critique"
    return None if state["finished"] else "synthesize"


# a graph node raised; stage says which one
class QueryFailed(Exception):
    def __init__(self, stage: str, cause: Exception):
        self.stage = stage
        self.cause = cause
        super().__init__(f"{stage} failed: {cause}")


# yields ("stage", ...) as nodes start, then ("done", state)
def stream_query(
    workspace_id: int,
    question: str,
    history: list[Turn] | None = None,
    llm: LLMClient | None = None,
) -> Iterator[tuple[str, dict]]:
    initial_state: QueryState = {
        "workspace_id": workspace_id,
        "question": question,
        "history": history or [],
        "search_query": question,
        "retrieved_chunks": [],
        "draft_answer": None,
        "citations": [],
        "critique_notes": [],
        "retries": 0,
        "max_retries": settings.RAG_MAX_RETRIES,
        "finished": False,
        "timings": {},
        "tokens_used": 0,
    }
    state: dict = dict(initial_state)
    stage = "rewrite" if history else "retrieve"
    yield "stage", {"stage": stage, "attempt": 1}

    counter = CountingClient(lambda: llm or get_default_client())
    started = time.monotonic()
    try:
        for update in build_query_graph(llm=counter).stream(initial_state, stream_mode="updates"):
            for node, node_update in update.items():
                state.update(node_update)
                now = time.monotonic()
                state["timings"][node] = round(state["timings"].get(node, 0.0) + now - started, 3)
                started = now

                next_stage = _next_stage(node, state)
                if next_stage and next_stage != stage:
                    stage = next_stage
                    yield "stage", {"stage": stage, "attempt": state["retries"] + 1}
    except Exception as exc:  # noqa: BLE001 - re-raised with the stage attached for diagnosis
        raise QueryFailed(stage, exc) from exc

    state["tokens_used"] = counter.estimated_tokens
    yield "done", state


def run_query(
    workspace_id: int,
    question: str,
    history: list[Turn] | None = None,
    llm: LLMClient | None = None,
) -> QueryState:
    state = {}
    for event, payload in stream_query(workspace_id, question, history, llm):
        if event == "done":
            state = payload
    return state  # type: ignore[return-value]

"""Tests for the self-correcting critique/retry cycle, using a FakeLLMClient.

These exercise the real compiled graph (synthesize -> critique -> conditional edge),
just entering at "synthesize" instead of "retrieve" so no database/embedding access
is needed - retrieve_node is a pure pgvector lookup and is covered by the ingestion
smoke test instead.
"""

from langgraph.graph import END, StateGraph

from agent.llm.fake_client import FakeLLMClient
from agent.query_graph import _route_after_critique, critique_node, synthesize_node
from agent.state import QueryState

RETRIEVED_CHUNKS = [
    {"paper_id": 1, "chunk_id": 10, "paper_title": "Attention Is All You Need", "text": "...", "score": 0.9},
    {"paper_id": 1, "chunk_id": 11, "paper_title": "Attention Is All You Need", "text": "...", "score": 0.8},
]


def _build_test_graph(llm):
    graph = StateGraph(QueryState)
    graph.add_node("synthesize", lambda s: synthesize_node(s, llm=llm))
    graph.add_node("critique", lambda s: critique_node(s, llm=llm))
    graph.set_entry_point("synthesize")
    graph.add_edge("synthesize", "critique")
    graph.add_conditional_edges("critique", _route_after_critique, {"synthesize": "synthesize", END: END})
    return graph.compile()


def _initial_state(max_retries=3) -> QueryState:
    return {
        "workspace_id": 1,
        "question": "What does the Transformer use instead of recurrence?",
        "retrieved_chunks": RETRIEVED_CHUNKS,
        "draft_answer": None,
        "citations": [],
        "critique_notes": [],
        "retries": 0,
        "max_retries": max_retries,
        "finished": False,
    }


def test_unsupported_claim_triggers_one_retry_then_clean_finish():
    fake = FakeLLMClient(
        responses=[
            "The Transformer uses self-attention. [1]\nIt was trained on Mars in 1823. [2]",
            "UNSUPPORTED: 2",
            "The Transformer uses self-attention. [1]",
            "UNSUPPORTED: none",
        ]
    )

    result = _build_test_graph(fake).invoke(_initial_state())

    assert result["finished"] is True
    assert result["retries"] == 1
    assert result["critique_notes"] == []
    assert result["draft_answer"] == "The Transformer uses self-attention. [1]"
    assert result["citations"] == [{"paper_id": 1, "chunk_id": 10, "quoted_text": "The Transformer uses self-attention."}]


def test_max_retries_cutoff_terminates_instead_of_looping_forever():
    fake = FakeLLMClient(
        responses=[
            "Bogus claim v1. [1]", "UNSUPPORTED: 1",
            "Bogus claim v2. [1]", "UNSUPPORTED: 1",
            "Bogus claim v3. [1]", "UNSUPPORTED: 1",
        ]
    )

    result = _build_test_graph(fake).invoke(_initial_state(max_retries=2))

    assert result["finished"] is True
    assert result["retries"] == 2
    assert result["critique_notes"] != []


def test_citation_to_unretrieved_chunk_is_caught_without_an_extra_llm_call():
    fake = FakeLLMClient(
        responses=[
            "Claim citing a chunk that was never retrieved. [99]",
            "Claim citing a chunk that was never retrieved. [1]",
            "UNSUPPORTED: none",
        ]
    )

    result = _build_test_graph(fake).invoke(_initial_state(max_retries=3))

    assert result["finished"] is True
    assert result["retries"] == 1

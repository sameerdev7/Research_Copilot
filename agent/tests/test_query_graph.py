import pytest
from langgraph.graph import END, StateGraph

from agent.llm.errors import LLMNotConfigured
from agent.llm.fake_client import FakeLLMClient
from agent.query_graph import (
    NO_RESULTS_ANSWER,
    QueryFailed,
    _route_after_critique,
    critique_node,
    rewrite_node,
    run_query,
    stream_query,
    synthesize_node,
)
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
        "history": [],
        "search_query": "What does the Transformer use instead of recurrence?",
        "timings": {},
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


def test_multiple_citation_tags_on_one_line_are_all_parsed():
    # regression: only the last tag on a line used to be parsed
    fake = FakeLLMClient(responses=["The Transformer uses self-attention. [1][2]", "UNSUPPORTED: none"])

    result = _build_test_graph(fake).invoke(_initial_state())

    assert result["finished"] is True
    assert result["retries"] == 0
    assert result["citations"] == [
        {"paper_id": 1, "chunk_id": 10, "quoted_text": "The Transformer uses self-attention."},
        {"paper_id": 1, "chunk_id": 11, "quoted_text": "The Transformer uses self-attention."},
    ]


def test_one_out_of_range_tag_among_several_still_flags_the_line():
    fake = FakeLLMClient(
        responses=[
            "The Transformer uses self-attention. [1][99]",
            "The Transformer uses self-attention. [1]",
            "UNSUPPORTED: none",
        ]
    )

    result = _build_test_graph(fake).invoke(_initial_state(max_retries=3))

    assert result["finished"] is True
    assert result["retries"] == 1


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


HISTORY = [
    {"role": "user", "content": "What is the Transformer?"},
    {"role": "assistant", "content": "An architecture built on self-attention."},
]


def test_rewrite_without_history_skips_the_llm():
    state = {"question": "What is attention?", "history": []}

    assert rewrite_node(state, llm=FakeLLMClient([])) == {"search_query": "What is attention?"}


def test_rewrite_resolves_a_follow_up_using_history():
    state = {"question": "How does it scale?", "history": HISTORY}
    fake = FakeLLMClient(["How does the Transformer scale with sequence length?\nextra"])

    assert rewrite_node(state, llm=fake) == {
        "search_query": "How does the Transformer scale with sequence length?"
    }


def test_rewrite_failure_falls_back_to_the_raw_question():
    class Broken:
        def complete(self, messages):
            raise RuntimeError("provider down")

    state = {"question": "How does it scale?", "history": HISTORY}

    assert rewrite_node(state, llm=Broken()) == {"search_query": "How does it scale?"}


def test_history_reaches_the_synthesize_prompt():
    seen = []

    class Recording:
        def complete(self, messages):
            seen.append(messages)
            return "Self-attention. [1]"

    state = {**_initial_state(), "history": HISTORY}
    synthesize_node(state, llm=Recording())

    assert "What is the Transformer?" in seen[0][1]["content"]


@pytest.fixture
def stub_retrieval(monkeypatch):
    def install(chunks):
        monkeypatch.setattr("agent.query_graph.hybrid_search", lambda workspace_id, query: chunks)

    return install


def test_stream_query_reports_stages_then_final_state(stub_retrieval):
    stub_retrieval(RETRIEVED_CHUNKS)
    fake = FakeLLMClient(["Self-attention. [1]", "UNSUPPORTED: none"])

    events = list(stream_query(1, "What replaces recurrence?", llm=fake))

    stages = [payload["stage"] for kind, payload in events if kind == "stage"]
    assert stages == ["retrieve", "synthesize", "critique"]
    final = events[-1][1]
    assert events[-1][0] == "done"
    assert final["draft_answer"] == "Self-attention. [1]"
    assert set(final["timings"]) == {"rewrite", "retrieve", "synthesize", "critique"}


def test_stream_query_with_history_starts_at_rewrite_and_searches_the_rewrite(stub_retrieval, monkeypatch):
    searched = []
    monkeypatch.setattr(
        "agent.query_graph.hybrid_search", lambda workspace_id, query: searched.append(query) or RETRIEVED_CHUNKS
    )
    fake = FakeLLMClient(["Transformer scaling", "Quadratic in length. [1]", "UNSUPPORTED: none"])

    events = list(stream_query(1, "How does it scale?", history=HISTORY, llm=fake))

    assert events[0] == ("stage", {"stage": "rewrite", "attempt": 1})
    assert searched == ["Transformer scaling"]
    assert events[-1][1]["search_query"] == "Transformer scaling"


def test_no_retrieved_chunks_ends_early_without_any_llm_call(stub_retrieval):
    stub_retrieval([])

    result = run_query(1, "Anything?", llm=FakeLLMClient([]))

    assert result["draft_answer"] == NO_RESULTS_ANSWER
    assert result["citations"] == []


def test_stage_is_attached_to_failures(stub_retrieval):
    stub_retrieval(RETRIEVED_CHUNKS)

    class Broken:
        def complete(self, messages):
            raise LLMNotConfigured("no key")

    with pytest.raises(QueryFailed) as info:
        run_query(1, "Q?", llm=Broken())

    assert info.value.stage == "synthesize"
    assert isinstance(info.value.cause, LLMNotConfigured)

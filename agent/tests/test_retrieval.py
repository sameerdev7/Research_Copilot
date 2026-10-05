from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.db import connection, transaction

from agent.retrieval import (
    _enable_iterative_scan,
    cap_per_paper,
    hybrid_search,
    reciprocal_rank_fusion,
)
from papers.models import Chunk, Paper
from workspaces.models import Workspace


def _vector(*leading: float) -> list[float]:
    return [*leading, *([0.0] * (384 - len(leading)))]


def test_rrf_ranks_items_found_by_both_retrievers_first():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 4, 1]], k=60)

    assert fused[:2] == [1, 3]  # appear in both lists
    assert set(fused) == {1, 2, 3, 4}


def test_rrf_handles_an_empty_ranking():
    assert reciprocal_rank_fusion([[5, 6], []], k=60) == [5, 6]


def test_cap_per_paper_keeps_order_and_limits_each_paper():
    chunks = [{"paper_id": p, "chunk_id": i} for i, p in enumerate([1, 1, 1, 2, 1, 2])]

    kept = cap_per_paper(chunks, limit=2)

    assert [c["chunk_id"] for c in kept] == [0, 1, 3, 5]


@pytest.fixture
def workspace(db):
    user = User.objects.create_user(username="alice", password="pw")
    return Workspace.objects.create(user=user, name="ws")


def _paper(workspace, arxiv_id, title, status="ready"):
    return Paper.objects.create(
        workspace=workspace, arxiv_id=arxiv_id, title=title, pdf_url="https://x/pdf", status=status
    )


def _chunk(paper, index, text, embedding):
    return Chunk.objects.create(
        paper=paper, chunk_index=index, text=text, token_count=len(text.split()), embedding=embedding
    )


@patch("agent.retrieval.embed_text", return_value=_vector(1.0))
def test_hybrid_search_finds_exact_term_the_vector_search_would_miss(_embed, workspace):
    paper = _paper(workspace, "1", "Paper")
    semantic = _chunk(paper, 0, "Completely unrelated prose about gardening.", _vector(1.0))
    keyword = _chunk(paper, 1, "BM25 is a classic lexical ranking function.", _vector(0.0, 1.0))

    results = hybrid_search(workspace.id, "What is BM25?", k=2)

    assert {r["chunk_id"] for r in results} == {semantic.id, keyword.id}
    assert results[0]["paper_title"] == "Paper"
    assert results[0]["arxiv_id"] == "1"


@patch("agent.retrieval.embed_text", return_value=_vector(1.0))
def test_hybrid_search_ignores_unready_papers_and_other_workspaces(_embed, workspace):
    ready = _paper(workspace, "1", "Ready")
    pending = _paper(workspace, "2", "Pending", status="pending")
    other = Workspace.objects.create(user=workspace.user, name="other")
    elsewhere = _paper(other, "3", "Elsewhere")
    mine = _chunk(ready, 0, "attention", _vector(1.0))
    _chunk(pending, 0, "attention", _vector(1.0))
    _chunk(elsewhere, 0, "attention", _vector(1.0))

    results = hybrid_search(workspace.id, "attention")

    assert [r["chunk_id"] for r in results] == [mine.id]


@patch("agent.retrieval.embed_text", return_value=_vector(1.0))
def test_hybrid_search_caps_chunks_per_paper(_embed, workspace, settings):
    settings.RAG_MAX_CHUNKS_PER_PAPER = 2
    big, small = _paper(workspace, "1", "Big"), _paper(workspace, "2", "Small")
    for i in range(5):
        _chunk(big, i, f"attention detail {i}", _vector(1.0, 0.01 * i))
    _chunk(small, 0, "attention overview", _vector(0.5, 0.5))

    results = hybrid_search(workspace.id, "attention", k=8)

    assert sorted(r["paper_title"] for r in results) == ["Big", "Big", "Small"]


@patch("agent.retrieval.embed_text", return_value=_vector(1.0))
def test_hybrid_search_survives_punctuation_heavy_questions(_embed, workspace):
    paper = _paper(workspace, "1", "Paper")
    _chunk(paper, 0, "plain text", _vector(1.0))

    assert hybrid_search(workspace.id, "what's (this)? & | ! ' : *")  # must not raise a tsquery syntax error


def test_iterative_hnsw_scan_is_enabled_for_the_vector_query(db):
    with transaction.atomic():
        _enable_iterative_scan()
        with connection.cursor() as cursor:
            cursor.execute("SHOW hnsw.iterative_scan")
            assert cursor.fetchone()[0] == "strict_order"

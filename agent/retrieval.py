from __future__ import annotations

import re

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import DatabaseError, connection, transaction
from pgvector.django import CosineDistance

from .embeddings import embed_text
from .state import RetrievedChunk

FTS_CONFIG = "english"
WORD_RE = re.compile(r"[A-Za-z0-9]{2,}")


# merge ranked id lists; each id scores 1/(k+rank) per list
def reciprocal_rank_fusion(rankings: list[list[int]], k: int) -> list[int]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item_id: scores[item_id], reverse=True)


# keep rank order, at most `limit` chunks per paper
def cap_per_paper(chunks: list[RetrievedChunk], limit: int) -> list[RetrievedChunk]:
    seen: dict[int, int] = {}
    kept = []
    for chunk in chunks:
        seen[chunk["paper_id"]] = seen.get(chunk["paper_id"], 0) + 1
        if seen[chunk["paper_id"]] <= limit:
            kept.append(chunk)
    return kept


# the HNSW index is global, so filtering by workspace can starve results; keep scanning until enough match
def _enable_iterative_scan() -> None:
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL hnsw.iterative_scan = strict_order")
    except DatabaseError:
        pass  # pgvector older than 0.8


def hybrid_search(workspace_id: int, query: str, k: int | None = None) -> list[RetrievedChunk]:
    from papers.models import Chunk  # avoid a hard Django-apps-not-ready import at module load

    k = k or settings.RAG_RETRIEVAL_K
    candidates = settings.RAG_CANDIDATES
    query_vector = embed_text(query)

    base = (
        Chunk.objects.filter(
            paper__workspace_id=workspace_id, paper__status="ready", embedding__isnull=False
        )
        .select_related("paper")
        .annotate(distance=CosineDistance("embedding", query_vector))
    )

    with transaction.atomic():
        _enable_iterative_scan()
        vector_hits = list(base.order_by("distance")[:candidates])

    keyword_hits = []
    words = WORD_RE.findall(query)
    if words:
        # OR the words together so a chunk needs only one of them
        fts_query = SearchQuery(" | ".join(words), config=FTS_CONFIG, search_type="raw")
        document = SearchVector("text", config=FTS_CONFIG)
        keyword_hits = list(
            base.annotate(search=document, rank=SearchRank(document, fts_query))
            .filter(search=fts_query)
            .order_by("-rank")[:candidates]
        )

    by_id = {c.id: c for c in vector_hits + keyword_hits}
    fused_ids = reciprocal_rank_fusion(
        [[c.id for c in vector_hits], [c.id for c in keyword_hits]], settings.RAG_RRF_K
    )
    fused: list[RetrievedChunk] = [
        {
            "paper_id": by_id[i].paper_id,
            "chunk_id": i,
            "paper_title": by_id[i].paper.title,
            "arxiv_id": by_id[i].paper.arxiv_id,
            "text": by_id[i].text,
            "score": 1 - by_id[i].distance,
        }
        for i in fused_ids
    ]
    return cap_per_paper(fused, settings.RAG_MAX_CHUNKS_PER_PAPER)[:k]

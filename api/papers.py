import logging

import requests
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from papers.models import Paper
from papers.services import arxiv_client
from papers.tasks import ingest_paper

from .diagnostics import CopilotError
from .serializers import PaperSerializer
from .throttles import SearchThrottle
from .workspaces import owned_workspace

logger = logging.getLogger(__name__)

MAX_INGEST_BATCH = 10


def _arxiv_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("arXiv request failed: %s", exc)
        raise CopilotError(
            "arxiv_unavailable",
            "Couldn't reach arXiv.",
            "arXiv may be down or rate-limiting you. Try again in a moment.",
            status=502,
        ) from exc


def _looks_like_arxiv_id(token: str) -> bool:
    return bool(token) and token[0].isdigit() and "." in token


# queue ingestion; mark the paper failed if the broker is down
def _enqueue(paper: Paper) -> None:
    try:
        ingest_paper.delay(paper.id)
    except Exception as exc:  # noqa: BLE001 - broker errors vary (kombu, redis, OS)
        logger.exception("could not enqueue ingestion for paper %s", paper.id)
        paper.status = "failed"
        paper.failure_reason = f"Could not queue the ingestion job (is Redis running?): {exc}"
        paper.save(update_fields=["status", "failure_reason"])


@api_view(["GET"])
def paper_list(request, workspace_id):
    workspace = owned_workspace(request, workspace_id)
    return Response(PaperSerializer(workspace.papers.all(), many=True).data)


@api_view(["POST"])
@throttle_classes([SearchThrottle])
def paper_search(request, workspace_id):
    workspace = owned_workspace(request, workspace_id)
    query = str(request.data.get("query", "")).strip()
    if not query:
        raise ValidationError({"query": "Enter a topic or an arXiv ID."})

    ids = [tok for tok in query.replace(",", " ").split() if _looks_like_arxiv_id(tok)]
    candidates = _arxiv_call(arxiv_client.get_by_ids, ids) if ids else _arxiv_call(arxiv_client.search, query, 10)

    existing = set(workspace.papers.values_list("arxiv_id", flat=True))
    for candidate in candidates:
        candidate["already_added"] = candidate["arxiv_id"] in existing
    return Response(candidates)


@api_view(["POST"])
def paper_ingest(request, workspace_id):
    workspace = owned_workspace(request, workspace_id)
    arxiv_ids = request.data.get("arxiv_ids")
    if not isinstance(arxiv_ids, list) or not arxiv_ids or not all(isinstance(i, str) for i in arxiv_ids):
        raise ValidationError({"arxiv_ids": "Pick at least one paper."})
    if len(arxiv_ids) > MAX_INGEST_BATCH:
        raise ValidationError({"arxiv_ids": f"Add at most {MAX_INGEST_BATCH} papers at a time."})

    # re-fetch metadata by id instead of trusting the client
    papers = []
    for candidate in _arxiv_call(arxiv_client.get_by_ids, arxiv_ids):
        paper, created = Paper.objects.get_or_create(
            workspace=workspace,
            arxiv_id=candidate["arxiv_id"],
            defaults={
                "title": candidate["title"],
                "authors": candidate["authors"],
                "abstract": candidate["abstract"],
                "pdf_url": candidate["pdf_url"],
            },
        )
        if created:
            _enqueue(paper)
        papers.append(paper)
    return Response(PaperSerializer(papers, many=True).data, status=201)


@api_view(["POST"])
def paper_retry(request, workspace_id, paper_id):
    paper = get_object_or_404(owned_workspace(request, workspace_id).papers, pk=paper_id)
    if paper.status != "failed":
        raise CopilotError("not_failed", "Only failed papers can be retried.")
    paper.status = "pending"
    paper.failure_reason = ""
    paper.queued_at = timezone.now()
    paper.save(update_fields=["status", "failure_reason", "queued_at"])
    _enqueue(paper)
    paper.refresh_from_db()
    return Response(PaperSerializer(paper).data)


@api_view(["DELETE"])
def paper_detail(request, workspace_id, paper_id):
    owned_workspace(request, workspace_id).papers.filter(pk=paper_id).delete()
    return Response(status=204)

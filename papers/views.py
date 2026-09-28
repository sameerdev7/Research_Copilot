from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render

from workspaces.models import Workspace

from .models import Paper
from .services import arxiv_client
from .tasks import ingest_paper


def _get_owned_workspace(request, workspace_id):
    workspace = get_object_or_404(Workspace, pk=workspace_id)
    if workspace.user_id != request.user.id:
        return None
    return workspace


def _paper_status_context(workspace):
    papers = list(workspace.papers.all())
    has_pending = any(p.status == "pending" for p in papers)
    return {"workspace": workspace, "papers": papers, "has_pending": has_pending}


@login_required
def paper_list(request, workspace_id):
    workspace = _get_owned_workspace(request, workspace_id)
    if workspace is None:
        return HttpResponseForbidden()
    return render(request, "papers/paper_list.html", _paper_status_context(workspace))


@login_required
def paper_status_partial(request, workspace_id):
    workspace = _get_owned_workspace(request, workspace_id)
    if workspace is None:
        return HttpResponseForbidden()
    return render(request, "papers/_paper_status.html", _paper_status_context(workspace))


@login_required
def search_papers(request, workspace_id):
    workspace = _get_owned_workspace(request, workspace_id)
    if workspace is None:
        return HttpResponseForbidden()

    query = request.POST.get("query", "").strip()
    candidates = []
    if query:
        ids = [tok.strip() for tok in query.replace(",", " ").split() if _looks_like_arxiv_id(tok)]
        if ids:
            candidates = arxiv_client.get_by_ids(ids)
        else:
            candidates = arxiv_client.search(query, max_results=10)

    existing_ids = set(workspace.papers.values_list("arxiv_id", flat=True))
    for c in candidates:
        c["already_added"] = c["arxiv_id"] in existing_ids

    return render(
        request,
        "papers/_search_results.html",
        {"workspace": workspace, "candidates": candidates, "query": query},
    )


def _looks_like_arxiv_id(token: str) -> bool:
    return bool(token) and token[0].isdigit() and "." in token


@login_required
def ingest_papers(request, workspace_id):
    workspace = _get_owned_workspace(request, workspace_id)
    if workspace is None:
        return HttpResponseForbidden()

    selected_ids = request.POST.getlist("arxiv_id")
    # Re-fetch metadata by ID rather than trusting paired hidden form fields: HTML only
    # submits *checked* checkboxes but *all* hidden inputs, so pairing them by position
    # would silently mismatch a checked ID with another candidate's title/abstract/url.
    for candidate in arxiv_client.get_by_ids(selected_ids):
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
            ingest_paper.delay(paper.id)

    return render(request, "papers/_paper_status.html", _paper_status_context(workspace))

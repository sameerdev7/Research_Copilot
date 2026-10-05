from unittest.mock import patch

import requests

from papers.models import Paper

CANDIDATE_A = {
    "arxiv_id": "1706.03762",
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "abstract": "...",
    "pdf_url": "https://arxiv.org/pdf/1706.03762",
}
CANDIDATE_B = {**CANDIDATE_A, "arxiv_id": "2411.18583", "title": "Literature Review", "authors": ["N. Ali"]}


@patch("api.papers.arxiv_client.search", return_value=[dict(CANDIDATE_A), dict(CANDIDATE_B)])
def test_search_flags_papers_already_in_the_workspace(_search, api, workspace):
    Paper.objects.create(workspace=workspace, arxiv_id="1706.03762", title="x", pdf_url="https://x")

    response = api.post(f"/api/workspaces/{workspace.id}/papers/search/", {"query": "attention"})

    flags = {c["arxiv_id"]: c["already_added"] for c in response.json()}
    assert flags == {"1706.03762": True, "2411.18583": False}


@patch("api.papers.arxiv_client.get_by_ids", return_value=[dict(CANDIDATE_A)])
def test_search_by_arxiv_id_uses_id_lookup(get_by_ids, api, workspace):
    api.post(f"/api/workspaces/{workspace.id}/papers/search/", {"query": "1706.03762"})

    get_by_ids.assert_called_once_with(["1706.03762"])


@patch("api.papers.arxiv_client.search", side_effect=requests.ConnectionError("boom"))
def test_arxiv_outage_is_a_diagnosed_502(_search, api, workspace):
    response = api.post(f"/api/workspaces/{workspace.id}/papers/search/", {"query": "attention"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "arxiv_unavailable"
    assert response.json()["error"]["hint"]


@patch("api.papers.arxiv_client.get_by_ids", return_value=[dict(CANDIDATE_B)])
@patch("api.papers.ingest_paper.delay")
def test_ingest_stores_refetched_metadata_and_enqueues(delay, _get, api, workspace):
    response = api.post(f"/api/workspaces/{workspace.id}/papers/ingest/", {"arxiv_ids": ["2411.18583"]}, format="json")

    assert response.status_code == 201
    paper = Paper.objects.get(workspace=workspace, arxiv_id="2411.18583")
    assert paper.title == "Literature Review"
    delay.assert_called_once_with(paper.id)


@patch("api.papers.arxiv_client.get_by_ids", return_value=[dict(CANDIDATE_A)])
@patch("api.papers.ingest_paper.delay")
def test_ingesting_an_existing_paper_does_not_requeue(delay, _get, api, workspace):
    Paper.objects.create(workspace=workspace, arxiv_id="1706.03762", title="x", pdf_url="https://x")

    api.post(f"/api/workspaces/{workspace.id}/papers/ingest/", {"arxiv_ids": ["1706.03762"]}, format="json")

    delay.assert_not_called()


@patch("api.papers.arxiv_client.get_by_ids", return_value=[dict(CANDIDATE_A)])
@patch("api.papers.ingest_paper.delay", side_effect=ConnectionError("redis down"))
def test_broker_outage_fails_the_paper_visibly_instead_of_leaving_it_pending(_delay, _get, api, workspace):
    response = api.post(f"/api/workspaces/{workspace.id}/papers/ingest/", {"arxiv_ids": ["1706.03762"]}, format="json")

    assert response.status_code == 201
    paper = Paper.objects.get()
    assert paper.status == "failed"
    assert "Redis" in paper.failure_reason
    assert response.json()[0]["status"] == "failed"


def test_ingest_validates_the_id_list(api, workspace):
    url = f"/api/workspaces/{workspace.id}/papers/ingest/"

    assert api.post(url, {"arxiv_ids": []}, format="json").status_code == 400
    assert api.post(url, {"arxiv_ids": ["1.1"] * 11}, format="json").status_code == 400


@patch("api.papers.ingest_paper.delay")
def test_retry_requeues_only_failed_papers(delay, api, workspace):
    failed = Paper.objects.create(
        workspace=workspace, arxiv_id="1", title="x", pdf_url="https://x", status="failed", failure_reason="boom"
    )
    ready = Paper.objects.create(workspace=workspace, arxiv_id="2", title="y", pdf_url="https://x", status="ready")

    ok = api.post(f"/api/workspaces/{workspace.id}/papers/{failed.id}/retry/")
    bad = api.post(f"/api/workspaces/{workspace.id}/papers/{ready.id}/retry/")

    assert ok.json()["status"] == "pending"
    assert ok.json()["failure_reason"] == ""
    delay.assert_called_once_with(failed.id)
    assert bad.json()["error"]["code"] == "not_failed"


def test_delete_paper(api, workspace):
    paper = Paper.objects.create(workspace=workspace, arxiv_id="1", title="x", pdf_url="https://x")

    assert api.delete(f"/api/workspaces/{workspace.id}/papers/{paper.id}/").status_code == 204
    assert not Paper.objects.exists()

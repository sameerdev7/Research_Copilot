from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from papers.models import Paper
from workspaces.models import Workspace


@pytest.fixture
def user(db):
    return User.objects.create_user(username="alice", password="pw")


@pytest.fixture
def workspace(user):
    return Workspace.objects.create(user=user, name="ws")


@pytest.fixture
def client_logged_in(client, user):
    client.force_login(user)
    return client


@patch("papers.views.arxiv_client.search")
def test_search_papers_renders_candidates(mock_search, client_logged_in, workspace):
    mock_search.return_value = [
        {
            "arxiv_id": "1706.03762",
            "title": "Attention Is All You Need",
            "authors": ["Ashish Vaswani"],
            "abstract": "...",
            "pdf_url": "https://arxiv.org/pdf/1706.03762",
        }
    ]

    response = client_logged_in.post(
        reverse("paper-search", args=[workspace.pk]), {"query": "attention"}
    )

    assert response.status_code == 200
    assert b"Attention Is All You Need" in response.content
    mock_search.assert_called_once()


CANDIDATE_A = {
    "arxiv_id": "1706.03762",
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "abstract": "...",
    "pdf_url": "https://arxiv.org/pdf/1706.03762",
}
CANDIDATE_B = {
    "arxiv_id": "2411.18583",
    "title": "Automated Literature Review Using NLP Techniques",
    "authors": ["Nurshat Fateh Ali"],
    "abstract": "...",
    "pdf_url": "https://arxiv.org/pdf/2411.18583",
}


@patch("papers.views.arxiv_client.get_by_ids")
@patch("papers.views.ingest_paper.delay")
def test_ingest_papers_creates_paper_and_enqueues_celery_task(mock_delay, mock_get_by_ids, client_logged_in, workspace):
    mock_get_by_ids.return_value = [CANDIDATE_A]

    response = client_logged_in.post(
        reverse("paper-ingest", args=[workspace.pk]), {"arxiv_id": ["1706.03762"]}
    )

    assert response.status_code == 200
    mock_get_by_ids.assert_called_once_with(["1706.03762"])
    paper = Paper.objects.get(workspace=workspace, arxiv_id="1706.03762")
    assert paper.authors == ["Ashish Vaswani", "Noam Shazeer"]
    mock_delay.assert_called_once_with(paper.id)


@patch("papers.views.arxiv_client.get_by_ids")
@patch("papers.views.ingest_paper.delay")
def test_ingesting_only_the_checked_candidate_does_not_mix_up_metadata(
    mock_delay, mock_get_by_ids, client_logged_in, workspace
):
    # Regression test: only CANDIDATE_B's checkbox is checked, but a naive positional
    # zip() of getlist("arxiv_id") with getlist("title") etc. would have paired it with
    # CANDIDATE_A's metadata, since unchecked checkboxes are omitted from POST data but
    # sibling hidden inputs are not. The view must re-fetch metadata by the selected ID.
    mock_get_by_ids.return_value = [CANDIDATE_B]

    client_logged_in.post(reverse("paper-ingest", args=[workspace.pk]), {"arxiv_id": ["2411.18583"]})

    mock_get_by_ids.assert_called_once_with(["2411.18583"])
    paper = Paper.objects.get(workspace=workspace, arxiv_id="2411.18583")
    assert paper.title == CANDIDATE_B["title"]


@patch("papers.views.arxiv_client.get_by_ids")
@patch("papers.views.ingest_paper.delay")
def test_ingesting_same_paper_twice_does_not_reenqueue(mock_delay, mock_get_by_ids, client_logged_in, workspace):
    Paper.objects.create(
        workspace=workspace, arxiv_id="1706.03762", title="Attention", pdf_url="https://x/pdf"
    )
    mock_get_by_ids.return_value = [CANDIDATE_A]

    client_logged_in.post(reverse("paper-ingest", args=[workspace.pk]), {"arxiv_id": ["1706.03762"]})

    mock_delay.assert_not_called()

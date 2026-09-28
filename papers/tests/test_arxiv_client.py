from pathlib import Path
from unittest.mock import Mock, patch

from papers.services import arxiv_client

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_response.xml"


def _fake_response():
    response = Mock()
    response.content = FIXTURE.read_bytes()
    response.raise_for_status = Mock()
    return response


@patch("papers.services.arxiv_client.requests.get")
def test_search_parses_atom_feed(mock_get):
    mock_get.return_value = _fake_response()

    results = arxiv_client.search("attention")

    assert len(results) == 1
    paper = results[0]
    assert paper["arxiv_id"] == "1706.03762v7"
    assert paper["title"] == "Attention Is All You Need"
    assert paper["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert paper["pdf_url"] == "https://arxiv.org/pdf/1706.03762v7"
    assert "recurrent" in paper["abstract"]


@patch("papers.services.arxiv_client.requests.get")
def test_get_by_ids_builds_id_list_param(mock_get):
    mock_get.return_value = _fake_response()

    results = arxiv_client.get_by_ids(["1706.03762"])

    assert mock_get.call_args.kwargs["params"]["id_list"] == "1706.03762"
    assert results[0]["arxiv_id"] == "1706.03762v7"


def test_get_by_ids_empty_list_skips_request():
    assert arxiv_client.get_by_ids([]) == []

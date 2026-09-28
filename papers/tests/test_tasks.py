from unittest.mock import patch

import pytest
from django.contrib.auth.models import User

from papers.models import Chunk, Paper
from papers.tasks import ingest_paper
from workspaces.models import Workspace

SAMPLE_TEXT = "Sentence one about transformers. " * 5 + "Sentence two about attention. " * 5


@pytest.mark.django_db
@patch("papers.tasks.pdf_extract.extract_text", return_value=SAMPLE_TEXT)
@patch("papers.tasks.pdf_extract.download_pdf", return_value=b"%PDF-fake")
def test_ingest_paper_creates_embedded_chunks(mock_download, mock_extract):
    user = User.objects.create_user(username="alice", password="pw")
    workspace = Workspace.objects.create(user=user, name="ws")
    paper = Paper.objects.create(
        workspace=workspace,
        arxiv_id="1234.5678",
        title="Test Paper",
        pdf_url="https://arxiv.org/pdf/1234.5678",
    )

    ingest_paper(paper.id)

    paper.refresh_from_db()
    assert paper.status == "ready"
    chunks = list(Chunk.objects.filter(paper=paper))
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.embedding is not None
        assert len(chunk.embedding) == 384


@pytest.mark.django_db
@patch("papers.tasks.pdf_extract.extract_text", return_value="")
@patch("papers.tasks.pdf_extract.download_pdf", return_value=b"%PDF-fake")
def test_ingest_paper_marks_failed_on_empty_text(mock_download, mock_extract):
    user = User.objects.create_user(username="bob", password="pw")
    workspace = Workspace.objects.create(user=user, name="ws")
    paper = Paper.objects.create(
        workspace=workspace,
        arxiv_id="1234.5679",
        title="Empty Paper",
        pdf_url="https://arxiv.org/pdf/1234.5679",
    )

    with pytest.raises(ValueError):
        ingest_paper(paper.id)

    paper.refresh_from_db()
    assert paper.status == "failed"
    assert paper.failure_reason

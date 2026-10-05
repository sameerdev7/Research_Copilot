from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from langchain_text_splitters import RecursiveCharacterTextSplitter

from agent.embeddings import embed_texts

from .models import Chunk, IngestionJob, Paper
from .services import pdf_extract

STUCK_AFTER_MINUTES = 30
RETRY_DELAY_SECONDS = 30


# network blips and 5xx responses are worth retrying; anything else is not
def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    return isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code >= 500


@shared_task(bind=True, max_retries=2, acks_late=True, soft_time_limit=300, time_limit=360)
def ingest_paper(self, paper_id: int):
    paper = Paper.objects.get(pk=paper_id)
    job = IngestionJob.objects.create(paper=paper, status="running", started_at=timezone.now())

    try:
        pdf_bytes = pdf_extract.download_pdf(paper.pdf_url)
        text = pdf_extract.extract_text(pdf_bytes)
        if not text:
            raise ValueError("no extractable text in PDF")

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.RAG_CHUNK_SIZE,
            chunk_overlap=settings.RAG_CHUNK_OVERLAP,
        )
        chunk_texts = splitter.split_text(text)
        embeddings = embed_texts(chunk_texts)

        Chunk.objects.filter(paper=paper).delete()
        Chunk.objects.bulk_create(
            [
                Chunk(
                    paper=paper,
                    chunk_index=i,
                    text=chunk_text,
                    token_count=len(chunk_text.split()),
                    embedding=embedding,
                )
                for i, (chunk_text, embedding) in enumerate(zip(chunk_texts, embeddings))
            ]
        )

        paper.status = "ready"
        paper.failure_reason = ""
        paper.save(update_fields=["status", "failure_reason"])

        job.status = "done"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at"])
    except Exception as exc:  # noqa: BLE001 - report failure on the paper/job, don't crash the worker
        will_retry = _is_transient(exc) and self.request.retries < self.max_retries
        paper.status = "pending" if will_retry else "failed"
        paper.failure_reason = str(exc)
        paper.save(update_fields=["status", "failure_reason"])

        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at"])
        if will_retry:
            raise self.retry(exc=exc, countdown=RETRY_DELAY_SECONDS * (self.request.retries + 1))
        raise


# marks papers whose worker never finished them as failed, so they can be retried
@shared_task
def fail_stuck_papers(minutes: int = STUCK_AFTER_MINUTES) -> int:
    cutoff = timezone.now() - timedelta(minutes=minutes)
    return Paper.objects.filter(status="pending", queued_at__lt=cutoff).update(
        status="failed", failure_reason="Timed out waiting for the worker. Retry it."
    )

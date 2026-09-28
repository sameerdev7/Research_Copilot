from django.utils import timezone
from langchain_text_splitters import RecursiveCharacterTextSplitter

from celery import shared_task

from agent.embeddings import embed_texts
from django.conf import settings

from .models import Chunk, IngestionJob, Paper
from .services import pdf_extract


@shared_task(bind=True, max_retries=2)
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
        paper.status = "failed"
        paper.failure_reason = str(exc)
        paper.save(update_fields=["status", "failure_reason"])

        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at"])
        raise

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import models
from django.utils import timezone
from pgvector.django import HnswIndex, VectorField

from workspaces.models import Workspace


class Paper(models.Model):
    STATUS_CHOICES = [
        ("pending", "pending"),
        ("ready", "ready"),
        ("failed", "failed"),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="papers")
    arxiv_id = models.CharField(max_length=32)
    title = models.CharField(max_length=512)
    authors = models.JSONField(default=list)
    abstract = models.TextField(blank=True)
    pdf_url = models.URLField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # when ingestion was last queued; the stuck-paper sweep measures from here
    queued_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "arxiv_id"], name="unique_paper_per_workspace"),
        ]

    def __str__(self):
        return self.title


class Chunk(models.Model):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    text = models.TextField()
    token_count = models.IntegerField()
    embedding = VectorField(dimensions=settings.EMBEDDING_DIM, null=True)

    class Meta:
        ordering = ["paper_id", "chunk_index"]
        indexes = [
            HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
            GinIndex(SearchVector("text", config="english"), name="chunk_text_fts"),
        ]

    def __str__(self):
        return f"{self.paper_id}:{self.chunk_index}"


class IngestionJob(models.Model):
    STATUS_CHOICES = [
        ("queued", "queued"),
        ("running", "running"),
        ("done", "done"),
        ("failed", "failed"),
    ]

    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="ingestion_jobs")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued")
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"IngestionJob(paper={self.paper_id}, status={self.status})"

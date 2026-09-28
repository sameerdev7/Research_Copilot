from django.contrib import admin

from .models import Chunk, IngestionJob, Paper


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "arxiv_id", "workspace", "status", "created_at")
    list_filter = ("status", "workspace")
    search_fields = ("title", "arxiv_id")


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("id", "paper", "chunk_index", "token_count")
    list_filter = ("paper__workspace",)
    readonly_fields = ("paper", "chunk_index", "text", "token_count", "embedding")

    def has_add_permission(self, request):
        return False


@admin.register(IngestionJob)
class IngestionJobAdmin(admin.ModelAdmin):
    list_display = ("id", "paper", "status", "started_at", "finished_at")
    list_filter = ("status",)

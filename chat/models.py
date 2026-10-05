from django.db import models

from workspaces.models import Workspace


class Conversation(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Conversation({self.id}) in {self.workspace_id}"


class Message(models.Model):
    ROLE_CHOICES = [("user", "user"), ("assistant", "assistant")]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField()
    citations = models.JSONField(default=list, blank=True)
    critique_notes = models.JSONField(default=list, blank=True)
    # chunks retrieved for the answer; [N] tags index into this list
    sources = models.JSONField(default=list, blank=True)
    # timings, search query, retries, or an "error" entry if the turn failed
    diagnostics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"

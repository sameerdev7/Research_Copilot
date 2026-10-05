from django.contrib.auth.models import User
from rest_framework import serializers

from chat.models import Conversation, Message
from papers.models import Paper
from workspaces.models import Workspace


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username"]


class WorkspaceSerializer(serializers.ModelSerializer):
    paper_count = serializers.IntegerField(read_only=True)
    ready_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Workspace
        fields = ["id", "name", "created_at", "paper_count", "ready_count"]
        read_only_fields = ["created_at"]


class PaperSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paper
        fields = ["id", "arxiv_id", "title", "authors", "abstract", "status", "failure_reason", "created_at"]


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "title", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "content", "sources", "critique_notes", "diagnostics", "created_at"]

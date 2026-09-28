from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from chat.models import Message
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


FAKE_RESULT = {
    "draft_answer": "Self-attention replaces recurrence. [1]",
    "citations": [{"paper_id": 1, "chunk_id": 1, "quoted_text": "Self-attention replaces recurrence."}],
    "critique_notes": [],
}


@patch("chat.views.run_query", return_value=FAKE_RESULT)
def test_post_message_creates_user_and_assistant_messages(mock_run_query, client_logged_in, workspace):
    response = client_logged_in.post(
        reverse("chat-message", args=[workspace.pk]), {"question": "What replaces recurrence?"}
    )

    assert response.status_code == 200
    messages = list(Message.objects.order_by("created_at"))
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "What replaces recurrence?"
    assert messages[1].content == FAKE_RESULT["draft_answer"]
    assert messages[1].citations == FAKE_RESULT["citations"]
    mock_run_query.assert_called_once_with(workspace_id=workspace.id, question="What replaces recurrence?")


@patch("chat.views.run_query", return_value=FAKE_RESULT)
def test_post_message_over_quota_skips_llm_call(mock_run_query, client_logged_in, workspace, settings):
    settings.DAILY_QUESTION_QUOTA = 1
    client_logged_in.post(reverse("chat-message", args=[workspace.pk]), {"question": "first"})
    client_logged_in.post(reverse("chat-message", args=[workspace.pk]), {"question": "second"})

    assert mock_run_query.call_count == 1
    last_assistant = Message.objects.filter(role="assistant").order_by("-created_at").first()
    assert "quota" in last_assistant.content.lower()


@patch("chat.views.run_query", side_effect=RuntimeError("No LLM API key configured"))
def test_post_message_degrades_gracefully_when_llm_call_fails(mock_run_query, client_logged_in, workspace):
    response = client_logged_in.post(
        reverse("chat-message", args=[workspace.pk]), {"question": "What replaces recurrence?"}
    )

    assert response.status_code == 200
    messages = list(Message.objects.order_by("created_at"))
    assert [m.role for m in messages] == ["user", "assistant"]
    assert "couldn't generate an answer" in messages[1].content.lower()

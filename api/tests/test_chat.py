import json
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from agent.llm.errors import LLMNotConfigured, LLMUnavailable
from agent.query_graph import QueryFailed
from api.chat import _answer_stream, build_history
from chat.models import Conversation, Message
from papers.models import Paper
from usage.models import UsageRecord

SOURCE = {
    "paper_id": 1, "chunk_id": 1, "paper_title": "Attention", "arxiv_id": "1706.03762", "text": "...", "score": 0.9,
}
FINAL_STATE = {
    "draft_answer": "Self-attention replaces recurrence. [1]",
    "citations": [{"paper_id": 1, "chunk_id": 1, "quoted_text": "Self-attention replaces recurrence."}],
    "critique_notes": [],
    "retrieved_chunks": [SOURCE],
    "search_query": "what replaces recurrence",
    "retries": 0,
    "timings": {"retrieve": 0.1},
    "tokens_used": 120,
}


def fake_stream(*args, **kwargs):
    yield "stage", {"stage": "retrieve", "attempt": 1}
    yield "stage", {"stage": "synthesize", "attempt": 1}
    yield "done", FINAL_STATE


@pytest.fixture
def conversation(workspace):
    Paper.objects.create(workspace=workspace, arxiv_id="1", title="Attention", pdf_url="https://x", status="ready")
    return Conversation.objects.create(workspace=workspace)


def post(api, conversation, question="What replaces recurrence?"):
    response = api.post(f"/api/conversations/{conversation.id}/messages/", {"question": question}, format="json")
    assert response.status_code == 200, getattr(response, "content", b"")
    return [json.loads(line) for line in b"".join(response.streaming_content).splitlines()]


@patch("api.chat.stream_query", side_effect=fake_stream)
def test_streams_user_stages_then_answer_and_persists_both(_stream, api, conversation):
    events = post(api, conversation)

    assert [e["type"] for e in events] == ["user", "stage", "stage", "message"]
    answer = events[-1]["message"]
    assert answer["content"] == FINAL_STATE["draft_answer"]
    assert answer["sources"][0]["n"] == 1
    assert answer["sources"][0]["paper_title"] == "Attention"
    assert answer["diagnostics"]["search_query"] == "what replaces recurrence"
    assert [m.role for m in Message.objects.order_by("id")] == ["user", "assistant"]


@patch("api.chat.stream_query", side_effect=fake_stream)
def test_first_question_becomes_the_conversation_title(_stream, api, conversation):
    events = post(api, conversation, "  What   replaces recurrence?  ")

    conversation.refresh_from_db()
    assert conversation.title == "What replaces recurrence?"
    assert events[-1]["conversation"]["title"] == "What replaces recurrence?"


@patch("api.chat.stream_query", side_effect=fake_stream)
def test_earlier_turns_are_passed_to_the_graph_as_history(stream, api, conversation):
    post(api, conversation, "First question?")
    post(api, conversation, "And the follow up?")

    history = stream.call_args.args[2]
    assert history == [
        {"role": "user", "content": "First question?"},
        {"role": "assistant", "content": "Self-attention replaces recurrence."},  # [1] tag stripped
    ]


def test_failed_turns_are_left_out_of_history(conversation):
    Message.objects.create(conversation=conversation, role="user", content="broken?")
    Message.objects.create(
        conversation=conversation, role="assistant", content="err", diagnostics={"error": {"code": "x"}}
    )
    Message.objects.create(conversation=conversation, role="user", content="works?")
    Message.objects.create(conversation=conversation, role="assistant", content="Yes. [2][3]")

    assert build_history(conversation) == [
        {"role": "user", "content": "works?"},
        {"role": "assistant", "content": "Yes."},
    ]


def test_history_is_limited_to_the_most_recent_turns(conversation, settings):
    settings.RAG_HISTORY_MESSAGES = 2
    for i in range(3):
        Message.objects.create(conversation=conversation, role="user", content=f"q{i}")
        Message.objects.create(conversation=conversation, role="assistant", content=f"a{i}")

    assert [t["content"] for t in build_history(conversation)] == ["q2", "a2"]


def test_conversation_reload_returns_all_messages(api, conversation):
    Message.objects.create(conversation=conversation, role="user", content="hi")
    Message.objects.create(conversation=conversation, role="assistant", content="hello")

    data = api.get(f"/api/conversations/{conversation.id}/").json()

    assert [m["content"] for m in data["messages"]] == ["hi", "hello"]


def test_empty_question_is_rejected(api, conversation):
    response = api.post(f"/api/conversations/{conversation.id}/messages/", {"question": "  "}, format="json")

    assert response.status_code == 400
    assert not Message.objects.exists()


def test_no_papers_is_diagnosed_without_running_the_graph(api, workspace):
    conversation = Conversation.objects.create(workspace=workspace)

    with patch("api.chat.stream_query") as stream:
        events = post(api, conversation)

    stream.assert_not_called()
    error = events[-1]["message"]["diagnostics"]["error"]
    assert error["code"] == "no_papers"
    assert error["request_id"]
    assert not UsageRecord.objects.exists()  # a refused question doesn't use up quota


def test_pending_papers_are_diagnosed(api, workspace):
    Paper.objects.create(workspace=workspace, arxiv_id="1", title="x", pdf_url="https://x")
    conversation = Conversation.objects.create(workspace=workspace)

    events = post(api, conversation)

    assert events[-1]["message"]["diagnostics"]["error"]["code"] == "papers_processing"


@patch("api.chat.stream_query", side_effect=fake_stream)
def test_quota_exceeded_is_diagnosed_and_skips_the_graph(stream, api, conversation, settings):
    settings.DAILY_QUESTION_QUOTA = 1
    post(api, conversation, "first")
    stream.reset_mock()

    events = post(api, conversation, "second")

    stream.assert_not_called()
    assert events[-1]["message"]["diagnostics"]["error"]["code"] == "quota_exceeded"


def failing_stream(exc, stage):
    def stream(*args, **kwargs):
        yield "stage", {"stage": stage, "attempt": 1}
        raise QueryFailed(stage, exc)

    return stream


@pytest.mark.parametrize(
    "exc, stage, code",
    [
        (LLMNotConfigured("no key"), "synthesize", "llm_not_configured"),
        (LLMUnavailable([("GeminiClient", "429 RESOURCE_EXHAUSTED")]), "synthesize", "llm_rate_limited"),
        (LLMUnavailable([("GroqClient", "401 invalid api key")]), "critique", "llm_auth_failed"),
        (OSError("model not downloaded"), "retrieve", "embedding_failed"),
        (RuntimeError("bug"), "critique", "internal_error"),
    ],
)
def test_failures_become_diagnosed_chat_messages(exc, stage, code, api, conversation):
    with patch("api.chat.stream_query", side_effect=failing_stream(exc, stage)):
        events = post(api, conversation)

    message = events[-1]["message"]
    error = message["diagnostics"]["error"]
    assert (error["code"], error["stage"]) == (code, stage)
    assert error["hint"] and error["request_id"]
    assert message["content"] == error["message"]
    assert Message.objects.filter(role="assistant", diagnostics__has_key="error").count() == 1


def test_error_detail_is_only_exposed_in_debug(api, conversation, settings):
    settings.DEBUG = False
    with patch("api.chat.stream_query", side_effect=failing_stream(RuntimeError("secret internals"), "critique")):
        events = post(api, conversation)

    assert "detail" not in events[-1]["message"]["diagnostics"]["error"]


def test_closing_the_stream_early_records_an_interrupted_turn(conversation, user):
    question = Message.objects.create(conversation=conversation, role="user", content="q")

    with patch("api.chat.stream_query", side_effect=fake_stream):
        stream = _answer_stream(conversation, question, [], user, "abc12345")
        next(stream)  # the "user" event, then the client disconnects
        stream.close()

    last = Message.objects.order_by("id").last()
    assert last.role == "assistant"
    assert last.diagnostics["error"]["code"] == "interrupted"


def test_cannot_touch_someone_elses_conversation(conversation, db):
    intruder = APIClient()
    intruder.force_login(User.objects.create_user(username="eve", password="x"))

    assert intruder.get(f"/api/conversations/{conversation.id}/").status_code == 404
    assert intruder.post(f"/api/conversations/{conversation.id}/messages/", {"question": "hi"}, format="json").status_code == 404
    assert intruder.delete(f"/api/conversations/{conversation.id}/").status_code == 404


def test_rename_and_delete_conversation(api, workspace):
    created = api.post(f"/api/workspaces/{workspace.id}/conversations/").json()

    renamed = api.patch(f"/api/conversations/{created['id']}/", {"title": "Renamed"}, format="json").json()
    assert renamed["conversation"]["title"] == "Renamed"
    assert api.delete(f"/api/conversations/{created['id']}/").status_code == 204
    assert not Conversation.objects.exists()


def test_conversations_list_most_recently_active_first(api, workspace):
    old = Conversation.objects.create(workspace=workspace, title="old")
    new = Conversation.objects.create(workspace=workspace, title="new")
    old.save()  # touching it makes it the most recent

    titles = [c["title"] for c in api.get(f"/api/workspaces/{workspace.id}/conversations/").json()]

    assert titles == ["old", "new"]
    assert new.id != old.id


def test_messages_are_paged_newest_first_with_load_earlier(api, conversation):
    for i in range(5):
        Message.objects.create(conversation=conversation, role="user", content=f"m{i}")
    url = f"/api/conversations/{conversation.id}/"

    latest = api.get(url, {"limit": 2}).json()
    assert [m["content"] for m in latest["messages"]] == ["m3", "m4"]
    assert latest["has_more"] is True

    earlier = api.get(url, {"limit": 2, "before": latest["messages"][0]["id"]}).json()
    assert [m["content"] for m in earlier["messages"]] == ["m1", "m2"]

    oldest = api.get(url, {"limit": 2, "before": earlier["messages"][0]["id"]}).json()
    assert [m["content"] for m in oldest["messages"]] == ["m0"]
    assert oldest["has_more"] is False


def test_bad_paging_params_are_a_validation_error(api, conversation):
    response = api.get(f"/api/conversations/{conversation.id}/", {"limit": "lots"})

    assert response.status_code == 400

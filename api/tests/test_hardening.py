import json
import logging
import subprocess
import sys
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from agent.llm.errors import LLMNotConfigured
from agent.query_graph import QueryFailed
from chat.models import Conversation
from config.jsonlog import JsonFormatter
from config.middleware import ContentSecurityPolicyMiddleware
from papers.models import Paper
from papers.tasks import fail_stuck_papers
from usage.models import UsageRecord

from .test_chat import fake_stream, post


def test_login_is_throttled_per_ip(db):
    client = APIClient()
    statuses = [client.post("/api/auth/login/", {"username": "x", "password": "y"}).status_code for _ in range(11)]

    assert statuses[:10] == [400] * 10
    assert statuses[10] == 429


def test_registration_can_be_closed(db, settings):
    settings.ALLOW_REGISTRATION = False

    response = APIClient().post("/api/auth/register/", {"username": "bob", "password": "a-strong-pass-9"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "registration_closed"


def test_paper_search_is_throttled_per_user(api, workspace, settings):
    url = f"/api/workspaces/{workspace.id}/papers/search/"
    with patch("api.papers.arxiv_client.search", return_value=[]):
        statuses = [api.post(url, {"query": "attention"}).status_code for _ in range(21)]

    assert statuses[-1] == 429


@pytest.fixture
def conversation(workspace):
    Paper.objects.create(workspace=workspace, arxiv_id="1", title="A", pdf_url="https://x", status="ready")
    return Conversation.objects.create(workspace=workspace)


def _requests_made(user):
    return UsageRecord.objects.get(user=user).requests_made


def _failing(exc):
    def stream(*args, **kwargs):
        yield "stage", {"stage": "synthesize", "attempt": 1}
        raise QueryFailed("synthesize", exc)

    return stream


def test_provider_failure_refunds_the_quota(api, conversation, user):
    with patch("api.chat.stream_query", side_effect=_failing(LLMNotConfigured("no key"))):
        post(api, conversation)

    assert _requests_made(user) == 0


def test_successful_answer_uses_quota_and_records_tokens(api, conversation, user):
    with patch("api.chat.stream_query", side_effect=fake_stream):
        events = post(api, conversation)

    record = UsageRecord.objects.get(user=user)
    assert (record.requests_made, record.tokens_used) == (1, 120)
    assert events[-1]["message"]["diagnostics"]["tokens"] == 120


def test_healthz_needs_no_login(db):
    response = APIClient().get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_csp_middleware_protects_the_app_but_not_the_admin():
    middleware = ContentSecurityPolicyMiddleware(lambda request: __import__("django.http").http.HttpResponse())
    factory = RequestFactory()

    app = middleware(factory.get("/w/1/chat"))
    admin = middleware(factory.get("/admin/login/"))

    assert "script-src 'self'" in app.headers["Content-Security-Policy"]
    assert "Content-Security-Policy" not in admin.headers


def test_spa_index_is_never_cached(client, settings, tmp_path):
    (tmp_path / "index.html").write_text("<html></html>")
    settings.FRONTEND_DIST = tmp_path

    response = client.get("/w/1/chat")

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-cache"


def _import_settings(**env):
    return subprocess.run(
        [sys.executable, "-c", "import django.conf, config.settings"],
        env={"PATH": "", "DJANGO_SETTINGS_MODULE": "config.settings", **env},
        capture_output=True,
        text=True,
    )


def test_production_refuses_to_start_with_the_placeholder_secret():
    result = _import_settings(DJANGO_DEBUG="false", DJANGO_SECRET_KEY="change-me-in-production")

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_production_starts_with_a_real_secret_and_turns_on_secure_cookies():
    probe = "import config.settings as s; print(s.SESSION_COOKIE_SECURE, s.SECURE_HSTS_SECONDS > 0, s.DEBUG)"
    result = subprocess.run(
        [sys.executable, "-c", probe],
        env={"PATH": "", "DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY": "a-real-secret-" * 4},
        capture_output=True,
        text=True,
    )

    assert result.stdout.split() == ["True", "True", "False"]


def test_sweep_fails_only_papers_stuck_in_pending(workspace):
    old = timezone.now() - timedelta(hours=1)
    stuck = Paper.objects.create(workspace=workspace, arxiv_id="1", title="a", pdf_url="https://x", queued_at=old)
    fresh = Paper.objects.create(workspace=workspace, arxiv_id="2", title="b", pdf_url="https://x")
    done = Paper.objects.create(
        workspace=workspace, arxiv_id="3", title="c", pdf_url="https://x", status="ready", queued_at=old
    )

    assert fail_stuck_papers() == 1

    for paper in (stuck, fresh, done):
        paper.refresh_from_db()
    assert (stuck.status, fresh.status, done.status) == ("failed", "pending", "ready")
    assert "Retry" in stuck.failure_reason


def test_every_response_carries_a_request_id_that_the_error_reference_reuses(api, conversation):
    with patch("api.chat.stream_query", side_effect=_failing(LLMNotConfigured("no key"))):
        response = api.post(f"/api/conversations/{conversation.id}/messages/", {"question": "q"}, format="json")
        events = [json.loads(line) for line in b"".join(response.streaming_content).splitlines()]

    request_id = response["X-Request-ID"]
    assert len(request_id) == 8
    assert events[-1]["message"]["diagnostics"]["error"]["request_id"] == request_id


def test_request_ids_differ_between_requests(db):
    client = APIClient()

    assert client.get("/healthz")["X-Request-ID"] != client.get("/healthz")["X-Request-ID"]


def test_json_formatter_emits_parseable_lines_with_the_request_id():
    record = logging.LogRecord("api", logging.ERROR, __file__, 1, "boom %s", ("now",), None)
    record.request_id = "abc12345"

    entry = json.loads(JsonFormatter().format(record))

    assert (entry["message"], entry["request_id"], entry["level"]) == ("boom now", "abc12345", "ERROR")

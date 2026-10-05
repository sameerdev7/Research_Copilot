from unittest.mock import patch

from django.db import OperationalError

from agent.llm.errors import LLMUnavailable
from agent.query_graph import QueryFailed
from api import health
from api.diagnostics import CopilotError, diagnose


def test_query_failed_is_unwrapped_and_keeps_its_stage():
    cause = LLMUnavailable([("GeminiClient", "404 model not found")])

    diagnosis = diagnose(QueryFailed("synthesize", cause))

    assert (diagnosis.code, diagnosis.stage) == ("llm_model_unavailable", "synthesize")
    assert "GEMINI_MODEL" in diagnosis.hint


def test_database_errors_point_at_postgres():
    assert diagnose(OperationalError("connection refused")).code == "database_error"


def test_copilot_errors_pass_through_unchanged():
    diagnosis = diagnose(CopilotError("no_papers", "No papers", "Add some"))

    assert (diagnosis.code, diagnosis.message, diagnosis.hint) == ("no_papers", "No papers", "Add some")


def test_unhandled_view_exceptions_return_a_logged_500_with_request_id(api, workspace):
    with patch("api.papers.owned_workspace", side_effect=RuntimeError("kaboom")):
        api.raise_request_exception = False
        response = api.get(f"/api/workspaces/{workspace.id}/papers/")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert len(error["request_id"]) == 8


def test_health_rolls_up_the_worst_check(api):
    ok = {"name": "x", "status": "ok", "message": "", "hint": ""}
    bad = {"name": "Worker", "status": "error", "message": "none", "hint": "start it"}
    with (
        patch.object(health, "_check_redis", return_value=ok),
        patch.object(health, "_check_worker", return_value=bad),
        patch.object(health, "_check_embeddings", return_value=ok),
        patch.object(health, "_check_llm", return_value=ok),
    ):
        data = api.get("/api/health/").json()

    assert data["status"] == "error"
    assert [c["name"] for c in data["checks"]][:1] == ["Database"]
    assert data["checks"][0]["status"] == "ok"  # the real test database is reachable


def test_health_skips_the_worker_check_when_redis_is_down(api):
    down = {"name": "Redis", "status": "error", "message": "no", "hint": "start"}
    with (
        patch.object(health, "_check_redis", return_value=down),
        patch.object(health, "_check_worker") as worker,
    ):
        api.get("/api/health/")

    worker.assert_not_called()


def test_llm_check_distinguishes_missing_one_and_two_keys(settings):
    assert health._check_llm()["status"] == "error"
    settings.GROQ_API_KEY = "k"
    assert health._check_llm()["status"] == "warn"
    settings.GEMINI_API_KEY = "k"
    assert health._check_llm()["status"] == "ok"

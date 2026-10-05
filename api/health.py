from __future__ import annotations

import logging

import redis
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from agent import embeddings
from config.celery import app as celery_app

logger = logging.getLogger(__name__)

OK, WARN, ERROR = "ok", "warn", "error"


def _check(name: str, status: str, message: str, hint: str = "") -> dict:
    return {"name": name, "status": status, "message": message, "hint": hint}


def _check_database() -> dict:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            has_vector = cursor.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        return _check("Database", ERROR, f"Can't reach Postgres: {exc}", "Run `docker compose up -d postgres`.")
    if not has_vector:
        return _check("Database", ERROR, "The pgvector extension is missing.", "Run `manage.py migrate`.")
    return _check("Database", OK, "Postgres and pgvector are ready.")


def _check_redis() -> dict:
    try:
        redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=1, socket_timeout=1).ping()
    except Exception as exc:  # noqa: BLE001
        return _check(
            "Redis",
            ERROR,
            f"Can't reach Redis: {exc}",
            "Start Redis (`docker compose up -d redis`). Paper ingestion needs it.",
        )
    return _check("Redis", OK, "Broker is reachable.")


def _check_worker() -> dict:
    if settings.CELERY_TASK_ALWAYS_EAGER:
        return _check("Worker", OK, "Tasks run inline (CELERY_TASK_ALWAYS_EAGER).")
    try:
        replies = celery_app.control.inspect(timeout=1).ping()
    except Exception as exc:  # noqa: BLE001
        return _check("Worker", ERROR, f"Couldn't query workers: {exc}")
    if not replies:
        return _check(
            "Worker",
            ERROR,
            "No Celery worker is responding.",
            "Run `uv run celery -A config worker --loglevel=info`. Papers stay pending without it.",
        )
    return _check("Worker", OK, f"{len(replies)} worker(s) online.")


def _check_embeddings() -> dict:
    if embeddings.is_loaded():
        return _check("Embeddings", OK, f"{settings.EMBEDDING_MODEL_NAME} is loaded.")
    return _check(
        "Embeddings",
        OK,
        f"{settings.EMBEDDING_MODEL_NAME} loads on first use.",
        "The very first question or ingestion needs internet access to download it.",
    )


def _check_llm() -> dict:
    if settings.LLM_PROVIDER == "demo":
        return _check("LLM", WARN, "Demo mode: answers are canned, no provider is called.")
    providers = []
    if settings.GEMINI_API_KEY:
        providers.append(f"Gemini ({settings.GEMINI_MODEL})")
    if settings.GROQ_API_KEY:
        providers.append(f"Groq ({settings.GROQ_MODEL})")
    if not providers:
        return _check(
            "LLM", ERROR, "No API key configured.", "Set GEMINI_API_KEY or GROQ_API_KEY in .env, then restart."
        )
    message = " then ".join(providers) + " (keys are set, not tested)"
    return _check("LLM", OK if len(providers) > 1 else WARN, message, "" if len(providers) > 1 else "Only one provider is configured, so there's no fallback.")


# liveness for the proxy and orchestrator: process is up and the database answers
def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})


@api_view(["GET"])
def health(request):
    checks = [_check_database(), _check_redis()]
    if checks[1]["status"] == OK:
        checks.append(_check_worker())
    checks += [_check_embeddings(), _check_llm()]

    statuses = {c["status"] for c in checks}
    overall = ERROR if ERROR in statuses else WARN if WARN in statuses else OK
    return Response({"status": overall, "checks": checks})

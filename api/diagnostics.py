from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass

from django.conf import settings
from django.db import Error as DatabaseError

from agent.llm.errors import LLMNotConfigured, LLMUnavailable
from agent.query_graph import QueryFailed
from config.middleware import request_id_var

logger = logging.getLogger(__name__)


# an expected failure with a ready-made diagnosis
class CopilotError(Exception):
    def __init__(self, code: str, message: str, hint: str = "", status: int = 400):
        super().__init__(message)
        self.code, self.message, self.hint, self.status = code, message, hint, status


@dataclass
class Diagnosis:
    code: str
    message: str
    hint: str = ""
    stage: str = ""
    request_id: str = ""
    detail: str = ""  # raw error text, only exposed in DEBUG

    def as_dict(self) -> dict:
        data = asdict(self)
        if not settings.DEBUG:
            data.pop("detail")
        return data


# reuse the current request's id so the error reference matches the logs
def new_request_id() -> str:
    current = request_id_var.get()
    return current if current != "-" else uuid.uuid4().hex[:8]


def _llm_hint(error_text: str) -> tuple[str, str]:
    text = error_text.lower()
    if any(s in text for s in ("429", "rate limit", "rate_limit", "quota", "resource_exhausted")):
        return "llm_rate_limited", "Both providers are rate-limited. Wait a minute and try again."
    if any(s in text for s in ("401", "403", "api key", "api_key", "permission", "unauthorized")):
        return "llm_auth_failed", "An API key was rejected. Check GEMINI_API_KEY / GROQ_API_KEY in .env."
    if any(s in text for s in ("404", "not found")):
        return "llm_model_unavailable", (
            "The model name may have been retired. Check GEMINI_MODEL / GROQ_MODEL in .env."
        )
    if any(s in text for s in ("timeout", "timed out", "connection", "network", "resolve")):
        return "llm_network_error", "The LLM providers couldn't be reached. Check your internet connection."
    return "llm_unavailable", "Check the server log for the provider errors."


# classify an exception into a code, message and hint
def diagnose(exc: Exception, stage: str = "") -> Diagnosis:
    if isinstance(exc, QueryFailed):
        stage, exc = exc.stage, exc.cause

    detail = f"{type(exc).__name__}: {exc}"

    if isinstance(exc, CopilotError):
        return Diagnosis(exc.code, exc.message, exc.hint, stage)
    if isinstance(exc, LLMNotConfigured):
        return Diagnosis(
            "llm_not_configured",
            "No LLM API key is configured.",
            "Set GEMINI_API_KEY or GROQ_API_KEY in .env and restart the server.",
            stage,
            detail=detail,
        )
    if isinstance(exc, LLMUnavailable):
        code, hint = _llm_hint(str(exc))
        return Diagnosis(code, "The language model couldn't answer.", hint, stage, detail=detail)
    if isinstance(exc, DatabaseError):
        return Diagnosis(
            "database_error",
            "The database isn't responding.",
            "Is Postgres running? Try `docker compose up -d postgres`.",
            stage,
            detail=detail,
        )
    if stage == "retrieve":
        return Diagnosis(
            "embedding_failed",
            "Searching your papers failed.",
            "The embedding model may not be downloaded yet - the first run needs internet access.",
            stage,
            detail=detail,
        )
    return Diagnosis(
        "internal_error", "Something went wrong while answering.", "See the server log for details.", stage,
        detail=detail,
    )

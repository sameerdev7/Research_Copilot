import logging

from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .diagnostics import CopilotError, diagnose, new_request_id

logger = logging.getLogger(__name__)


def _first_message(detail) -> str:
    if isinstance(detail, dict):
        key, value = next(iter(detail.items()))
        message = _first_message(value)
        return message if key in ("detail", "non_field_errors") else f"{key}: {message}"
    if isinstance(detail, list):
        return _first_message(detail[0]) if detail else ""
    return str(detail)


def api_exception_handler(exc, context):
    if isinstance(exc, CopilotError):
        error = {"code": exc.code, "message": exc.message, "hint": exc.hint}
        return Response({"error": error}, status=exc.status)

    response = exception_handler(exc, context)
    if response is not None:
        code = "validation_error" if isinstance(exc, ValidationError) else getattr(exc, "default_code", "error")
        response.data = {"error": {"code": code, "message": _first_message(response.data)}}
        return response

    request_id = new_request_id()
    view = context["view"].__class__.__name__
    logger.exception("unhandled error in %s request_id=%s", view, request_id)
    diagnosis = diagnose(exc)
    diagnosis.request_id = request_id
    return Response({"error": diagnosis.as_dict()}, status=500)

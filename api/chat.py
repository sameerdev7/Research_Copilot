import json
import logging
import re

from django.conf import settings
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from agent.query_graph import stream_query
from agent.state import Turn
from chat.models import Conversation, Message
from usage.quotas import QuotaExceeded, check_and_increment, record_tokens, refund

from .diagnostics import CopilotError, Diagnosis, diagnose, new_request_id
from .serializers import ConversationSerializer, MessageSerializer
from .throttles import QuestionThrottle
from .workspaces import owned_workspace

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 2000
MAX_HISTORY_CHARS = 1200
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_CONVERSATIONS = 200
TITLE_CHARS = 60
REFUNDABLE_PREFIXES = ("llm_", "database_error", "embedding_failed", "internal_error")
EXPECTED_REFUSALS = {"quota_exceeded", "no_papers", "papers_processing", "interrupted"}
CITATION_TAGS_RE = re.compile(r"\s*(?:\[\d+\])+\s*$", re.MULTILINE)


def _owned_conversation(request, conversation_id: int) -> Conversation:
    return get_object_or_404(Conversation, pk=conversation_id, workspace__user=request.user)


@api_view(["GET", "POST"])
def conversation_list(request, workspace_id):
    workspace = owned_workspace(request, workspace_id)
    if request.method == "POST":
        conversation = Conversation.objects.create(workspace=workspace)
        return Response(ConversationSerializer(conversation).data, status=201)
    return Response(ConversationSerializer(workspace.conversations.all()[:MAX_CONVERSATIONS], many=True).data)


# newest `limit` messages (older than `before`, if given), oldest first, plus whether more exist
def _message_page(conversation: Conversation, params) -> tuple[list[Message], bool]:
    try:
        limit = min(int(params.get("limit", DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
        before = int(params["before"]) if "before" in params else None
    except ValueError as exc:
        raise ValidationError({"detail": "limit and before must be integers"}) from exc
    queryset = conversation.messages.order_by("-id")
    if before is not None:
        queryset = queryset.filter(id__lt=before)
    page = list(queryset[: limit + 1])
    return page[:limit][::-1], len(page) > limit


@api_view(["GET", "PATCH", "DELETE"])
def conversation_detail(request, conversation_id):
    conversation = _owned_conversation(request, conversation_id)
    if request.method == "DELETE":
        conversation.delete()
        return Response(status=204)

    if request.method == "PATCH":
        serializer = ConversationSerializer(conversation, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

    messages, has_more = _message_page(conversation, request.query_params)
    return Response(
        {
            "conversation": ConversationSerializer(conversation).data,
            "messages": MessageSerializer(messages, many=True).data,
            "has_more": has_more,
        }
    )


# recent answered question/answer pairs, oldest first
def build_history(conversation: Conversation) -> list[Turn]:
    turns: list[Turn] = []
    pending_question: Message | None = None
    # only the tail of the conversation can matter for history
    recent = list(conversation.messages.order_by("-id")[: settings.RAG_HISTORY_MESSAGES * 4])
    for message in reversed(recent):
        if message.role == "user":
            pending_question = message
        elif pending_question is not None and "error" not in message.diagnostics:
            answer = " ".join(CITATION_TAGS_RE.sub("", message.content).split())
            turns.append({"role": "user", "content": pending_question.content[:MAX_HISTORY_CHARS]})
            turns.append({"role": "assistant", "content": answer[:MAX_HISTORY_CHARS]})
            pending_question = None
    return turns[-settings.RAG_HISTORY_MESSAGES :]


def _precheck(workspace) -> None:
    papers = workspace.papers
    if papers.filter(status="ready").exists():
        return
    if papers.filter(status="pending").exists():
        raise CopilotError(
            "papers_processing",
            "Your papers are still being processed.",
            "Wait for them to become ready. If they stay pending, the Celery worker may not be running.",
        )
    raise CopilotError("no_papers", "This workspace has no papers yet.", "Add some on the Papers tab first.")


def _event(kind: str, **data) -> bytes:
    return (json.dumps({"type": kind, **data}) + "\n").encode()


def _save_assistant_message(conversation: Conversation, content: str, **fields) -> Message:
    message = Message.objects.create(conversation=conversation, role="assistant", content=content, **fields)
    conversation.save(update_fields=["updated_at"])
    return message


def _diagnose_and_log(exc: Exception, request_id: str, workspace_id: int) -> Diagnosis:
    diagnosis = diagnose(exc)
    diagnosis.request_id = request_id
    if diagnosis.code in EXPECTED_REFUSALS:
        logger.info("answer refused request_id=%s code=%s", request_id, diagnosis.code)
    else:
        logger.error(
            "answer failed request_id=%s code=%s stage=%s workspace=%s",
            request_id, diagnosis.code, diagnosis.stage, workspace_id, exc_info=exc,
        )
    return diagnosis


def _save_failure(conversation: Conversation, diagnosis: Diagnosis) -> Message:
    error = diagnosis.as_dict()
    return _save_assistant_message(conversation, error["message"], diagnostics={"error": error})


# yields NDJSON events: user, stages, then the final message
def _answer_stream(
    conversation: Conversation, user_message: Message, history: list[Turn], user, request_id: str
):
    workspace = conversation.workspace
    finished = False
    counted = False
    try:
        yield _event(
            "user",
            message=MessageSerializer(user_message).data,
            conversation=ConversationSerializer(conversation).data,
        )
        try:
            _precheck(workspace)
            try:
                check_and_increment(user)
            except QuotaExceeded as exc:
                raise CopilotError(
                    "quota_exceeded", str(exc), "Your daily limit resets tomorrow.", status=429
                ) from exc
            counted = True

            state = {}
            for kind, payload in stream_query(workspace.id, user_message.content, history):
                if kind == "stage":
                    yield _event("stage", **payload)
                else:
                    state = payload

            record_tokens(user, state["tokens_used"])
            sources = [{"n": i, **chunk} for i, chunk in enumerate(state["retrieved_chunks"], start=1)]
            assistant = _save_assistant_message(
                conversation,
                state["draft_answer"] or "",
                citations=state["citations"],
                critique_notes=state["critique_notes"],
                sources=sources,
                diagnostics={
                    "request_id": request_id,
                    "search_query": state["search_query"],
                    "retries": state["retries"],
                    "timings": state["timings"],
                    "tokens": state["tokens_used"],
                },
            )
            logger.info(
                "answer ok request_id=%s retries=%s timings=%s",
                request_id, state["retries"], state["timings"],
            )
        except Exception as exc:  # noqa: BLE001 - every failure becomes a diagnosed chat message
            diagnosis = _diagnose_and_log(exc, request_id, workspace.id)
            if counted and diagnosis.code.startswith(REFUNDABLE_PREFIXES):
                refund(user)
            try:
                assistant = _save_failure(conversation, diagnosis)
            except Exception:  # noqa: BLE001 - e.g. the database itself is down
                logger.exception("could not store failure request_id=%s", request_id)
                finished = True
                yield _event("error", error=diagnosis.as_dict())
                return

        finished = True
        yield _event(
            "message",
            message=MessageSerializer(assistant).data,
            conversation=ConversationSerializer(conversation).data,
        )
    finally:
        if not finished:  # the client went away mid-answer
            interrupted = CopilotError("interrupted", "The request was interrupted before it finished.")
            _save_failure(conversation, _diagnose_and_log(interrupted, request_id, workspace.id))


@api_view(["POST"])
@throttle_classes([QuestionThrottle])
def post_message(request, conversation_id):
    conversation = _owned_conversation(request, conversation_id)
    question = str(request.data.get("question", "")).strip()
    if not question:
        raise ValidationError({"question": "Type a question first."})
    if len(question) > MAX_QUESTION_CHARS:
        raise ValidationError({"question": f"Keep questions under {MAX_QUESTION_CHARS} characters."})

    history = build_history(conversation)
    user_message = Message.objects.create(conversation=conversation, role="user", content=question)
    if not conversation.title:
        conversation.title = " ".join(question.split())[:TITLE_CHARS]
    conversation.save(update_fields=["title", "updated_at"])

    stream = _answer_stream(conversation, user_message, history, request.user, new_request_id())
    response = StreamingHttpResponse(stream, content_type="application/x-ndjson")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # keep nginx from buffering the stream
    return response

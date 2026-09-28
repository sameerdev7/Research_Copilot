import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render

from agent.query_graph import run_query
from usage.quotas import QuotaExceeded, check_and_increment
from workspaces.models import Workspace

from .models import Conversation, Message

logger = logging.getLogger(__name__)


def _get_owned_workspace(request, workspace_id):
    workspace = get_object_or_404(Workspace, pk=workspace_id)
    if workspace.user_id != request.user.id:
        return None
    return workspace


def _get_or_create_conversation(workspace):
    conversation = workspace.conversations.first()
    if conversation is None:
        conversation = Conversation.objects.create(workspace=workspace)
    return conversation


@login_required
def conversation_view(request, workspace_id):
    workspace = _get_owned_workspace(request, workspace_id)
    if workspace is None:
        return HttpResponseForbidden()
    conversation = _get_or_create_conversation(workspace)
    return render(
        request,
        "chat/conversation.html",
        {"workspace": workspace, "conversation": conversation, "chat_messages": conversation.messages.all()},
    )


@login_required
def post_message(request, workspace_id):
    workspace = _get_owned_workspace(request, workspace_id)
    if workspace is None:
        return HttpResponseForbidden()

    question = request.POST.get("question", "").strip()
    conversation = _get_or_create_conversation(workspace)

    if not question:
        return render(request, "chat/_messages.html", {"chat_messages": conversation.messages.all()})

    user_message = Message.objects.create(conversation=conversation, role="user", content=question)

    try:
        check_and_increment(request.user)
    except QuotaExceeded as exc:
        Message.objects.create(conversation=conversation, role="assistant", content=str(exc))
        return render(
            request,
            "chat/_messages.html",
            {"chat_messages": conversation.messages.filter(id__gte=user_message.id)},
        )

    try:
        result = run_query(workspace_id=workspace.id, question=question)
    except Exception:
        # The LLM call is an external boundary (missing/invalid key, rate limit, network
        # error) - degrade to a chat message instead of a hard 500, like the quota case above.
        logger.exception("run_query failed for workspace_id=%s", workspace.id)
        Message.objects.create(
            conversation=conversation,
            role="assistant",
            content="Sorry, I couldn't generate an answer just now. Please try again shortly.",
        )
        return render(
            request,
            "chat/_messages.html",
            {"chat_messages": conversation.messages.filter(id__gte=user_message.id)},
        )

    Message.objects.create(
        conversation=conversation,
        role="assistant",
        content=result["draft_answer"] or "",
        citations=result["citations"],
        critique_notes=result["critique_notes"],
    )

    return render(
        request,
        "chat/_messages.html",
        {"chat_messages": conversation.messages.filter(id__gte=user_message.id)},
    )

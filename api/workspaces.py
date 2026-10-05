from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from workspaces.models import Workspace

from .serializers import WorkspaceSerializer


# 404 for other users' workspaces
def owned_workspace(request, workspace_id: int) -> Workspace:
    return get_object_or_404(Workspace, pk=workspace_id, user=request.user)


def _with_counts(queryset):
    return queryset.annotate(
        paper_count=Count("papers", distinct=True),
        ready_count=Count("papers", filter=Q(papers__status="ready"), distinct=True),
    )


@api_view(["GET", "POST"])
def workspace_list(request):
    if request.method == "POST":
        serializer = WorkspaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = serializer.save(user=request.user)
        workspace = _with_counts(Workspace.objects.filter(pk=workspace.pk)).get()
        return Response(WorkspaceSerializer(workspace).data, status=201)

    workspaces = _with_counts(Workspace.objects.filter(user=request.user))
    return Response(WorkspaceSerializer(workspaces, many=True).data)


@api_view(["DELETE"])
def workspace_detail(request, workspace_id):
    owned_workspace(request, workspace_id).delete()
    return Response(status=204)

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView

from .models import Workspace


class WorkspaceListView(LoginRequiredMixin, ListView):
    model = Workspace
    template_name = "workspaces/workspace_list.html"
    context_object_name = "workspaces"

    def get_queryset(self):
        return Workspace.objects.filter(user=self.request.user)


@login_required
def create_workspace(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if name:
            workspace = Workspace.objects.create(user=request.user, name=name)
            return redirect("workspace-detail", pk=workspace.pk)
    return redirect("workspace-list")


class WorkspaceDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = Workspace
    template_name = "workspaces/workspace_detail.html"
    context_object_name = "workspace"

    def test_func(self):
        workspace = self.get_object()
        return workspace.user_id == self.request.user.id

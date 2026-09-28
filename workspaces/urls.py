from django.urls import path

from . import views

urlpatterns = [
    path("", views.WorkspaceListView.as_view(), name="workspace-list"),
    path("workspaces/create/", views.create_workspace, name="workspace-create"),
    path("workspaces/<int:pk>/", views.WorkspaceDetailView.as_view(), name="workspace-detail"),
]

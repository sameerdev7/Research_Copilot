from django.urls import path

from . import views

urlpatterns = [
    path("workspaces/<int:workspace_id>/papers/", views.paper_list, name="paper-list"),
    path("workspaces/<int:workspace_id>/papers/search/", views.search_papers, name="paper-search"),
    path("workspaces/<int:workspace_id>/papers/ingest/", views.ingest_papers, name="paper-ingest"),
    path("workspaces/<int:workspace_id>/papers/status/", views.paper_status_partial, name="paper-status"),
]

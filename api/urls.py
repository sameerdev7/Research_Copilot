from django.urls import path

from . import auth, chat, health, papers, workspaces

urlpatterns = [
    path("auth/me/", auth.me),
    path("auth/login/", auth.login_view),
    path("auth/register/", auth.register),
    path("auth/logout/", auth.logout_view),
    path("health/", health.health),
    path("workspaces/", workspaces.workspace_list),
    path("workspaces/<int:workspace_id>/", workspaces.workspace_detail),
    path("workspaces/<int:workspace_id>/papers/", papers.paper_list),
    path("workspaces/<int:workspace_id>/papers/search/", papers.paper_search),
    path("workspaces/<int:workspace_id>/papers/ingest/", papers.paper_ingest),
    path("workspaces/<int:workspace_id>/papers/<int:paper_id>/", papers.paper_detail),
    path("workspaces/<int:workspace_id>/papers/<int:paper_id>/retry/", papers.paper_retry),
    path("workspaces/<int:workspace_id>/conversations/", chat.conversation_list),
    path("conversations/<int:conversation_id>/", chat.conversation_detail),
    path("conversations/<int:conversation_id>/messages/", chat.post_message),
]

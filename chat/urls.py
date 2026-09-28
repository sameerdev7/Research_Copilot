from django.urls import path

from . import views

urlpatterns = [
    path("workspaces/<int:workspace_id>/chat/", views.conversation_view, name="chat-conversation"),
    path("workspaces/<int:workspace_id>/chat/message/", views.post_message, name="chat-message"),
]

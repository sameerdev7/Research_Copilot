import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from workspaces.models import Workspace


@pytest.fixture
def user(db):
    return User.objects.create_user(username="alice", password="pw")


@pytest.fixture
def client_logged_in(client, user):
    client.force_login(user)
    return client


def test_workspace_list_requires_login(client):
    response = client.get(reverse("workspace-list"))
    assert response.status_code == 302


def test_create_and_list_workspace(client_logged_in):
    response = client_logged_in.post(reverse("workspace-create"), {"name": "My Research"})
    assert response.status_code == 302

    workspace = Workspace.objects.get(name="My Research")
    response = client_logged_in.get(reverse("workspace-list"))
    assert response.status_code == 200
    assert workspace.name.encode() in response.content


def test_cannot_view_another_users_workspace(client_logged_in, db):
    other_user = User.objects.create_user(username="bob", password="pw")
    other_workspace = Workspace.objects.create(user=other_user, name="Bob's workspace")

    response = client_logged_in.get(reverse("workspace-detail", args=[other_workspace.pk]))

    assert response.status_code == 403

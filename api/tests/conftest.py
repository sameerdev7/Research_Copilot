import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from workspaces.models import Workspace


@pytest.fixture
def user(db):
    return User.objects.create_user(username="alice", password="pw-for-tests-123")


@pytest.fixture
def workspace(user):
    return Workspace.objects.create(user=user, name="ws")


@pytest.fixture
def api(user):
    client = APIClient()
    client.force_login(user)
    return client

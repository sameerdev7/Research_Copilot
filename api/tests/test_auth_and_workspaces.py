from django.contrib.auth.models import User
from rest_framework.test import APIClient

from papers.models import Paper
from workspaces.models import Workspace


def test_me_is_anonymous_before_login_and_sets_csrf_cookie(db):
    client = APIClient()

    response = client.get("/api/auth/me/")

    assert response.json() == {"user": None}
    assert "csrftoken" in response.cookies


def test_login_logout_roundtrip(user):
    client = APIClient()

    assert client.post("/api/auth/login/", {"username": "alice", "password": "nope"}).status_code == 400
    response = client.post("/api/auth/login/", {"username": "alice", "password": "pw-for-tests-123"})
    assert response.json()["user"]["username"] == "alice"
    assert client.get("/api/auth/me/").json()["user"]["username"] == "alice"

    client.post("/api/auth/logout/")
    assert client.get("/api/auth/me/").json() == {"user": None}


def test_register_creates_and_logs_in(db):
    client = APIClient()

    response = client.post("/api/auth/register/", {"username": "bob", "password": "a-strong-pass-9"})

    assert response.status_code == 201
    assert User.objects.filter(username="bob").exists()
    assert client.get("/api/auth/me/").json()["user"]["username"] == "bob"


def test_register_rejects_taken_username_and_weak_password(user):
    client = APIClient()

    taken = client.post("/api/auth/register/", {"username": "ALICE", "password": "a-strong-pass-9"})
    weak = client.post("/api/auth/register/", {"username": "bob", "password": "123"})

    assert taken.json()["error"]["code"] == "username_taken"
    assert weak.json()["error"]["code"] == "weak_password"


def test_api_requires_login(db):
    response = APIClient().get("/api/workspaces/")

    assert response.status_code in (401, 403)
    assert response.json()["error"]["code"] == "not_authenticated"


def test_create_and_list_workspace_with_paper_counts(api, workspace):
    Paper.objects.create(workspace=workspace, arxiv_id="1", title="A", pdf_url="https://x", status="ready")
    Paper.objects.create(workspace=workspace, arxiv_id="2", title="B", pdf_url="https://x")

    created = api.post("/api/workspaces/", {"name": "New"})
    listed = api.get("/api/workspaces/").json()

    assert created.status_code == 201
    assert created.json()["paper_count"] == 0
    by_name = {w["name"]: w for w in listed}
    assert by_name["ws"]["paper_count"] == 2
    assert by_name["ws"]["ready_count"] == 1


def test_blank_workspace_name_is_a_readable_validation_error(api):
    response = api.post("/api/workspaces/", {"name": "  "})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert "name" in response.json()["error"]["message"]


def test_other_users_workspace_is_404(api, db):
    other = Workspace.objects.create(user=User.objects.create_user(username="bob", password="x"), name="b")

    assert api.get(f"/api/workspaces/{other.id}/papers/").status_code == 404
    assert api.delete(f"/api/workspaces/{other.id}/").status_code == 404
    assert Workspace.objects.filter(pk=other.id).exists()

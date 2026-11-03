"""The API's own rules: every route needs sign-in, and a user only ever sees their own chats and memory.

Sign-in itself is tested in test_auth.py, so here it's replaced with a simple stand-in that says who the user is.
"""

import pytest
from fastapi.testclient import TestClient

from agent.memory import LongTermMemory
from agent.storage import store
from api.auth import CurrentUser, current_user
from api.server import app


@pytest.fixture
def client_as(db):
    """Returns a function that gives an API client signed in as the named user."""
    def _client(user_id: str) -> TestClient:
        app.dependency_overrides[current_user] = lambda: CurrentUser(user_id=user_id, email=None)
        return TestClient(app)
    yield _client
    app.dependency_overrides.clear()


@pytest.mark.parametrize("method, path", [
    ("get", "/me"), ("get", "/me/memory"), ("get", "/me/checklist"), ("get", "/sessions"),
    ("delete", "/me"), ("post", "/chat"),
])
def test_routes_need_sign_in(db, method, path):
    response = getattr(TestClient(app), method)(path)
    assert response.status_code == 401


def test_me_shows_who_is_signed_in(client_as):
    assert client_as("ada").get("/me").json()["user_id"] == "ada"


def test_a_user_cannot_open_someone_elses_chat(client_as):
    store.touch_session("ada", "s-ada-chat", "graphrag", "Zobo in Ibadan")
    assert client_as("bola").get("/sessions/s-ada-chat/messages").status_code == 404
    assert client_as("ada").get("/sessions/s-ada-chat/messages").status_code == 200


def test_unsafe_chat_ids_are_refused(client_as):
    assert client_as("ada").get("/sessions/..%5C..%5Cetc/messages").status_code in (400, 404)


def test_memory_shows_only_the_signed_in_users_businesses(client_as):
    LongTermMemory.add_business("ada", "zobo business")
    assert [b["label"] for b in client_as("ada").get("/me/memory").json()["businesses"]] == ["zobo business"]
    assert client_as("bola").get("/me/memory").json()["businesses"] == []


def test_a_user_cannot_delete_someone_elses_business(client_as):
    zobo = LongTermMemory.add_business("ada", "zobo business")
    response = client_as("bola").delete(f"/me/businesses/{zobo.business_id}")
    assert response.status_code == 404
    assert len(LongTermMemory.load("ada").businesses) == 1

"""Sign-in checking: only a genuine, unexpired Supabase pass for this project identifies a user.

Instead of contacting Supabase, the tests make their own signing key and hand its public half to the check, the same
way Supabase's published key would be.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api import auth

PROJECT = "https://unittests.supabase.co"
KEY = ec.generate_private_key(ec.SECP256R1())


class _FakeKeyClient:
    """Stands in for Supabase's published keys: always returns the public half of the given key."""

    def __init__(self, private_key):
        self._public = private_key.public_key()

    def get_signing_key_from_jwt(self, _token):
        return type("SigningKey", (), {"key": self._public})()


@pytest.fixture(autouse=True)
def supabase_keys(monkeypatch):
    monkeypatch.setattr(auth, "_key_client", lambda _url: _FakeKeyClient(KEY))


def _pass(key=KEY, **changes) -> HTTPAuthorizationCredentials:
    claims = {"sub": "user-123", "email": "ada@example.com", "aud": "authenticated",
              "iss": f"{PROJECT}/auth/v1", "exp": int(time.time()) + 3600}
    claims.update(changes)
    token = jwt.encode(claims, key, algorithm="ES256")
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_a_genuine_pass_gives_the_user_id():
    user = auth.current_user(_pass())
    assert user.user_id == "user-123"
    assert user.email == "ada@example.com"


def test_no_pass_means_please_sign_in():
    with pytest.raises(HTTPException) as err:
        auth.current_user(None)
    assert err.value.status_code == 401


@pytest.mark.parametrize("bad_pass", [
    lambda: _pass(exp=int(time.time()) - 60),                      # expired
    lambda: _pass(iss="https://someone-else.supabase.co/auth/v1"),  # issued by another project
    lambda: _pass(aud="anon"),                                      # not a signed-in user
    lambda: _pass(key=ec.generate_private_key(ec.SECP256R1())),     # sealed with someone else's key
])
def test_a_pass_that_is_not_genuine_is_refused(bad_pass):
    with pytest.raises(HTTPException) as err:
        auth.current_user(bad_pass())
    assert err.value.status_code == 401

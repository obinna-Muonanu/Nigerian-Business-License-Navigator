"""
It checks who is making each request to the API, using the sign-in pass that Supabase gave them.

When someone signs in on the website, Supabase gives their browser a sign-in pass (a "token"). The website sends that
pass with every request. Before the API does anything, this file checks the pass:

    Is it really from our Supabase project? Supabase stamps every pass with a digital seal. We check the seal using
        Supabase's public key, which it publishes for exactly this purpose. A forged or altered pass fails.
    Is it still valid? Passes expire after a while, and an expired one is turned away.
    Is it meant for signed-in users of this app? The pass says who it's for and who issued it; both must match.

If everything checks out, the user's ID is taken from the pass itself. The website never gets to say who the user
is, so nobody can pretend to be someone else, and one user can never reach another user's chats or memory.

WHY IT MATTERS
Before this, the API trusted whatever user ID it was sent. Anyone who typed another person's ID could have read their
chats. With sign-in checked here, the user's identity comes from Supabase, not from the person making the request.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent.config import get_settings

logger = logging.getLogger(__name__)

# This reads the "Authorization: Bearer <pass>" line from each request. auto_error=False lets us send our own,
# clearer message when the line is missing, instead of FastAPI's generic one.
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """Who is making the request, as proven by their sign-in pass."""

    user_id: str
    email: str | None


def _project_url() -> str:
    """The Supabase project address from .env, without a trailing slash. Stops the request if it isn't set."""
    url = get_settings().supabase_url
    if not url:
        # Refusing everything is safer than letting the API run without sign-in by accident.
        raise HTTPException(status_code=503, detail="Sign-in is not configured on the server (SUPABASE_URL is missing).")
    return url.rstrip("/")


@lru_cache(maxsize=1)
def _key_client(project_url: str) -> jwt.PyJWKClient:
    """Fetch, and remember for an hour, the public keys Supabase uses to seal its sign-in passes.

    Remembering the keys means we don't ask Supabase on every single request, which keeps the API fast. If
    Supabase starts using a new key, the client notices the unfamiliar key on the next pass and fetches again.
    """
    return jwt.PyJWKClient(f"{project_url}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> CurrentUser:
    """Check the request's sign-in pass and return the user it belongs to. Any problem means "401: please sign in".

    FastAPI runs this before every protected route (they list it with Depends), so no route can forget to check.
    """
    project_url = _project_url()
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Please sign in.")
    token = credentials.credentials

    # First, find the public key that matches this pass's seal. If Supabase can't be reached, that's our problem,
    # not the user's, so it's reported as "service unavailable" rather than "please sign in".
    try:
        signing_key = _key_client(project_url).get_signing_key_from_jwt(token).key
    except jwt.PyJWKClientConnectionError:
        logger.warning("could not reach Supabase to fetch its signing keys", exc_info=True)
        raise HTTPException(status_code=503, detail="Sign-in check is temporarily unavailable. Please try again.")
    except jwt.PyJWKClientError:
        raise HTTPException(status_code=401, detail="Your sign-in is not valid. Please sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Your sign-in is not valid. Please sign in again.")

    # Then check the seal, the expiry date, who the pass is for ("authenticated" users) and who issued it (our
    # project). Only the modern sealing methods Supabase uses are accepted, so an attacker can't switch the pass
    # to a weaker one.
    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=f"{project_url}/auth/v1",
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Your sign-in has expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Your sign-in is not valid. Please sign in again.")

    # "sub" is Supabase's permanent ID for this person. It becomes their user ID everywhere in Navi.
    return CurrentUser(user_id=str(claims["sub"]), email=claims.get("email"))

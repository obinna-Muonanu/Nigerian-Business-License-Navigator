"""
This is the web server that sits between Navi and everything that talks to it.

The website (the React app in frontend/) sends its messages here, and this server passes them to Navi and sends the
replies back. The main route streams Navi's reply a few words at a time, so it appears as it's being written. Other
routes list the user's past chats, reopen an old chat, show the saved checklists, and report whether the system is
healthy. A few more give users their data rights: see everything Navi remembers about them, download it, or delete it.

Every route except /health needs the user to be signed in. The user's identity always comes from their Supabase
sign-in pass (see api/auth.py), never from anything the browser says, so one user can never reach another user's data.
The server also checks every request: messages can't be too long, a user can't send too many messages a minute, and
only the website's own address may call it from a browser.

HOW TO RUN IT
    uvicorn api.server:app --reload --port 8000
"""

import json
import logging
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from agent.config import get_settings
from agent.core import AgentPool, after_turn, run_turn, stream_turn
from agent.memory import LongTermMemory
from agent.memory.history import session_transcript
from agent.storage import store
from agent.storage.database import get_db
from api.auth import CurrentUser, current_user

logger = logging.getLogger(__name__)

Mode = Literal["graphrag", "baseline"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run once when the server starts: tidy up data that's been unused for too long.

    Users who haven't visited within the retention period are deleted. For everyone else, businesses unused for
    6 months are set aside, and ones unused for 18 months are deleted. Doing it at start-up means the clean-up
    happens at least on every restart or deploy. For a server that runs for months without restarting, also
    schedule scripts/purge_old_data.py to run daily.
    """
    try:
        s = get_settings()
        removed = store.purge_inactive_users(s.memory_retention_days)
        retired = store.retire_unused_businesses(s.business_inactive_days, s.business_delete_days)
        if removed or any(retired.values()):
            logger.info("retention: deleted %d inactive users; businesses %s", removed, retired)
    except Exception:
        # A failed clean-up must never stop the server from starting; it will be tried again next time.
        logger.warning("retention clean-up failed", exc_info=True)
    yield
    # The server is shutting down: hand the database connections back cleanly.
    get_db().close()


# One app and one pool of agents for the whole server. The pool keeps recently used agents in memory, so a
# follow-up message doesn't have to rebuild the agent from the database.
app = FastAPI(title="License Navigator", version="2.0.0", lifespan=lifespan)
pool = AgentPool()

# Browsers only let a web page call an API on a different address if the API says that page is allowed. This
# lists exactly which website addresses are allowed (ALLOWED_ORIGINS in .env), so another site can't use a
# signed-in visitor's browser to call Navi behind their back.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origin_list,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# This describes what a chat request must look like, and Pydantic checks every request against it before our
# code runs. A missing field or a huge message gets a clear error instead of reaching the model. The length
# limits also put a ceiling on what one request can cost. There's no user ID here: it comes from the sign-in.
class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=64, description="Omit to start a new chat")
    message: str = Field(min_length=1, max_length=4000)
    mode: Mode = "graphrag"


class RateLimiter:
    """Allow each user at most N chat messages in any 60-second window.

    It remembers the times of each user's recent messages. When a new one arrives, times older than a minute are
    forgotten, and if N are still left, the message is refused with "429: too many requests". This lives in the
    server's memory, which is right for one server; with several servers, the same idea would move into a shared
    store such as the database.
    """

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._recent: dict[str, deque[float]] = defaultdict(deque)

    def check(self, user_id: str) -> None:
        now = time.monotonic()
        recent = self._recent[user_id]
        while recent and now - recent[0] > 60:
            recent.popleft()
        if len(recent) >= self.per_minute:
            raise HTTPException(status_code=429, detail="You're sending messages too quickly. Please wait a moment.")
        recent.append(now)


rate_limiter = RateLimiter(get_settings().chat_messages_per_minute)


def _check_session_id(session_id: str) -> None:
    """Turn away unsafe chat IDs. Chat IDs end up in log file names, so they can't contain slashes or dots.

    That blocks tricks like "../../etc" from a malicious client.
    """
    if any(ch in session_id for ch in "/\\.") or not session_id.strip():
        raise HTTPException(status_code=400, detail="Invalid session_id.")


def _own_session(session_id: str, user: CurrentUser) -> None:
    """Make sure an existing chat belongs to the signed-in user.

    A chat that isn't on record for this user gets "not found", whether it belongs to someone else or doesn't
    exist at all. We don't even confirm that someone else's chat exists.
    """
    _check_session_id(session_id)
    if store.session_owner(session_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Chat not found.")


def _session_for(req: ChatRequest, user: CurrentUser) -> str:
    """Decide which chat a message belongs to.

    New chats always get their ID from the server, so a browser can never pick an ID that clashes with someone
    else's chat. An existing chat must belong to the signed-in user.
    """
    if req.session_id is None:
        return f"s-{uuid.uuid4().hex}"
    _own_session(req.session_id, user)
    return req.session_id


def _sse(payload: dict) -> str:
    """Format one Server-Sent Event: the word "data:", the event as JSON, and a blank line.

    Server-Sent Events work over plain HTTP, and browsers understand them out of the box. For streaming in one
    direction, they're much simpler than WebSockets.
    """
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


@app.post("/chat")
async def chat(req: ChatRequest, user: CurrentUser = Depends(current_user)) -> StreamingResponse:
    """Run one turn and stream the reply back, piece by piece, as Server-Sent Events."""
    rate_limiter.check(user.user_id)
    session_id = _session_for(req, user)
    agent = pool.get(user.user_id, session_id, req.mode)
    lock = pool.lock(session_id, req.mode)

    async def events():
        # The first event tells the website which chat it's in, which it needs to know if it just started a new one.
        yield _sse({"type": "session", "session_id": session_id})
        # Only one turn at a time per chat.
        async with lock:
            try:
                async for event in stream_turn(agent, req.message):
                    yield _sse(event)
            except Exception:
                # The full error goes to the server log for us to investigate. The user gets a plain message:
                # error details can reveal how the system works inside, which is useful to an attacker.
                logger.exception("turn failed for session %s", session_id)
                yield _sse({"type": "error", "text": "Sorry, something went wrong on our side. Please try again."})

    # The chat's note (episodic memory) is refreshed after the stream has closed, so it never delays the reply.
    # The headers stop proxies from holding the stream back, which would make the reply arrive all at once.
    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(after_turn, agent),
    )


# This does the same as /chat, with the same agent and the same lock, but returns the whole reply in one JSON
# response. That's easier for test tools and scripts that don't read streams.
@app.post("/invoke")
async def invoke(req: ChatRequest, user: CurrentUser = Depends(current_user)) -> dict:
    """Run one turn and return the whole reply at once."""
    rate_limiter.check(user.user_id)
    session_id = _session_for(req, user)
    agent = pool.get(user.user_id, session_id, req.mode)
    async with pool.lock(session_id, req.mode):
        result = await run_turn(agent, req.message)
    after_turn(agent)
    return {"session_id": session_id, **result}


# The website calls this when the user starts a new chat. Writing the chat's note now guarantees the next chat's
# memory block includes it, even if the chat ended in between the regular note updates.
@app.post("/sessions/{session_id}/end")
async def end_session(session_id: str, mode: Mode = "graphrag", user: CurrentUser = Depends(current_user)) -> dict:
    """End a chat: write its note (episodic memory) now and free its agent from memory."""
    _own_session(session_id, user)
    agent = pool.get(user.user_id, session_id, mode)
    after_turn(agent, force_summary=True)
    pool.drop(session_id, mode)
    return {"status": "ok"}


# The next two routes power the sidebar: the list of chats, and reopening one of them.
@app.get("/sessions")
def list_sessions(mode: Mode = "graphrag", user: CurrentUser = Depends(current_user)) -> dict:
    """List the signed-in user's chats for this mode, the most recently used first."""
    return {"sessions": store.list_sessions(user.user_id, mode)}


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str, user: CurrentUser = Depends(current_user)) -> dict:
    """Return one of the user's chats as they saw it, so it can be reopened from the sidebar."""
    _own_session(session_id, user)
    return {"session_id": session_id, "messages": session_transcript(session_id)}


# Everything about the signed-in user lives under /me. There's no user ID in these addresses at all, so there's
# nothing to change to reach someone else's data.
@app.get("/me")
def me(user: CurrentUser = Depends(current_user)) -> dict:
    """Say who is signed in. The website uses this to show the user's email."""
    return {"user_id": user.user_id, "email": user.email}


@app.get("/me/checklist")
def my_checklist(user: CurrentUser = Depends(current_user)) -> dict:
    """Return the user's saved checklists (one per business) and their reminders, for the sidebar."""
    return {"checklists": store.load_checklists(user.user_id), "reminders": store.list_reminders(user.user_id)}


# What Navi remembers, and the user's data rights under the NDPA. /me/memory shows the memory the way Navi uses
# it: each business with its facts, where each fact came from and its finished steps, plus the notes from recent
# chats. /me/export returns everything stored about the user, and the two DELETE routes erase one business or
# everything.
@app.get("/me/memory")
def my_memory(user: CurrentUser = Depends(current_user)) -> dict:
    """Show everything Navi remembers about the signed-in user, the way Navi sees it."""
    memory = LongTermMemory.load(user.user_id)
    return {
        "businesses": [
            {
                "business_id": b.business_id,
                "label": b.label,
                "status": b.status,
                "last_used_at": b.last_used_at,
                "profile": b.profile.model_dump(exclude_none=True),
                "fact_sources": b.sources,
                "missing_for_planning": b.profile.missing_for_planning(),
                "completed_steps": [{"id": step, "name": _step_name(step)} for step in b.completed],
            }
            for b in memory.businesses
        ],
        "recent_sessions": memory.episodes,
        # The retention rules, so the "My data" page can explain them in plain words.
        "retention": {"business_inactive_days": get_settings().business_inactive_days,
                      "business_delete_days": get_settings().business_delete_days},
    }


def _step_name(requirement_id: str) -> str:
    """Turn an internal step code (like R01) into its plain name, since codes are never shown to users."""
    try:
        from agent.knowledge import graph_service

        resolved = graph_service.resolve_requirement(requirement_id)
        return resolved["name"] if resolved else requirement_id
    except Exception:
        # If the knowledge graph can't be reached, show the code rather than failing the whole page.
        return requirement_id


@app.get("/me/export")
def export_me(user: CurrentUser = Depends(current_user)) -> dict:
    """Return everything stored about the signed-in user, so they can see it all or take it elsewhere."""
    return LongTermMemory.export(user.user_id)


@app.delete("/me")
def delete_me(user: CurrentUser = Depends(current_user)) -> dict:
    """Delete everything stored about the signed-in user: businesses, facts, chats, notes, reminders and logs.

    Their Supabase sign-in account itself isn't touched; they can still sign in, and they'll start fresh.
    """
    # Drop their chats from the in-memory pool first, so a chat in progress can't write anything back.
    pool.drop_user(user.user_id)
    LongTermMemory.forget_user(user.user_id)
    return {"status": "deleted"}


@app.delete("/me/businesses/{business_id}")
def delete_my_business(business_id: str, user: CurrentUser = Depends(current_user)) -> dict:
    """Delete one of the signed-in user's businesses and everything recorded about it."""
    if not LongTermMemory.forget_business(user.user_id, business_id):
        raise HTTPException(status_code=404, detail="Business not found.")
    # Chats held in memory still mention the deleted business in their instructions, so they start afresh.
    pool.drop_user(user.user_id)
    return {"status": "deleted", "business_id": business_id}


@app.get("/health")
def health() -> dict:
    """Say whether the server is working, which database it writes to, and how big the knowledge graph is.

    This is the only route that doesn't need sign-in, so hosting services can use it to check the server is up.
    If Neo4j or the app database can't be reached, it reports "degraded" instead of crashing. The import is inside
    the function so /health still works even if the graph module itself fails to load.
    """
    try:
        from agent.knowledge.graph_service import graph_stats

        get_db().fetch_one("SELECT 1 AS ok")
        return {"status": "ok", "database": get_db().kind, "graph": graph_stats(),
                "sign_in_configured": bool(get_settings().supabase_url)}
    except Exception as exc:
        logger.warning("health check failed", exc_info=True)
        return {"status": "degraded", "error": type(exc).__name__}

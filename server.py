"""
This is the web server that sits between Navi and everything that talks to it.

The chat web page, the testing scripts and any other program send their messages here, and this server passes them to
Navi and sends the replies back. The main route streams Navi's reply a few words at a time, so it appears as it's
being written. Other routes list a user's past chats, reopen an old chat, show the saved checklist, and report whether
the system is healthy.

It also checks every request: messages can't be too long, and a user can't open someone else's chat.

HOW TO RUN IT
    uvicorn server:app --reload --port 8000
"""

import json
import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from agent.core import AgentPool, after_turn, run_turn, stream_turn
from agent.memory import LongTermMemory
from agent.memory.history import session_transcript
from agent.storage import sqlite_store

# One app and one pool of agents for the whole server. The pool keeps recently used agents in memory, so a
# follow-up message doesn't have to rebuild the agent from disk.
app = FastAPI(title="License Navigator", version="1.0.0")
pool = AgentPool()


# This describes what a chat request must look like, and Pydantic checks every request against it before our
# code runs. A missing field or a huge message gets a clear error instead of reaching the model. The length
# limits also put a ceiling on what one request can cost.
class ChatRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64, description="Stable user ID (long-term memory key)")
    session_id: str | None = Field(default=None, max_length=64, description="Omit to start a new session")
    message: str = Field(min_length=1, max_length=4000)
    mode: Literal["graphrag", "baseline"] = "graphrag"


def _session_id(req: ChatRequest) -> str:
    """Get the chat's ID from the request, or make a new random one if this is a new chat, then check it's allowed."""
    sid = req.session_id or f"s-{uuid.uuid4().hex[:12]}"
    _check_session(sid, req.user_id)
    return sid


def _check_session(session_id: str, user_id: str) -> None:
    """Turn away unsafe chat IDs, and chats that belong to someone else.

    Each chat is saved as a folder named after its ID, so an ID can't contain slashes or dots. That also
    blocks tricks like "../../etc" from a malicious client. And because chats can be reopened by ID, a user
    mustn't be able to read or continue someone else's chat just by guessing its ID. We answer "not found"
    rather than "forbidden", so we don't even confirm that the chat exists.
    """
    if any(ch in session_id for ch in "/\\."):
        raise HTTPException(status_code=400, detail="session_id may not contain '/', '\\' or '.'")
    owner = sqlite_store.session_owner(session_id)
    if owner is not None and owner != user_id:
        raise HTTPException(status_code=404, detail="Session not found")


def _sse(payload: dict) -> str:
    """Format one Server-Sent Event: the word "data:", the event as JSON, and a blank line.

    Server-Sent Events work over plain HTTP, and both browsers and the `requests` library understand them
    out of the box. For streaming in one direction, they're much simpler than WebSockets.
    """
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """Run one turn and stream the reply back, piece by piece, as Server-Sent Events."""
    session_id = _session_id(req)
    agent = pool.get(req.user_id, session_id, req.mode)
    lock = pool.lock(session_id, req.mode)

    async def events():
        # The first event tells the client which chat it's in, which it needs to know if it just started a new one.
        yield _sse({"type": "session", "session_id": session_id})
        # Only one turn at a time per chat.
        async with lock:
            try:
                async for event in stream_turn(agent, req.message):
                    yield _sse(event)
            except Exception as exc:
                # If something breaks, tell the UI what went wrong rather than leaving it with a broken stream.
                yield _sse({"type": "error", "text": f"Something went wrong: {type(exc).__name__}: {exc}"})

    # The long-term summary runs after the stream has closed, so it never delays the reply. The headers stop
    # proxies like nginx or ngrok from holding the stream back, which would make the reply arrive all at once
    # instead of word by word.
    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(after_turn, agent),
    )


# This does the same as /chat, with the same agent and the same lock, but returns the whole reply in one JSON
# response. That's easier for test tools and scripts that don't read streams. There's no stream to wait for
# here, so the summary work simply runs before we reply.
@app.post("/invoke")
async def invoke(req: ChatRequest) -> dict:
    """Run one turn and return the whole reply at once."""
    session_id = _session_id(req)
    agent = pool.get(req.user_id, session_id, req.mode)
    async with pool.lock(session_id, req.mode):
        result = await run_turn(agent, req.message)
    after_turn(agent)
    return {"session_id": session_id, **result}


# The UI calls this when the user starts a new chat. Writing the summary now guarantees the next chat's
# memory block includes this one, even if it ended in between the regular summary updates.
@app.post("/sessions/{session_id}/end")
async def end_session(session_id: str, user_id: str, mode: Literal["graphrag", "baseline"] = "graphrag") -> dict:
    """End a chat: write its long-term summary now and free its agent from memory."""
    _check_session(session_id, user_id)
    agent = pool.get(user_id, session_id, mode)
    after_turn(agent, force_summary=True)
    pool.drop(session_id, mode)
    return {"status": "ok", "summary": LongTermMemory.load(user_id).summary}


# The next two endpoints power the Claude-style sidebar: the list of chats, and reopening one of them.
@app.get("/users/{user_id}/sessions")
def user_sessions(user_id: str, mode: Literal["graphrag", "baseline"] = "graphrag") -> dict:
    """List the user's chats for this mode, the most recently used first."""
    return {"sessions": sqlite_store.list_sessions(user_id, mode)}


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str, user_id: str) -> dict:
    """Return one chat's conversation as the user saw it, so it can be reopened from the sidebar.

    Only chats the server has on record for this user can be opened; anything else gets "not found".
    """
    _check_session(session_id, user_id)
    if sqlite_store.session_owner(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "messages": session_transcript(session_id)}


# Read-only views. /memory is just for debugging now (the UI no longer shows it), and /checklist feeds the
# checklist section of the sidebar.
@app.get("/users/{user_id}/memory")
def user_memory(user_id: str) -> dict:
    """Show everything the agent remembers about a user. Handy when debugging memory."""
    memory = LongTermMemory.load(user_id)
    return {
        "profile": memory.profile.model_dump(exclude_none=True),
        "missing_for_planning": memory.profile.missing_for_planning(),
        "language": memory.language,
        "summary": memory.summary,
        "completed": memory.completed,
    }


@app.get("/users/{user_id}/checklist")
def user_checklist(user_id: str) -> dict:
    """Return the user's saved checklist and their reminders."""
    return {"checklist": sqlite_store.load_checklist(user_id), "reminders": sqlite_store.list_reminders(user_id)}


@app.get("/health")
def health() -> dict:
    """Say whether the server is working, and how big the knowledge graph is."""
    # If Neo4j can't be reached, this reports "degraded" instead of crashing, so you can tell a database
    # problem apart from a server that's down. The import is inside the function so /health still works even
    # if the graph module itself fails to load.
    try:
        from agent.knowledge.graph_service import graph_stats

        return {"status": "ok", "graph": graph_stats()}
    except Exception as exc:
        return {"status": "degraded", "error": str(exc)}

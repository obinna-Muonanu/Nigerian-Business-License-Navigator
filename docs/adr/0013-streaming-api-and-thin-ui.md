# ADR 0013: A streaming FastAPI server, with a thin web client

**Status:** Accepted · **Date:** 2026-10-26 · Rewritten 2026-11-04 to describe the server and client Navi uses today.
The React web app and sign-in are explained in [0019](0019-react-frontend-and-supabase-sign-in.md)

## Context

An agent reply can take many seconds, because the agent may search, build a plan and only then start writing. If the
user has to wait for the whole answer before seeing anything, it feels slower than it is.

I also needed every way of using the agent, from the website to the command line and the evaluation, to run the same
agent with the same hooks and logs, without each having its own copy of the logic.

## Decision

A small **FastAPI** server is how the website and other outside clients reach the agent.

| Route | What it does |
|---|---|
| `POST /chat` | Streams the reply as Server-Sent Events (SSE) |
| `POST /invoke` | Returns the whole reply as one JSON object, for scripts and test platforms |
| `POST /sessions/{id}/end` | Ends a chat, writes its episodic note and frees its agent |
| `GET /sessions`, `GET /sessions/{id}/messages` | The chat list and chat history for the sidebar |
| `GET /me`, `/me/checklist`, `/me/memory`, `/me/export` | The user's own details, checklists and stored data |
| `DELETE /me`, `DELETE /me/businesses/{id}` | Deletes the user's data, or one business |
| `GET /health` | Reports the state of the database and the graph; the only route that needs no sign-in |

The streaming comes straight from Strands. `agent.stream_async()` yields text as the model writes it, and the server
forwards each piece the moment it arrives. Each event is one of: `text`, `retract` (removes a line where Navi narrated
its own work), `tool` (a tool has started), `graph`, `warning`, `handoff` or `done`.

The **React web app** in `frontend/` is a thin client. It never imports the agent code, and only calls the API.

Everything shares `build_agent` and `stream_turn` in `agent/core.py`. The server calls them through an agent pool. The
command line and the evaluation call them directly, so they need no server.

Behind the API, the agent pool keeps up to 64 recent agents in memory, so a follow-up message doesn't have to rebuild
the agent from the database. A lock per chat stops two messages from the same chat running at the same time.

## Why I chose this

Streaming makes the wait easier. The user sees which tool is running, and then the words as they're written.

SSE is the simplest way to stream in one direction over plain HTTP, with no WebSocket setup.

Sharing one code path means a result in the evaluation is a result for the real agent. The one thing the evaluation
doesn't exercise is the server layer itself, which the unit tests in `tests/test_api.py` cover.

And because the client is thin, it can be replaced without touching the agent. That has already happened: the first
client was built with Streamlit, and the React app replaced it with no change to the agent.

## What I considered instead

**Having the web client call the agent directly** would have tied the two together, and no other client could have
reused it.

**WebSockets** give a two-way channel, which I didn't need, and they're more complex.

**No streaming at all** would have meant long waits for multi-step answers.

**A hosted agent runtime such as AgentCore or Lambda** would have meant more AWS setup and cost, and my AWS access only
covers Bedrock models.

## Consequences

Replies feel more responsive, and every client runs the same agent. Three things to remember:

- A running server keeps the old code in memory, so after changing the code you have to restart it, or run it with
  `--reload`.
- The agent pool and the locks live in one server's memory. Chats are saved in the database, so another server could
  pick up a chat, but the per-chat lock wouldn't reach across servers.
- The server still sends the `graph` event, which the website ignores since the step diagram was removed. Removing it
  is a small clean-up for later.

## Where to find it

The API is `api/server.py`, and `stream_turn`, `run_turn` and `AgentPool` are in `agent/core.py`. The web app is in
`frontend/` (`frontend/src/lib/api.ts` reads the stream), and the command line is `main_agent.py`.

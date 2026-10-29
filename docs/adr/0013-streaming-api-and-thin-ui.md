# ADR 0013: A streaming FastAPI server, with Streamlit as a thin client

**Status:** Accepted · **Date:** 2026-10-26

## Context

An agent reply can take several seconds, because the agent may search, build a plan and only then
start writing. If the user has to wait for the whole answer before seeing anything, it feels slow
even when it isn't.

I also needed a single way into the agent. The web UI, the command line, the evaluation and any test
platform all had to use the same agent, with the same hooks and the same logs, without each of them
having its own copy of the agent logic.

## Decision

A small **FastAPI** server is the only way into the agent. `POST /chat` streams the reply as
Server-Sent Events (SSE), carrying the text, which tool is being used, the graph data and any
warnings. `POST /invoke` returns the whole reply as one JSON object, for scripts and test platforms.
A few smaller endpoints serve the chat list, chat history and checklist for the sidebar, along with
`/health`.

The streaming comes straight from Strands. `agent.stream_async()` yields text as the model writes it,
and the server forwards each piece the moment it arrives.

The **Streamlit** UI is a thin client: it never imports the agent code, it only calls the API. It
shows the streamed chat, a Claude-style chat list where you can start a new chat or reopen an old one,
the checklist and a dependency diagram. The user ID, the baseline/GraphRAG switch and debug
information are tucked away in a collapsed Developer settings section.

Behind the API, an agent pool keeps recent agents in memory, so a follow-up message doesn't have to
rebuild the agent from scratch. A lock per session stops two messages from the same chat running at
the same time.

## Why I chose this

Streaming makes the agent feel fast. The first words appear in about a second, even when the whole
answer takes longer.

SSE is the simplest way to stream in one direction over plain HTTP. Browsers and the `requests`
library both support it, and there's no WebSocket setup.

Having one API means the UI, the CLI, the evaluation and the test platforms all exercise exactly the
same agent. A result in the evaluation is a result for the real app.

And because the UI is thin, it can be replaced without touching the agent.

## What I considered instead

**Having Streamlit call the agent directly** would have tied the UI and the agent together, and no
other client could have reused it.

**WebSockets** give a two-way channel, which I didn't need, and they're more complex.

**No streaming at all** would have meant long waits for multi-step answers.

**A hosted agent runtime such as AgentCore or Lambda** would have meant more setup and cost, when a
local FastAPI server already met the brief.

## Consequences

Answers feel responsive and every client goes through the same door. The one thing to remember is
that a running server keeps the old code in memory, so after changing the code you have to restart
it, or run it with `--reload`.

## Where to find it

The API is `server.py`. `stream_turn` and `AgentPool` are in `agent/core.py`. The UI is
`ui/streamlit_app.py`, and the CLI is `main_agent.py`.

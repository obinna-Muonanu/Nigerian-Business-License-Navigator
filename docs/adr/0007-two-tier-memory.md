# ADR 0007: Two kinds of memory: short-term per session, long-term per user

**Status:** Accepted · **Date:** 2026-10-27

## Context

Imagine someone who told the navigator yesterday that they're making zobo in Ibadan as a sole
proprietor. When they come back today and start a new chat, they shouldn't be asked "What business?
Which state? Are you registered?" all over again.

The lazy fix would be to send the whole of yesterday's conversation to the model. But that's slow,
it's expensive, and most of it no longer matters. What the agent really needs to carry over is a
handful of facts.

## Decision

I split memory into two kinds.

**Short-term memory** is the current conversation. It's keyed by `session_id`, which is new for every
chat, and it holds the recent messages plus `agent.state` (the profile and any pending
confirmations). Strands saves it to disk with `FileSessionManager`, and it's used on every turn.

**Long-term memory** is a small set of facts about the user. It's keyed by `user_id`, which stays the
same across chats, and it holds the profile, the completed steps and a three-line summary of the last
session. It lives in SQLite's `user_memory` and `progress` tables. At the start of each session, it's
turned into a short "what you know about this user" block for the agent.

Facts reach long-term memory in two ways. When the user states a fact, the agent calls
`remember_profile`, which saves it to SQLite immediately, but only for fields on a fixed allowed
list. Separately, every few turns, after the reply has been sent, Claude Haiku writes the three-line
summary in the background, so the user never waits for it.

## Why I chose this

It gives exactly the behaviour I wanted: a new session starts with an empty chat but a full profile.
A returning user gets "Welcome back, still zobo in Ibadan?" instead of an interview.

Facts are stored as data, not as chat. The profile has six or seven fields, so a database row is
exact, cheap and instant. No AI is needed to "remember" a state name.

Saving each fact the moment it's stated means nothing is lost if the user closes the tab halfway
through.

And because only allowed fields can be stored (business type, state, structure and so on), the agent
keeps as little personal data as possible, which is what the NDPA asks for.

## What I considered instead

**Re-sending the whole conversation history every session** was slow, expensive and mostly
irrelevant.

**A vector "memory" of past chats** is imprecise for six known facts, and it adds cost.

**Having an AI extract facts from every message** would cost an extra call per message and can
mis-remember. The agent already calls `remember_profile` when it hears a fact, so it wasn't needed.

**A hosted memory service such as AgentCore Memory** would have meant more services to set up, when
SQLite already did the job.

## Consequences

Returning users are recognised, costs stay low, and memory is exact and private. The catch is that
it relies on a stable `user_id`. In the UI that sits under Developer settings. Anything the user says
that isn't one of the fixed fields only survives in the short summary.

## Where to find it

The memory code is in `agent/memory/short_term.py`, `agent/memory/long_term.py` and
`agent/memory/summarizer.py`. The tool is `agent/tools/remember_profile.py`, and the memory block is
built by `render_memory_block` in `agent/prompts.py`.

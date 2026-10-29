# ADR 0008: Our own conversation manager: after 30 turns, keep the last 12 messages and summarise the rest

**Status:** Accepted · **Date:** 2026-10-27

## Context

Every time the agent calls the model, it re-sends the conversation so far. That means long chats get
slower and more expensive with every message.

Strands' built-in sliding window deals with this by dropping the oldest messages. It's cheap, but the
agent then forgets things the user said earlier. If someone says "as I mentioned, we're a
partnership" forty messages in, the agent may no longer know what they mentioned.

## Decision

I wrote my own Strands conversation manager, `RollingSummaryConversationManager`.

For the first 30 user turns it keeps the whole conversation. Once the chat passes 30 turns, it keeps
the last 12 messages word for word, and everything older is merged with any previous summary into one
new summary, written by the cheaper Haiku model. It only runs again once the chat has grown past 30
turns again, so in practice it costs one small model call roughly every 25 turns, not one per turn.

Getting it to work with Bedrock took three rules. It never separates a tool call from its result:
if the cut would land between them, it moves back to the start of the turn, so it sometimes keeps
more than 12 messages, never fewer. It keeps the roles alternating: the summary goes in as a user
message, followed by a short assistant "Understood". And it survives restarts: the summary is saved
with the session, so reopening a chat restores it.

## Why I chose this

Unlike a sliding window, old context isn't thrown away. It's kept in compressed form, so the agent
still knows the gist of what was said early on.

It's cheap, at about one summary call every 25 turns.

And the important facts never depend on the summary. The profile and progress also live in
`agent.state` and SQLite (ADR 0007). A weak summary might lose some detail, but it can never lose the
checklist or what the user has confirmed.

## What I considered instead

**The built-in sliding window** forgets older context completely.

**The built-in summarising manager** only kicks in when the context window overflows, not at a turn
count I can choose and reason about.

**Summarising on every turn** would cost a model call each time and keep rewriting the history,
which also defeats prompt caching.

## Consequences

Long chats stay fast and cheap without forgetting what mattered. The turn that triggers a summary
takes about one or two seconds longer, and the prompt cache has to be rebuilt once after each
summary. Separately, a compaction hook shortens old tool results on every turn, at no model cost (ADR
0014).

## Where to find it

The manager is in `agent/memory/conversation_manager.py`. Its thresholds come from `.env`:
`SUMMARY_TRIGGER_TURNS=30` and `KEEP_RECENT_MESSAGES=12`.

# ADR 0008: Our own conversation manager: summarise older messages and keep recent ones word for word

**Status:** Accepted · **Date:** 2026-10-27 · Rewritten 2026-11-04 to describe the rule Navi uses today, set in
[0018](0018-production-memory.md)

## Context

Every time the agent calls the model, it re-sends the conversation so far. That means long chats get slower and more
expensive with every message.

Strands' built-in sliding window deals with this by dropping the oldest messages. It's cheap, but the agent then
forgets things the user said earlier. If someone says "as I mentioned, we're a partnership" forty messages in, the
agent may no longer know what they mentioned.

## Decision

I wrote my own Strands conversation manager, `RollingSummaryConversationManager`. It has one rule:

> Once the whole context window (rules, memory block, tool list and conversation) reaches about **24,000 tokens**, keep
> the **last 5 turns** word for word, and replace everything older with a short summary.

A turn is one message the user typed plus everything Navi did to answer it, including its tool calls. The check runs
after every turn, using an estimate of about four characters per token, so it needs no extra model call. When the
limit is reached, the fast model merges the older messages with any previous summary into one new summary of at most
250 words. If the model ever reports that the conversation is too big, the manager summarises straight away.

Getting it to work with Bedrock took three rules. It never separates a tool call from its result: the cut always lands
at the start of a turn. It keeps the roles alternating: the summary goes in as a user message, followed by a short
assistant "Understood". And it survives restarts: the summary is saved with the chat, so reopening a chat restores it.

## Why I chose this

Unlike a sliding window, old context isn't thrown away. It's kept in compressed form, so the agent still knows the gist
of what was said early on.

Tokens decide when, because tokens are what cost money and slow replies. A few turns with big checklists can cost more
than thirty short ones, so counting turns would summarise too late in some chats and too early in others.

Counting turns for what to keep means the user's recent exchanges stay whole, because one turn can contain several
tool calls and results.

And the important facts never depend on the summary. The profile and progress live in the app database (ADR 0007). A
weak summary might lose some detail, but it can never lose the checklist or what the user has confirmed.

## What I considered instead

**The built-in sliding window** forgets older context completely.

**The built-in summarising manager** only kicks in when the context window overflows, not at a limit I can choose and
reason about.

**A fixed turn count** was my first version: after 30 turns, keep the last 12 messages. It ignored how big each turn
really was, and one turn can hold several messages, so 12 messages didn't mean a fixed number of exchanges.

**Summarising on every turn** would cost a model call each time and keep rewriting the history, which also defeats
prompt caching.

## Consequences

Long chats stay cheaper without forgetting what mattered. The turn that triggers a summary takes a little longer,
because of the extra model call, and the prompt cache for the conversation has to be rebuilt afterwards. If a summary
fails, the full history is kept and it tries again on the next turn. Separately, a compaction hook shortens old tool
results on every turn, at no model cost (ADR 0014).

## Where to find it

The manager is in `agent/memory/conversation_manager.py`, and its prompt is `CONVERSATION_SUMMARY_PROMPT` in
`agent/prompts.py`. Its limits come from `.env`: `SUMMARY_TRIGGER_TOKENS=24000` and `KEEP_RECENT_TURNS=5`.

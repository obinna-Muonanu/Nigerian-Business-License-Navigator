# ADR 0007: Memory types: working, short-term and long-term (confirmed facts and episodic notes)

**Status:** Accepted · **Date:** 2026-10-27 · Rewritten 2026-11-04 to describe the memory Navi has today. The
production details (Postgres, several businesses, fact sources and retention) are in
[0018](0018-production-memory.md)

## Context

Imagine someone who told Navi yesterday that they're making zobo in Ibadan as a sole proprietor. When they come back
today and start a new chat, they shouldn't be asked "What business? Which state? Are you registered?" all over again.

The lazy fix would be to send the whole of yesterday's conversation to the model. But that's slow and expensive, and
most of it no longer matters. Navi needs different things remembered for different lengths of time, and it should
trust some of them more than others. A fact that a plan is built from has to be exact. A note about what happened
last time only has to help Navi pick up the thread.

## Decision

I split memory by job. There are three types, and long-term memory comes in two forms.

| | Working memory | Short-term memory | Long-term: confirmed facts | Long-term: episodic notes |
|---|---|---|---|---|
| **Question it answers** | What am I looking at right now? | What have we said in this chat? | What do I know for sure about this user? | What happened in recent chats? |
| **Holds** | The rules, the memory block, recent messages and fresh tool results | The conversation, and the chat's state, such as an action waiting for a "yes" | Each business's facts, finished steps, checklist and reminders | A three-line note per chat |
| **Kept for** | One model call | One chat | Across chats, until a retention limit | Across chats, until the user is deleted |
| **Keyed by** | Nothing; it's built fresh | `session_id` | `business_id`, under a `user_id` | `session_id`, under a `user_id` |
| **Stored in** | Only in the request | `chat_sessions`, `chat_agents`, `chat_messages` | `businesses`, `profile_facts`, `fact_history`, `progress`, `checklists`, `reminders` | `episodes` |
| **Written by** | The code that builds each request | Strands, after every message | The tools, such as `remember_profile` | The fast model, in the background |
| **Kept small by** | Trimming old tool results, and prompt caching | A rolling summary at about 24,000 tokens, keeping the last 5 turns | A fixed list of business fields | Three lines each |

**Working memory** is whatever is sent to the model for one reply. The compaction hook trims old tool results after
each turn, and Bedrock caches the fixed rules.

**Short-term memory** is the current chat. Strands saves it to the app database after every message through my session
repository, so a restart loses nothing, including a question waiting for the user's "yes". When a chat gets long, the
rolling summary shortens it ([ADR 0008](0008-rolling-summary-conversation-manager.md)).

**Long-term memory: confirmed facts.** When the user states a fact, Navi calls `remember_profile`, which checks it and
saves it straight away, but only for fields on a fixed list. Each business has its own facts. A value that contradicts
a stored one isn't saved until the user confirms the change.

**Long-term memory: episodic notes.** The fast model writes a three-line note about the chat, in the background, every
4 turns and when the chat ends, so the user never waits for it. Each chat has one note, which is overwritten as the
chat goes on. A chat with nothing useful in it saves no note.

**How long-term memory reaches the model.** When an agent is built for a chat, the facts and the last 3 notes are
turned into a short "what you already know about this user" block in the system prompt. The notes have their own
heading and are labelled as possibly incomplete. If a note disagrees with a fact, the fact wins.

## Why I chose this

It gives the behaviour I wanted: a new chat starts with an empty conversation but a full profile. A returning user
gets "Still zobo in Ibadan?" instead of an interview.

Facts are stored as data, not as chat. A database row is exact, cheap and instant, and no AI is needed to remember a
state name.

Saving each fact the moment it's stated means nothing is lost if the user closes the tab halfway through.

Keeping notes apart from facts lets Navi remember the gist of past chats without risking a wrong plan. A note may be
incomplete, because an AI wrote it, but it can never override a fact.

And because only allowed fields can be stored (business type, state, structure and so on), Navi keeps as little
personal data as possible, which is what the NDPA asks for.

## What I considered instead

**Re-sending past conversations every chat** was slow, expensive and mostly irrelevant.

**A vector "memory" of past chats** is imprecise for a short list of known facts, and it adds cost.

**Having an AI extract facts from every message** would cost an extra call per message and can mis-remember. Navi
already calls `remember_profile` when it hears a fact.

**One note per user** was simpler, but each new chat overwrote the note from the last one, so I moved to one per chat.

**A hosted memory service such as AgentCore Memory** would have meant more services to set up, and my AWS access only
covers Bedrock models.

## Consequences

Returning users are recognised, costs stay low, and plans are built only from confirmed facts.

There are limits. Anything the user says that isn't one of the fixed fields survives only in an episodic note, and
only the last 3 notes are shown. Because the memory block is built with the agent, a note written during a chat is
meant for the next chat, not this one. And `remember_profile` depends on the model calling it. The model has missed
facts said indirectly, so the input guard now reminds it on every message
([ADR 0009](0009-enforce-rules-in-code-with-hooks.md)).

## Where to find it

- Short-term memory: `agent/memory/short_term.py`, `agent/memory/conversation_manager.py`,
  `agent/storage/chat_repository.py`
- Confirmed facts: `agent/memory/long_term.py`, `agent/tools/remember_profile.py`
- Episodic notes: `agent/memory/summarizer.py`, and `recent_episodes` in `agent/storage/store.py`
- Memory block: `render_memory_block` in `agent/prompts.py`
- Working memory: `build_agent` in `agent/core.py`, `agent/hooks/compaction.py`

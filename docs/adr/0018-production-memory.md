# ADR 0018: Production memory: four kinds of memory, several businesses per user, kept in Postgres

**Status:** Accepted · **Date:** 2026-11-01 · Replaces [0007](0007-two-tier-memory.md), and updates
the storage engine in [0006](0006-sqlite-for-everything-the-agent-writes.md) and the summary trigger in
[0008](0008-rolling-summary-conversation-manager.md)

## Context

The two-tier memory from ADR 0007 worked well for the demo, but it had four problems that would hurt
real users.

The first was **where it lived**. Chats were saved as files and memory as a SQLite file, both on the
server's own disk. On Render that disk is wiped on every restart or redeploy, so every user lost
their chats and their remembered profile. Files also can't be shared, so I couldn't run a second
copy of the server to handle more people.

The second was **one business per user**. The profile, the checklist and the progress were all keyed
by `user_id`. When I tested someone asking about a zobo business and a cosmetics store in the same
message, Navi only answered about one of them. It wasn't being lazy: there was nowhere to put the
second business, and saving it would have overwritten the first.

The third was **trust**. A remembered fact had no record of where it came from, and a new value
simply replaced the old one. One misheard "I'm registered with CAC" could quietly drop a step from
someone's plan, and nobody could tell afterwards how it happened.

The fourth was **the summary**. There was one three-line summary per user, so each new chat
overwrote the note from the previous one. It also sat in the memory block right next to the facts,
as if it were equally reliable, even though an AI wrote it.

## Decision

I now treat memory as four separate kinds. Each one answers a different question and gets its own
storage, size limit and level of trust.

**Working memory** is what the model sees on a single reply: the rules, the memory block, the recent
messages and fresh tool results. It's kept small by the compaction hook, which trims old tool
results after every turn, and by Bedrock prompt caching of the fixed rules.

**Short-term memory** is the current chat. Strands still saves it after every message, but now into
the database (`chat_sessions`, `chat_agents`, `chat_messages`) through my own session repository
instead of into files. The rolling summary from ADR 0008 now has one simple rule: once the
whole context window (rules, tool list and conversation) reaches about 24,000 tokens, the last **5 turns**
stay word for word and everything older is summarised. Tokens decide when, because they are what costs
money and slows replies, and a few turns with big checklists can cost more than thirty short ones.
Counting turns rather than messages for what to keep means the user's recent exchanges stay whole,
because one turn can contain several tool calls and results.

**Long-term memory** holds the confirmed facts, and it's now organised per business. One user can
have up to ten businesses. Each has a label ("zobo business", "Lagos pharmacy") and its own facts,
checklist, progress and reminders. Every fact is stored with its source (`user_stated`,
`progress_update`, `migrated` or `seeded`), the chat it came from and the time, and every change is
copied into `fact_history`. If the model tries to save a value that contradicts a stored one, nothing
is saved. The tool replies `FACT_CONFLICT` instead, and Navi has to ask the user and then call it again
with `confirm_change=true`.

**Episodic memory** is a three-line note per chat (`episodes`), written in the background by Claude
Haiku. The last three notes appear in the memory block, under their own heading, labelled as
possibly incomplete. If a note disagrees with a fact, the fact wins.

Underneath all four, the app database can now be **SQLite or Postgres**. A small layer
(`agent/storage/database.py`) hides the difference, and numbered migrations
(`agent/storage/migrations.py`) create or upgrade the tables. An empty `DATABASE_URL` means a local
SQLite file. A Postgres address means production.

Finally, users now **control their data**. They can view and export everything stored about them, and
delete one business or everything. Users who haven't visited for `MEMORY_RETENTION_DAYS` (365 by
default) are deleted automatically.

## Why I chose this

Splitting memory by job is what lets each part be both cheap and trustworthy. The facts that plans
are built from need to be exact and confirmed, so they live in typed rows with a source. The notes
only need to help Navi pick up the thread, so they can be AI-written, as long as they're labelled
and can never override a fact.

Keeping businesses as their own records fixed the multi-business bug at its root. The planner itself
didn't change at all; it's simply called once per business. Tools refuse to guess. When a user has
several businesses and the model doesn't say which one, the tool sends back the list of labels
instead of picking one, because guessing is exactly how a step gets recorded against the wrong
business.

Postgres was the obvious production choice. I only have Bedrock on AWS, and managed Postgres is
available everywhere else: Render, Neon, Supabase. It survives restarts, can be shared by several
servers, and is backed up. Keeping SQLite for local development means nothing has to be installed to
work on the project. Writing ordinary SQL with `?` placeholders, translated for Postgres, kept that
dual support down to one small file.

Storing the chat history through Strands' own `SessionRepository` interface meant the agent loop, the
hooks and the rolling summary didn't need to change. Strands still decides what to save and when; I
only changed where it goes.

## What I considered instead

**SQLAlchemy** would have handled both databases too, but it adds a large dependency and a new way of
writing queries. Our queries are simple, so a thin translation layer was easier to read.

**Amazon Bedrock AgentCore Memory** is a managed memory service. It's separate from model access,
though, and my AWS access only covers Bedrock models. It would also have hidden the fact-versus-note
distinction that matters so much here.

**Letting the AI extract and store memories automatically** (in the style of Mem0) would remember more,
but in a regulated domain one wrong remembered fact gives a wrong plan. I kept the rule that only
facts the user actually stated, from a fixed list, are saved.

**A searchable vector store of past conversations** would let Navi answer "what did you tell me about
NAFDAC last month?". Nobody needs that yet, and the profile, checklist and notes cover what users
actually come back for. It can be added later.

**Keeping one profile per user and asking users to start a new account per business** would have
avoided the schema change, but it would have been confusing, and the agent still couldn't answer a
question that covers two businesses.

## Consequences

Memory now survives restarts and redeploys, more than one server can run at once, a user can plan
several businesses in one conversation, and every remembered fact can be explained. The memory block
is a little longer for users with several businesses, which costs a few more tokens per turn.

There are some new duties. Production needs a Postgres database and a daily run of
`scripts/purge_old_data.py`, or at least a restart now and then, since the server also cleans up on
start-up. The data-rights endpoints trust the `user_id` they're given, like the rest of the API, so
**real sign-in must be added before going live**. Chats saved as files by older versions aren't
imported, because they were test data; profiles, checklists and progress are carried across by
migration 2.

## Where to find it

- Database layer and migrations: `agent/storage/database.py`, `agent/storage/migrations.py`
- All reads and writes, plus export, delete and retention: `agent/storage/store.py`
- Chat history in the database: `agent/storage/chat_repository.py`
- Long-term memory per business, conflicts and sources: `agent/memory/long_term.py`
- Episodic notes: `agent/memory/summarizer.py`; size-based summary: `agent/memory/conversation_manager.py`
- New tool: `agent/tools/add_business.py`; the `business` input on the other tools
- Memory block and multi-business rules: `render_memory_block` and "MORE THAN ONE BUSINESS" in `agent/prompts.py`
- Data-rights endpoints: `server.py`; retention job: `scripts/purge_old_data.py`

## Update (2026-11-03): retiring businesses the user no longer uses

The user-level rule (delete everything after 365 days without a visit) left a gap: a user who keeps
chatting about a new business keeps their old, abandoned businesses forever. Each one is listed in full in
the memory block on every reply, which costs tokens, distracts Navi ("which business do you mean?"), and
keeps personal data longer than the NDPA expects.

So each business now has its own lifecycle, measured by a new **last used** date (migration 3). It's
updated whenever any tool works on the business (building its checklist, recording progress, setting a
reminder, saving a fact or answering about it), not only when its facts change. Otherwise a business
someone checks every month without changing anything would look abandoned.

- **Unused for 6 months** (`BUSINESS_INACTIVE_DAYS=180`): marked **inactive**. It's kept, but the memory
  block shows it as a single line (name, kind, state, last used) instead of all its details.
- **Unused for 18 months** (`BUSINESS_DELETE_DAYS=540`): **deleted** with its facts, history, progress,
  checklist and reminders. I chose 18 months rather than 12 because licences renew yearly, and a real
  business can be quiet for eleven months and then come back for its renewal.
- A business with a **reminder still in the future** is never made inactive or deleted.

Using an inactive business brings it straight back with everything intact. Two layers stop Navi from
creating an empty duplicate when the user returns to one. First, the single line in the memory block tells
Navi the business exists; Navi can't search the database by itself, so without that line it would assume the
business is new. Second, `add_business` checks the user's inactive businesses first and reactivates a match
instead of creating a new one. Navi passes `force_new=true` only if the user confirms they really mean a
separate business. Finally, a request that doesn't name a business now uses the single active one, even if
inactive ones exist, instead of asking every time.

The clean-up runs with the user-level one, at server start-up and in `scripts/purge_old_data.py`. The
**My data** page labels inactive businesses, shows when each was last used, and states the rule in plain
words. Code: `retire_unused_businesses` and `touch_business` in `agent/storage/store.py`; `resolve`,
`add_business` and `_use` in `agent/memory/long_term.py`; `render_memory_block` in `agent/prompts.py`.

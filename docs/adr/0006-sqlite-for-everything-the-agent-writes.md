# ADR 0006: Store everything the agent writes in SQLite, separate from the knowledge

**Status:** Accepted · **Date:** 2026-10-26

## Context

The agent has to save things. It keeps each user's profile and checklist, records their progress,
sets mock reminders, logs human hand-offs and keeps a record of every tool call it makes. I had to
decide where all of that should live, and whether the agent should be allowed to write to the
knowledge database at all.

## Decision

The agent **only reads** from Neo4j. Everything it **writes** goes into one local SQLite file,
`data/runtime/navigator.db`:

| Table | What it stores |
|---|---|
| `user_memory` | Long-term memory per user: profile, language, last-session summary |
| `sessions` | Each chat's owner, title and last activity (for the sidebar) |
| `checklists`, `progress`, `reminders`, `handoffs` | The user's saved work and requests |
| `tool_calls` | Every tool call: name, inputs, status, full result, duration |
| `turns` | Tokens, cache use and response time per turn |

## Why I chose this

The main reason is safety. If the agent can't write to the knowledge database, then no bad or
model-written query can ever damage the graph. That separation is what makes the text-to-Cypher tool
safe to offer at all (ADR 0005).

It also helps with privacy. User data and the shared reference knowledge are kept apart, so a graph
query, however it's written, can never see another user's checklist.

SQLite is also simply easy to run. It's one file, with no server and no setup, and it's more than fast
enough for this project.

And it's easy to inspect. All the evidence I needed for the report and the evaluation, from the tool
log to the token counts, sits in one file I can query directly.

## What I considered instead

**Storing user data in Neo4j as well** would have meant giving the agent write access to the
knowledge, and user data would have been mixed in with reference data.

**A hosted database such as DynamoDB or Postgres** would have added setup and cost that one local
agent doesn't need.

**Plain JSON files** were the simplest option of all, but they can't handle two writes at once safely
and they're awkward to query.

## Consequences

The design is safe, private, simple and easy to query. The limit is that SQLite works on a single
machine. A production version running on many servers would need a hosted database, but that is a
contained change, because all storage goes through `sqlite_store.py`.

## Where to find it

Every table, and the functions that read and write them, are in `agent/storage/sqlite_store.py`.
`agent/storage/neo4j_client.py` gives the agent read-only access; only ingestion writes to Neo4j.

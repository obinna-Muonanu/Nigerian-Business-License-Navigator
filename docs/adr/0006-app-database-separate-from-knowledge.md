# ADR 0006: Store everything the agent writes in its own app database, separate from the knowledge

**Status:** Accepted · **Date:** 2026-10-26 · Rewritten 2026-11-04 to describe the database Navi uses today. The move
to Postgres and the memory tables are explained in [0018](0018-production-memory.md)

## Context

The agent has to save things. It keeps each user's businesses, facts and checklists, records their progress, sets mock
reminders, logs human hand-offs and keeps a record of every tool call it makes. I had to decide where all of that
should live, and whether the agent should be allowed to write to the knowledge database at all.

## Decision

The agent **only reads** from Neo4j. Everything it **writes** goes into a separate app database. That database is a
local SQLite file (`data/runtime/navigator.db`) when `DATABASE_URL` is empty, and Postgres when `DATABASE_URL` is set.
The same code runs on both, and numbered migrations create and upgrade the tables.

| Tables | What they store |
|---|---|
| `users`, `businesses` | Each user, and their businesses with status and last used date |
| `profile_facts`, `fact_history` | Confirmed facts with their source, and every change to them |
| `checklists`, `progress`, `reminders`, `handoffs` | The user's saved work and requests |
| `episodes` | The short note about each chat |
| `chat_sessions`, `chat_agents`, `chat_messages` | The chat history saved by Strands |
| `sessions` | Each chat's owner, title and last activity, for the sidebar |
| `tool_calls`, `turns` | Every tool call, and tokens, cache use and response time per turn |
| `schema_version` | Which migrations have been applied |

## Why I chose this

The main reason is safety. If the agent can't write to the knowledge database, then no bad or model-written query can
ever damage the graph. That separation is what makes the text-to-Cypher tool safe to offer at all (ADR 0005).

It also helps with privacy. User data and the shared reference knowledge are kept apart, so a graph query, however
it's written, can never see another user's checklist.

Using two engines suits two jobs. SQLite is one file with no server and no set-up, so nothing has to be installed to
work on the project. Postgres survives restarts and redeploys, and several servers can share it.

And it's easy to inspect. All the evidence I needed for the report and the evaluation, from the tool log to the token
counts, can be queried directly.

## What I considered instead

**Storing user data in Neo4j as well** would have meant giving the agent write access to the knowledge, and user data
would have been mixed in with reference data.

**SQLite only** was my first version, but on a hosted server its file can be wiped on every restart.

**Postgres only** would have made every developer set up a database just to run the project.

**DynamoDB** would have added another AWS service, and my AWS access only covers Bedrock models.

**Plain JSON files** were the simplest option of all, but they can't handle two writes at once safely and they're
awkward to query.

## Consequences

The design is safe, private and easy to query, and it works both on a laptop and in production. There are costs. The
code has to work on two database engines, which a small layer handles. Production needs a hosted Postgres database.
And a database far from the server slows replies, because each reply makes many database calls: the same lookup
questions took about 7 seconds with local SQLite and 15 to 17 seconds with Neon from a laptop.

## Where to find it

- Every read and write: `agent/storage/store.py`
- SQLite and Postgres support: `agent/storage/database.py`
- Tables and upgrades: `agent/storage/migrations.py`
- Chat history: `agent/storage/chat_repository.py`
- Read-only access to the graph: `agent/storage/neo4j_client.py` (only ingestion writes to Neo4j)

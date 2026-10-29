# ADR 0015: Read configuration through one validated Pydantic settings model

**Status:** Accepted · **Date:** 2026-10-27

## Context

All the settings, from AWS details and model IDs to the Neo4j connection and tuning values, come in
as plain text from `.env`. My first version read them by hand with `os.environ` wherever they were
needed. That meant a typo like `TOP_K=four`, or a missing password, wouldn't fail until much later,
deep inside a tool call, quite possibly in the middle of a demo.

It also stopped at the first missing variable. If three things were wrong, I had to fix one, restart,
hit the next error, fix that, and restart again.

## Decision

I moved all configuration into one Pydantic settings class in `agent/config.py`, and made it the only
place in the project that reads environment variables. Everything else calls `get_settings()`.

The class converts and checks every value when the app starts. `AGENT_MODEL_ID`, `NEO4J_URI` and
`NEO4J_PASSWORD` are required. Numbers have to be in range: `MIN_RELEVANCE` between 0 and 1, `TOP_K`
between 1 and 20, and `KEEP_RECENT_MESSAGES` at least 2. `EMBED_DIMENSIONS` must be 256, 512 or
1024, the sizes Titan supports. And `NEO4J_URI` has to start with `neo4j://`, `neo4j+s://` or
`bolt://`.

If anything is wrong, every problem is reported at once, in one readable message. Passwords and keys
show up as `**********` in logs and errors, and the settings can't be changed once the app is running.

## Why I chose this

A bad `.env` is caught the moment the app starts, and the error names the variable, so there's no
hunting through a stack trace.

One message lists everything that needs fixing, instead of one restart per problem.

Secrets can't leak into logs or error messages by accident.

And the rest of the code stays simple, because it gets properly typed values from one place.

## What I considered instead

**`os.environ` with manual conversion** was my first version. It gave confusing errors, one problem
at a time, and had no range checks.

**A plain dataclass** would have kept things in one place, but without automatic validation or
secret hiding.

## Consequences

Start-up errors are clearer and secrets are handled more safely. It does mean one extra package,
`pydantic-settings`.

There were two small surprises along the way. First, Pydantic doesn't copy `.env` values into the
process environment, so boto3 can't find AWS keys there on its own. I pass them to it explicitly in
`agent/llm/bedrock.py`. Second, `EMBED_DIMENSIONS` is defined as a number with a separate check,
because Pydantic won't convert the text "1024" when matching it against a fixed list of numbers.

## Where to find it

Everything is in `agent/config.py`. `.env.example` lists every setting with a comment explaining it.

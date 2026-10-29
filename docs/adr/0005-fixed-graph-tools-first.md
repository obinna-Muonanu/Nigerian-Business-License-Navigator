# ADR 0005: Use fixed graph queries first; text-to-Cypher only as a guarded extra

**Status:** Accepted · **Date:** 2026-10-26

## Context

There are two ways to let an AI use a graph database. You can give it fixed tools, such as "get the
requirements for this business in this state", each backed by a query you wrote yourself. Or you
can let it write its own database queries in Cypher.

Model-written queries are flexible, but they can be wrong, they can be slow, and in the worst case
they can try to change or delete data. The brief's guidance was to start with fixed tools, and if you
do let the model write queries, to validate them first and run them read-only.

## Decision

The everyday work is done by fixed tools: `get_requirements`, `get_dependencies`, `plan_steps` and
`explain_path`. Each one runs a query I wrote and tested in advance, with the user's details passed
in as parameters.

On top of that, I added `query_graph`, a text-to-Cypher tool, as a stretch-goal extra for unusual
questions such as "which regulator issues the most permits?". I don't trust anything it writes, so
every query goes through four checks.

First, a validator rejects any write or admin keyword (`CREATE`, `MERGE`, `DELETE`, `SET`, `CALL`
and so on), more than one statement, or any label that isn't in the graph, and it adds a `LIMIT`.
Second, the query is run with `EXPLAIN`, so Neo4j checks the syntax without running anything. Third,
it runs in a READ transaction with a 5-second timeout, so Neo4j itself refuses any write, even one
the validator missed. Fourth, if anything fails along the way, the tool tells the agent to fall back
to the fixed tools.

## Why I chose this

Fixed queries are predictable. The same user profile always produces the same plan, which is what
you want from a licensing guide, and it also makes the evaluation repeatable.

They are also fast and safe. There's no chance of a badly written query timing out or touching data.

Most importantly, the planning logic lives in Python that I can test: which steps apply to this user,
and in what order. I didn't want that logic to depend on a query the model improvises on the spot.

The guarded extra still delivers the stretch goal and covers questions the fixed tools don't, without
handing the model the keys to the database.

## What I considered instead

**Text-to-Cypher only** would have made the answers unpredictable, and it would have been risky
without heavy checks.

**No text-to-Cypher at all** would have been the safest option, but it would have missed the
stretch goal and left the agent unable to answer unusual questions about the graph.

## Consequences

The main path is reliable, there's flexibility where it's useful, and the safety comes in layers so
no single check has to be perfect. The validator is deliberately cautious, so it may occasionally
reject a harmless query. When that happens, the agent just falls back to the fixed tools.

## Where to find it

The fixed queries and the planner are in `agent/knowledge/graph_service.py`. Validation, `EXPLAIN`
and the read-only run are in `agent/knowledge/cypher_guard.py`. `read()` in
`agent/storage/neo4j_client.py` always uses a READ transaction.

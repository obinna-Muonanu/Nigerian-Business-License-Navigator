# ADR 0016: A modular code layout, with one file per tool

**Status:** Accepted · **Date:** 2026-10-26

## Context

An agent mixes a lot of concerns: configuration, prompts, models, storage, knowledge, memory, tools
and safety rules. If they're all tangled together, the code becomes hard to read, hard to test and
hard to change, and it's difficult to walk someone through it in a review.

## Decision

I followed the course's modular AI framework and split the `agent/` package by concern. I also gave
every tool its own file.

```
agent/
  config.py      the only module that reads .env           (ADR 0015)
  prompts.py     every prompt in one place
  schemas.py     shared vocabularies and data models
  core.py        builds the agent and streams one turn
  llm/           Bedrock models and embeddings              (ADR 0014)
  storage/       SQLite and Neo4j clients                   (ADR 0003, 0006)
  knowledge/     graph planning, vector search, Cypher guard, citations
  memory/        short-term, long-term, summaries           (ADR 0007, 0008)
  tools/         ONE FILE PER TOOL + __init__.py registry   (ADR 0002)
  hooks/         the policy layer                           (ADR 0009)
ingestion/       build the graph and the vector index (offline)
evaluation/      datasets, judge, runner, results           (ADR 0017)
server.py · main_agent.py · ui/streamlit_app.py
```

The tools are deliberately thin. Each one reads the user's state and calls a service in `knowledge/`
or `storage/`, and those services know nothing about the agent.

## Why I chose this

Each file has one job, so it's easy to find things and easy to explain them.

One file per tool means each tool can be read on its own, and adding or removing one is simple. The
registry in `tools/__init__.py` still shows them all in one place, grouped by what they're for.

Keeping the services separate from the tools means the real logic can be tested without an agent or a
model call. The evaluation takes advantage of this: it uses `graph_service` directly to compute the
gold answers.

And because it matches the course structure, it's familiar to anyone reviewing it.

## What I considered instead

**A few large files** would have been hard to navigate, and a change in one place could easily affect
unrelated code.

**Several tools per file**, which is how my first version grouped them, made it harder to find and
review a single tool. I split them up when that was pointed out.

## Consequences

The code is readable, testable and easy to extend. Adding a tool means one new file and one line in
the registry. The price is more files to open, so each module starts with a docstring and the code
is commented to explain what each part does and why.

## Where to find it

The structure above is the project itself. `agent/__init__.py` and `agent/tools/__init__.py` describe
the layout.

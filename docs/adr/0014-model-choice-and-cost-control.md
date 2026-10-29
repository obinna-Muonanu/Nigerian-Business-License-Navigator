# ADR 0014: Claude Haiku for the agent, Sonnet for extraction and judging, plus caching

**Status:** Accepted · **Date:** 2026-10-27

## Context

A single user message can turn into several model calls: the agent reasons, calls a tool, reasons
again, calls another tool and finally answers. Each of those calls re-sends the system prompt, the
tool list and the conversation so far. Running the most capable model for all of that would get
expensive quickly. But running the cheapest model for everything could make the graph, or the
grading of the evaluation, unreliable.

## Decision

I matched each job to the model it actually needs:

| Job | Model | Why this model |
|---|---|---|
| The agent (conversation, tools, Pidgin) | **Haiku 4.5** | Good at tool use, fast, and much cheaper |
| Session summaries, text-to-Cypher | Haiku 4.5 | Small, simple jobs |
| Graph extraction (once, offline) | **Sonnet 4.5** | Mistakes here affect every checklist |
| Evaluation judge | **Sonnet 4.5** | A stronger, separate model grading a cheaper one keeps scores trustworthy |
| Embeddings | Titan Text Embeddings V2 | Bedrock's embedding model |

On top of that, I cut the cost of every turn in a few ways.

The biggest saving is prompt caching. The system prompt and the tool definitions are the same for
every user, so Bedrock can read them from its cache instead of processing them fresh. I put the
user-specific memory block after the cache point, so the cached part is shared by everyone.

A compaction hook shortens old tool results, which are mostly long document chunks, after each turn.
The tools themselves keep their output small: four chunks per search, compact JSON, and the diagram
data kept out of the model's view entirely.

Finally, replies are capped at 4,000 tokens. I raised that from 1,500 after a long checklist got cut
off mid-reply. Only the tokens actually generated are billed, so the higher cap costs nothing on
short replies. If the cap is ever hit, the reply ends by asking the user to say "continue" instead of
crashing.

## Why I chose this

Most of the cost comes from the conversation, so that's where a cheaper model pays off the most.

Using a cheaper model doesn't weaken safety, because the rules are enforced in code by the hooks, not
by the model's good behaviour (ADR 0009).

And it spends accuracy where it matters. The graph is built only once, so paying for Sonnet there is
cheap and protects every checklist. The judge has to be trustworthy, or the evaluation means nothing.

## What I considered instead

**Sonnet for the agent** would have cost several times as much per turn, and Haiku passed every tool
and safety test anyway.

**Haiku for everything** would have meant a weaker extractor and a weaker judge, which would make the
graph and the scores less reliable.

## Consequences

Running costs are low, safety is held by the code, and the grading can be trusted. The trade-off is
that Haiku follows long instructions less reliably than Sonnet, which is why I added the short
per-message notes (ADR 0009, ADR 0012). If that ever becomes a problem, switching the agent's model
is a single line in `.env` (`AGENT_MODEL_ID`).

## Where to find it

The models, caching and token cap are set up in `agent/llm/bedrock.py`, and compaction is in
`agent/hooks/compaction.py`. The model IDs live in `.env`.

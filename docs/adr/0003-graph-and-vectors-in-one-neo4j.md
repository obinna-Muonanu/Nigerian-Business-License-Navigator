# ADR 0003: Keep the knowledge graph and the vector search in one Neo4j database

**Status:** Accepted · **Date:** 2026-10-26

## Context

The brief asks for two kinds of knowledge, and they answer different questions.

The **graph** answers "what do I need, and in what order?" That answer depends on connections that
run across many documents. CAC registration comes before tax registration, which comes before the
state permit, and no single paragraph spells out the whole chain.

**Document search (RAG)** answers the detail questions: how much does it cost, which forms do I
need, how long does it take? Those answers sit in the text of the documents themselves.

The usual setup is two databases, a graph database for the first job and a separate vector database
for the second. I had to decide whether this project really needed both.

## Decision

I put everything in **one Neo4j AuraDB** database.

The graph side has `BusinessType`, `Requirement`, `Regulator`, `RequiredDocument` and `State` nodes,
connected by `REQUIRES`, `DEPENDS_ON`, `ISSUED_BY`, `NEEDS_DOCUMENT` and `APPLIES_IN`. There is also
`SATISFIES` for the four different routes to CAC registration.

The document side has `Chunk` nodes, each holding a piece of text and its embedding, searched through
a Neo4j vector index. Each chunk is linked to its `Document`, which records the title, the date I read
it and the official link.

The two sides meet through `(Chunk)-[:DESCRIBES]->(Requirement)`, which connects a piece of text to
the step it is about.

## Why I chose this

The biggest reason is that one query can use both sides. I can find a paragraph by meaning and then
follow the graph from the requirement it describes. With two databases I would have had to match
results by name in Python, which breaks as soon as a document words a name slightly differently.

It also made citations consistent. Every chunk knows its document, section, date read and official
link, so every answer can be cited the same way (ADR 0011).

It made the experiment fairer, too. The vector-only baseline searches exactly the same index as the
GraphRAG agent. The only difference between the two is the graph, which is exactly what the
experiment is meant to measure.

And there is simply less to run: one database, one connection and one loading script. Neo4j AuraDB
Free supports vector indexes, so it cost nothing.

## What I considered instead

**Neo4j plus a separate vector database such as Chroma** was the obvious alternative. It would have
meant two stores to load and keep in sync, and joining their results would have needed that fragile
name matching.

**A vector database on its own** couldn't reliably answer "in what order?". It only finds paragraphs
that look like the question, and the order isn't written in any one paragraph.

**Amazon Neptune or OpenSearch** would have worked, but they mean more AWS services, more setup and
more cost than this project needs.

## Consequences

The system is simpler, answers can join facts from the graph and the documents, citations are
consistent, and the baseline comparison is fair. The trade-off is that everything depends on one
database: if Neo4j is down, both the graph and the search are down. The `/health` endpoint reports
that clearly, so it's easy to spot.

## Where to find it

`ingestion/load_graph.py` creates the graph, the chunks and the vector index. The graph queries live
in `agent/knowledge/graph_service.py`, and vector search in `agent/knowledge/retrieval_service.py`.

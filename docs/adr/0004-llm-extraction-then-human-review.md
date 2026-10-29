# ADR 0004: Build the graph with an LLM, then check it by hand

**Status:** Accepted · **Date:** 2026-10-26

## Context

The graph is only as good as its data. If a single "must be done after" link is wrong, every
checklist built on top of it is wrong too, and the user ends up going to the wrong regulator first.

There were about 70 requirements across 9 documents, each with its own prerequisites, documents and
conditions. Typing all of that in by hand would have been slow, and I would almost certainly have
made mistakes. Letting an AI build the graph unchecked was risky in a different way. The brief's
advice settled it: build it with an LLM, then check it by hand.

## Decision

I built a three-step pipeline: extract, review, then approve and load.

First, `extract_graph.py` sends each document to Claude Sonnet and asks it to fill in a strict form
(`ExtractedDocumentGraph`). For every requirement the model has to give the ID, name and regulator,
the business types it applies to and under which condition, the states, the prerequisites (each with
a reason), the documents needed, and whether the step repeats.

Second, the same script writes a `review_report.txt`. It compares the model's output with a simple
rule-based reading of each document's "Must be done after" line, and lists anything suspicious:
missing requirements, dependencies the two disagree on, links to IDs that don't exist, and loops.

Third, once the review is done, running the script with `--approve` copies the file to
`reviewed.json`. Only `reviewed.json` is ever loaded into Neo4j.

## Why I chose this

The strict form stops the model from inventing structure. Business types, states and conditions come
from fixed lists, so a made-up code is rejected straight away instead of quietly ending up in the
graph.

The review report makes the human check fast. Instead of reading 70 requirements blind, I could start
with the handful the report flagged and then work through the rest.

I also asked for a reason on every dependency. That means the agent can explain why a step comes
first using the regulator's own words (`explain_path`), rather than just asserting it.

And the separate approve step means unchecked data can never reach the agent by accident. If I re-run
the extraction, nothing changes for the agent until I approve the new version.

## What I considered instead

**Writing the whole graph by hand** was too slow and error-prone for about 70 requirements and their
links.

**Parsing the documents with rules alone** looked tempting, but the conditions are written in prose
("when one person owns the business"), and rules handle prose badly.

**Using the LLM output without a review** was ruled out by the brief, and it would have been a bad
idea anyway, since one wrong link breaks every plan built on it.

## Consequences

The graph was quick to build, it is consistent and explainable, and it's easy to rebuild when the
documents change. The weak point is that the review is only as good as the reviewer.

### Review result (2026-10-27)

The automatic review report flagged no issues: no missing requirements, no disagreeing dependencies,
no links to unknown IDs and no loops. I then checked the extracted graph by hand against the
knowledge-base documents in Neo4j Browser and found it correct.

No corrections were needed, so `reviewed.json` is identical to `extracted.json`. That is what a
review that finds nothing to fix looks like; it doesn't mean the review was skipped.

## Where to find it

Extraction and the review report are in `ingestion/extract_graph.py`, and loading is in
`ingestion/load_graph.py`. The extraction form is defined in `agent/schemas.py` and its prompt in
`agent/prompts.py` (`EXTRACTION_PROMPT`). The approved graph is `data/graph/reviewed.json`.

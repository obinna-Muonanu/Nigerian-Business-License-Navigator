# ADR 0021: Give every regulator and required document one standard name

**Status:** Accepted · **Date:** 2026-11-03 · Builds on [0004](0004-llm-extraction-then-human-review.md)

## Context

Claude extracted the graph one document at a time, and it wrote names in its own words each time. The
same thing in reality came out under several spellings, and each spelling became its own node:

- **Regulators:** 21 nodes for 15 real bodies. "CAC" and "Corporate Affairs Commission (CAC)" were two
  nodes, NAFDAC appeared three times ("NAFDAC", "NAFDAC laboratory", and a long description), and most
  state revenue services appeared both with and without their abbreviation.
- **Required documents:** 135 nodes, of which 118 were linked to only one step. "Evidence of payment",
  "Receipt of payment", "Proof of payment for certification" and seven others were all the same idea.

The review in ADR 0004 checked the steps and their order, which were correct. It didn't check whether
names were consistent. The cost showed up in questions that cross documents: "which steps need proof of
payment?" or "what does NAFDAC handle?" only found the steps that happened to use one spelling.

## Decision

A reviewed list, `data/graph/canonical_names.json`, maps every extracted name to one standard name: 21
regulator names to 15, and 135 document names to 52. Every extracted name is listed explicitly, and I
checked the groupings by hand.

`ingestion/load_graph.py` applies the list when it builds the graph. The original wording isn't lost: each
`NEEDS_DOCUMENT` link keeps it in a `details` property (for example, the step "MSME cosmetics
registration" links to the standard "Proof of payment", with the details "Receipt of payment for
production registration"). `reviewed.json` itself is unchanged, so the extraction stays a faithful
record of what the documents said.

The review report in `ingestion/extract_graph.py` now also flags any name that isn't on the list, so a
future re-extraction can't quietly bring the duplicates back: a person adds the new name to the list
before the graph is approved.

## Why I chose this

A **reviewed mapping file** keeps the human in charge, like the rest of the graph review. It's easy to
read, easy to correct, and it records exactly which spellings were merged.

Keeping the original wording on the link means nothing the documents say is thrown away. The standard
name is for finding things; the details are for telling the user exactly what to bring.

## What I considered instead

**Asking the extraction prompt to use standard names** helps, but it can't be relied on across separate
calls, and it would mean re-running and re-reviewing the whole extraction.

**Merging names automatically by similarity** (embeddings or fuzzy matching) would merge things that only
look alike, such as a "Certificate of analysis" and a "Certificate of manufacture and free sale". For a
compliance tool a wrong merge is worse than a duplicate.

## Consequences

The knowledge graph went from 238 to 149 nodes and from 861 to 837 relationships (275 nodes and 1,040
relationships including the 117 chunks and 9 source documents). The steps, their order and their
dependencies (72 requirements, 83 dependencies) are unchanged. Only 25 documents are now linked to just
one step, down from 118.

The cost is one more file to maintain: when the documents change, new names must be added to the list.
The review report makes that impossible to miss.

**To undo it,** move `canonical_names.json` aside and run `python -m ingestion.load_graph --reset`; the
loader then uses the names exactly as extracted.

## Where to find it

The list is `data/graph/canonical_names.json`, read by `ingestion/canonical.py`. The loader is
`ingestion/load_graph.py`, and the review check is in `ingestion/extract_graph.py`.

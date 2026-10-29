# ADR 0011: Cite sources as numbered footnotes, and never show internal IDs

**Status:** Accepted · **Date:** 2026-10-27

## Context

The brief requires every answer to show where it came from, naming the document and the section. My
first attempt put the citation inline, like
`[NAFDAC requirements ... > Requirement: NAFDAC product registration, read 2026-10-24]`. It met the
requirement, but it looked like code in the middle of a sentence and was hard to read.

There was a second, related problem. Internally, every requirement has an ID such as R01, D05 or
S-OY-01, and the agent kept writing those IDs into its replies. They mean nothing to a business owner.

## Decision

For citations, I switched to numbered footnotes. Each fact gets a marker like [1], and a short
**Sources** list at the end gives the document, the section and an "information as of" date, plus
the official link. The tools hand the model a ready-made source line, so it copies it rather than
writing its own, which keeps every citation consistent. Checklists cite one line per document rather
than one per step, so a 20-step plan ends up with about five sources.

For the IDs, I used three layers. The prompt says IDs are for tool calls only. The tools return a
name next to every ID, so the model always has something better to write. And a stream filter removes
any ID that still slips through, while the reply is streaming.

## Why I chose this

Footnotes meet the brief in a way people can actually read. They name the document and section, and
the "information as of" date matters because fees change.

They're also consistent and checkable. Both the grounding hook and the evaluation check that each [n]
marker has a matching line in the Sources list.

The filter is what makes the ID rule a guarantee. Even when the model slips, the user never sees an
ID.

## What I considered instead

**Inline bracket citations** were my first version, and they were hard to read mid-sentence.

**One citation per checklist step** made replies far too long, with 20 or more source lines.

**A prompt rule alone for the IDs** wasn't enough. The model still slipped now and then.

## Consequences

Answers are clean and still meet the citation requirement. The only cost is that the filter holds
back the last few characters of the stream so that an ID split across two chunks is still caught.
The delay is too small to notice.

## Where to find it

Source lines are built in `agent/knowledge/citations.py`, and the ID filter is
`agent/output_filter.py`. The citation check is `has_citation` in `agent/hooks/grounding.py`, and the
citation rules are in `agent/prompts.py`.

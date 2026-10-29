# ADR 0017: Evaluate with a fair baseline, gold answers from the reviewed graph, a judge and hard checks

**Status:** Accepted · **Date:** 2026-10-27

## Context

The brief asks for 20 to 30 RAG questions, 10 tool scenarios and 5 safety cases. Most importantly, it
asks for a comparison between plain vector RAG and GraphRAG, to show whether the graph actually
helps.

Grading more than 80 answers by hand would have been slow, and I would have graded them
inconsistently. Grading them with an AI alone has its own risk: a polite, confident answer can fool a
judge even when it's wrong. And an AI judge reading the reply can't see what the agent actually did
behind the scenes.

## Decision

I tested the agent with four suites:

| Suite | Size | How it is graded |
|---|---|---|
| **Comparison** (the key experiment) | 15 questions × 2 modes | Judge, against gold material |
| RAG | 31 questions (6 Pidgin messages across the suites) | Judge, against the expected document section |
| Tool scenarios | 11 scripted chats (incl. the 7 demo scenarios) | Hard checks: did the right tools actually run, and no false "done" claims |
| Safety | 5 attack cases | Hard checks (no forbidden tool ran, no leaked text or numbers, no invented ₦ amounts) and the judge |

So answers are graded by an independent judge model against gold material, and behaviour is checked
with deterministic checks against the audit log: which tools ran, and what, if anything, leaked.

I set some rules to keep the comparison fair. The only difference between the two modes is the
graph: same model, same documents, same vector index and same prompt. Every case starts as a
brand-new user with their profile pre-loaded, so no case can affect another. The gold answers are
computed from the hand-reviewed graph with no AI involved, and they're written as each step's
prerequisites, so any valid order counts as correct. The judge is Sonnet, a stronger model than the
agent, and it has to grade only against the gold material on a fixed 0/1/2 scale. And the hard checks
read the audit log, which records what really happened, not the model's own account of it.

## Why I chose this

It's repeatable. One command re-runs any suite, and the results are saved twice: as Markdown to read,
and as JSON with every answer, verdict and tool call.

It's trustworthy, because the two kinds of grading cover each other's blind spots. The hard checks
catch what a judge might miss, and the judge handles what rules can't, such as whether an answer is
complete.

And it earned its keep by finding real bugs. The ignored "yes", the "out of scope" refusals made
without searching, the withheld answer and the false "saved" claim were all caught by the evaluation
and fixed. They're listed in the experiment report.

## What I considered instead

**Grading by hand** would have been slow and inconsistent for more than 80 answers.

**Using a judge only** could be fooled by a confident wrong answer, and it can't see which tools ran.

**A single numbered gold order** was my first version. It penalised answers that used a different but
perfectly valid order, so I replaced it with prerequisite-based gold.

## Consequences

The result is honest, repeatable evidence and a clear story for the report. It does have limits, and
I've stated them in the report. There are only 5 questions per category, so the differences should
be read as a direction, not a precise measurement. The gold answers come from the same graph that
GraphRAG uses. The judge only sees the expected section, so it may flag a correct fact from a nearby
section as "invented". And scores vary a little from run to run.

## Where to find it

The runner is `evaluation/run_eval.py`, the judge is `evaluation/judge.py`, and the datasets are in
`evaluation/datasets/`. Results are saved in `evaluation/results/`, and the write-up is
`evaluation/EXPERIMENT_REPORT.md`.

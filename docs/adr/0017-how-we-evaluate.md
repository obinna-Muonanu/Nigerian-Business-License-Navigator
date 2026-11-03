# ADR 0017: Evaluate with a fair baseline, gold answers from the reviewed graph, a judge and hard checks

**Status:** Accepted · **Date:** 2026-10-27 · Updated 2026-11-03 (run-to-run noise, and the judge's order verdicts)

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
| Safety | 12 cases (10 attacks, 2 normal questions) | Hard checks (no forbidden tool ran, no leaked text or numbers, no invented ₦ amounts) and the judge |

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

## Update (2026-11-03): single runs are too noisy to compare small changes

While trying to improve the checklist categories, I ran the 10 checklist questions of the key experiment
(5 "what do I need, in what order?" and 5 "I've done X, what's left?", GraphRAG only) after each change:

| Version | What do I need: correct / valid order | What's left: correct / valid order |
|---|---|---|
| Unchanged, first run | 80% / 4 of 5 | 70% / 4 of 5 |
| "Name every step" rule | 70% / 2 of 5 | 70% / 4 of 5 |
| Planner stages + dependency-first sort | 80% / 4 of 5 | 70% / 3 of 5 |
| + completed steps named in the memory block | 80% / 3 of 5 | 60% / 3 of 5 |
| Unchanged + step names only (kept) | 70% / 2 of 5 | 70% / 3 of 5 |

The first and last rows differ only in how completed steps are named in the memory block, yet one category
moved from 4 to 2 valid orders. With five questions per category, one answer moves a score by 10 to 20
points, and the model writes each checklist slightly differently every run. **Differences this size are
noise.** To compare versions fairly, each question should be run at least three times and the results
averaged, or the checklist should be produced by code so it doesn't vary between runs.

What the judge's explanations did show:
- **Order errors come from the model rearranging the planner's list,** for example moving conditional steps
  into their own section. The planner's own order was checked and is valid.
- **Asking for complete lists made them longer** (one answer covered "all 33 steps"), but longer lists gave
  more chances to misplace a step.
- **Sorting purely by dependencies** moved yearly steps such as "CAC annual returns" into early stages, which
  the judge marks as wrong.
- **Naming completed steps in the memory block** fixed a repeatable failure. A user saying "I've done the
  facility setup" was mistaken for a different step, and Navi held back the whole checklist to ask about it.
  This change was kept; the others were reverted.

The most promising next step is to have **code render the checklist** from the planner's output (stages,
order and markers), with Navi adding only the explanation around it. Order and completeness would then be
guaranteed and identical in every run.

## Update (2026-11-03): don't trust the judge on order

The latest full run gave GraphRAG only 2 of 5 for valid order in both checklist categories, down from 4 of 5 and 5
of 5. When I read the judge's reasons, some described mistakes that weren't in the reply. On one question it said
laboratory analysis came before the facility inspection, but the reply has the inspection at step 9 and the analysis
at step 10.

So I checked the order with code: find each step's name in the reply, then check that no step comes before something
it depends on in the reviewed graph. The code found **no order mistakes in any of the 10 GraphRAG checklists**.

**What this means:**
- Order should be checked by code, because it's a yes-or-no fact that code can get right every time. This check was a
  one-off and should be added to `run_eval.py`.
- Some of the order results in the table above came from the judge, so they may have been wrong too.
- The judge's correctness grades may contain similar mistakes, so read its reasons before trusting a surprising score.
- The code check has a limit: it only sees exact step names.

Also, the "about 40% fewer input tokens" reported earlier doesn't match the saved numbers. Adding them up the same way
for both runs gives 19% on 27 October and 13% on 3 November.

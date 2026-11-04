# Key experiment: vector-only RAG vs GraphRAG

**Question asked by the brief:** does adding a knowledge graph help an agent answer licensing questions,
compared with retrieving from the same documents with vector search alone? Where does it help, and where
does it make no difference?

**Short answer:** the graph **didn't help simple lookups** and **helped on the questions that depend on
connections between documents**: "what do I need, and in what order?" and "I have done X, what is left?". The
answers were more complete and always in a valid order. The graph also needed 85% fewer document searches and
about 18% fewer input tokens per turn.

This report was updated on 4 November 2026 with the latest run.

Raw results: `evaluation/results/20261104-184740_comparison_both.md` (and `.json` for every answer).

---

## 1. What was compared

| | Vector-only baseline | GraphRAG navigator |
|---|---|---|
| Model | Claude Haiku 4.5 (Bedrock) | Claude Haiku 4.5 (Bedrock) |
| Documents | Same 9 summaries, same 117 chunks, same Neo4j vector index | Same |
| System prompt | Same, plus a short "baseline mode" note | Same |
| Tools | `vector_search` (+ `remember_profile`, `handoff_to_human`, `add_business`) | `vector_search` + graph tools (`plan_steps`, `explain_path`, `get_dependencies`, ...) |
| User profile | Pre-loaded into memory, identical for both | Same |

The **only** difference is access to the graph, so any difference in scores comes from the graph.

**15 questions, 5 per type** (`evaluation/datasets/comparison_questions.json`), over 5 business profiles
(zobo in Ibadan, pharmacy in Lagos, cosmetics importer in Lagos, furniture in Ogun, zobo sold online):

- **Lookup**: one fact from one document ("What is the CAC registration fee for a business name?")
- **Multi-step**: "What do I need, and in what order?"
- **Progress**: "I have done X. What is left?" (the completed steps are pre-recorded)

## 2. How the answers were scored

An independent judge (Claude **Sonnet** 4.5, a stronger model than the agent) graded every answer against
**gold material**:

- **Lookups**: the knowledge-base section that contains the answer.
- **Multi-step and progress**: the remaining steps and their prerequisites, computed directly from the
  hand-reviewed graph (no LLM involved). Any order that respects the prerequisites counts as correct.

| Score | Meaning |
|---|---|
| **Correctness 0 / 1 / 2** | wrong or not answered / partly right (missing or wrong items) / fully right |
| **Citation 0 / 1 / 2** | no sources / vague sources / right document and section |
| **Valid order** | the checklist never lists a step before something it depends on, counted by code (see section 3) |

Each table cell is the **average of 5 questions**. Multiply by 50 for a percentage (1.6 = 80%).

## 3. Results

| Question type | Mode | Correctness | Citation | Valid order (code) | Order (judge) |
|---|---|---|---|---|---|
| Lookup | Baseline | **1.80** (90%) | 2.00 | – | – |
| Lookup | GraphRAG | 1.60 (80%) | 2.00 | – | – |
| Multi-step | Baseline | 0.80 (40%) | 1.80 | 3/5 | 1/5 |
| Multi-step | GraphRAG | **1.40** (70%) | 1.60 | **5/5** | 3/5 |
| Progress | Baseline | 0.80 (40%) | 1.00 | 4/5 | 3/4 |
| Progress | GraphRAG | **1.40** (70%) | **1.80** | **5/5** | 3/5 |

**Why there are two order columns.** The judge's order verdicts turned out to be unreliable. For example, in the
3 November run, on question M1, it said laboratory analysis was listed before the facility inspection, but the
reply listed the inspection at step 9 and the analysis at step 10. So I checked the order with code as well: for
each reply, find every step name, then check that no step appears before something it depends on in the reviewed
graph. This found no order mistakes in any of the 10 GraphRAG checklists, in this run or on 3 November. It is a
one-off check, not yet part of `run_eval.py`.

The code check has a limit: it only sees steps written with their exact names. The baseline replies name far
fewer steps (about 2 to 6 on average, against 8 to 14 for GraphRAG), so they have fewer chances to go wrong.

Per-question correctness (0–2):

| | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---|---|---|---|---|
| Lookup, baseline | 2 | 2 | 2 | 2 | 1 |
| Lookup, GraphRAG | 2 | 2 | 2 | 1 | 1 |
| Multi-step, baseline | 1 | 1 | 1 | **0** | 1 |
| Multi-step, GraphRAG | 1 | 1 | **2** | **2** | 1 |
| Progress, baseline | 1 | 1 | 1 | 1 | **0** |
| Progress, GraphRAG | 1 | 1 | **2** | 1 | **2** |

Effort across the same 15 questions:

| | Baseline | GraphRAG |
|---|---|---|
| `vector_search` calls in total | 34 | **5** |
| Average input tokens per turn (including cached) | 21,822 | **17,798** |
| Average time per turn (using Neon from a laptop) | 30.1 s | 31.2 s |

**Compared with 3 November.** GraphRAG's progress correctness went up from 50% to 70%, and multi-step stayed at
70%. Lookups went from 90% to 80% and multi-step citations from 100% to 80%, but neither is a real drop (see
section 5). Each category has only 5 questions and the model writes each reply differently, so one run can't
settle small changes. GraphRAG's time per turn went from 23.4 s to 31.2 s. I haven't found out why: its input
tokens rose by only about 3%, and database times from a laptop vary a lot. Times are also much longer than the
8.9 s measured on 27 October, because that run used a local database (see section 8).

An earlier version of this report said GraphRAG used about 40% fewer input tokens. Adding up the saved numbers the
same way gives 19% on 27 October, 13% on 3 November and 18% in this run.

## 4. Where the graph helped

**Multi-step questions: better coverage and order (40% → 70%, valid order 3/5 → 5/5).**
"What do I need, and in what order?" depends on connections across several documents: CAC registration comes
before tax, which comes before the state premises permit, which comes before the NAFDAC inspection, and so on.
Vector search returns the 4 closest paragraphs per search, so the baseline needed 2 to 9 searches on these questions
and still missed many steps. The graph returns the connected list in one call.

**Progress questions: better citations, coverage and order (citations 50% → 90%, correctness 40% → 70%).**
The graph knows every requirement for the profile, so `plan_steps` removes the steps already on record and returns
the rest with their sources. The baseline can only reason from retrieved paragraphs. It searched once on each of
these questions, and its replies named only about 2 steps on average. In the 27 October run, this gap was
much larger (30% → 80%), and the baseline's general knowledge led it to name the old tax agency, FIRS.

**Efficiency.** One graph call replaces several searches: 5 searches instead of 34 across the 15 questions, and
about 18% fewer input tokens per turn.

## 5. Where it made no difference

**Lookups (90% vs 80%).** A single fact ("the business-name fee is ₦10,000") lives in one paragraph, and both modes
find it with the same vector search, so no real difference is expected. The gap is one question, L4: the judge
called the data protection impact assessment "invented", but the reviewed graph requires that step for an online
cosmetics store. The two modes tied at 90% on 3 November.

**Multi-step citations (90% vs 80%).** This isn't a real win for the baseline. GraphRAG's replies list their sources
in the same way as on 3 November, when they scored 100%. Those source lines name the document but not the section,
so the judge can go either way on "vague". Adding the section to `plan_steps`' source lines would remove the doubt.

**Long checklists are still often only "partly right".** Most GraphRAG checklist answers scored 1, not 2, mainly
because Navi **shortens** long plans (20 to 30 steps) when writing the reply. The graph supplied every step; the
steps were lost when the model wrote the answer. Having code write out the checklist would close this gap.

## 6. Limitations (read the numbers as direction, not precision)

1. **Small sample.** 5 questions per type: one question moves an average by 0.4. Across the full runs GraphRAG
   stayed ahead on multi-step and progress correctness, but the exact numbers moved (GraphRAG multi-step
   correctness has been 1.4, 1.0, 1.0, 1.4 and 1.4; progress was 1.6 on 27 October, 1.0 on 3 November and 1.4 on
   4 November).
2. **The gold answers come from the same graph GraphRAG uses.** This favours GraphRAG on completeness.
   It is mitigated by the graph being extracted from the same documents the baseline searches and then
   checked by hand, but a fully independent gold list (written from the documents by a person) would be
   stronger.
3. **The judge sees only the expected section.** Some details it called "invented" may come from another
   section of the same document (for example the SON "60 days" timeline, flagged in both modes), and one, the
   impact assessment on L4, is confirmed by the reviewed graph.
4. **The judge is not perfect.** Its order verdicts are unreliable, so the valid-order counts above come from
   code. Its correctness grades could contain similar mistakes. Every verdict and reason is in the `.json` file
   for checking.
5. **One model.** Both modes used Haiku 4.5. A stronger model might narrow the gap on multi-step
   questions by searching more thoroughly, at a higher cost.

## 7. What changed during evaluation (so the results can be trusted)

Early runs exposed bugs in the agent itself, which were fixed before the final run. They are listed here
because they changed the scores:

| Problem found | Fix |
|---|---|
| The user's "yes" was ignored (the input guard's language note made "yes" look like a long message) | The confirmation check reads only what the user typed |
| The agent declared covered topics "out of scope" without searching | A per-message "search before saying you do not know" reminder |
| In progress questions, GraphRAG held back the answer while asking to record progress | Already-recorded steps pass without confirmation; `plan_steps(assume_done=...)` shows what is left at once and registers the confirmation itself |
| One reply claimed "Your checklist has been saved" when the save was blocked | A false-success-claim check now shows a correction and is part of every tool scenario |

## 8. Other evaluation results (4 November 2026)

The guardrail and Text-to-Cypher tests are from 3 November and weren't repeated. They don't depend on the prompt
changes made on 4 November.

| Test | Result | Report |
|---|---|---|
| Unit tests | **55/55 passed** | `pytest -q` |
| Safety cases (12) | **12/12 passed** | `20261104-192519_safety_both.md` |
| Tool scenarios (11, incl. the 7 demo scenarios) | **10/11 passed** (11/11 in the run before it) | `20261104-193408_tools_both.md` |
| RAG questions (31, incl. 6 in Pidgin across suites) | Correctness 1.87/2, citation 1.97/2, "I don't know" handled 2/2 | `20261104-183022_rag_graphrag.md` |
| Asking for a person (20 messages, one-off test) | 20/20 in two runs: requests 6/6, frustration 6/6, look-alikes 8/8 | ADR 0009 |
| Fixes checked 3 times each (one-off test) | Pidgin fact 3/3, medical tests 3/3, "why" question 3/3, honest "no" 3/3 | – |
| Guardrail alone (40 messages, one-off test) | Caught 9 of 15 attacks; wrongly flagged 3 of 25 normal questions | ADR 0020 |
| Text-to-Cypher retry (one-off test) | All checks passed | – |

**The one tool failure.** In scenario 3, Navi wrote "I've marked CAC business registration as done. Is that
correct?" while the save was still waiting for the user's yes. The check caught it: a correction appeared under the
reply, nothing was saved, and the save went through after the user said yes. The same scenario passed in the run
before it, so this slip happens sometimes.

**The honest "no" didn't search.** The export-licence question got a correct "outside what I cover" with no search.
The prompt allows this because exporting is listed as out of scope, but it means this test didn't exercise the new
"search a second time" rule.

**Reply time.** Using Neon from a laptop, lookup questions took 15 to 17 seconds per reply. With a temporary local
database, three of the same questions took about 7 seconds. Neon queries from the laptop took 0.6 to 5.8 seconds
each, and each reply makes many of them. A server in the same region as Neon should be much faster, but this hasn't
been measured yet.

## Conclusion

The graph helps exactly where the brief predicts. Vector search finds paragraphs that look like the
question, so it handles one-fact lookups well, and the graph adds nothing there. Questions whose answer
depends on how requirements connect across documents ("what do I need, in what order?", "what is left?")
need the graph: with it, the agent gave fuller, correctly ordered, cited plans, though it still shortens long ones.
Without it, the agent listed far fewer steps, put some out of order, and cited its sources less well on progress
questions.

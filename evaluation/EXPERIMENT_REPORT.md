# Key experiment: vector-only RAG vs GraphRAG

**Question asked by the brief:** does adding a knowledge graph help an agent answer licensing questions,
compared with retrieving from the same documents with vector search alone? Where does it help, and where
does it make no difference?

**Short answer:** the graph made **no difference for simple lookups** and **helped on the questions that
depend on connections between documents**: "what do I need, and in what order?" and "I have done X, what is
left?". The answers were more complete, always in a valid order, and better cited. The graph also needed 85%
fewer document searches and about 13% fewer input tokens per turn.

This report was updated on 3 November 2026 with the latest run.

Raw results: `evaluation/results/20261103-224141_comparison_both.md` (and `.json` for every answer).

---

## 1. What was compared

| | Vector-only baseline | GraphRAG navigator |
|---|---|---|
| Model | Claude Haiku 4.5 (Bedrock) | Claude Haiku 4.5 (Bedrock) |
| Documents | Same 9 summaries, same 117 chunks, same Neo4j vector index | Same |
| System prompt | Same, plus a short "baseline mode" note | Same |
| Tools | `vector_search` (+ `remember_profile`, `handoff_to_human`) | `vector_search` + graph tools (`plan_steps`, `explain_path`, `get_dependencies`, ...) |
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
| Lookup | GraphRAG | **1.80** (90%) | 2.00 | – | – |
| Multi-step | Baseline | 1.00 (50%) | 1.60 | 3/5 | 2/5 |
| Multi-step | GraphRAG | **1.40** (70%) | **2.00** | **5/5** | 2/5 |
| Progress | Baseline | 0.80 (40%) | 1.00 | 4/5 | 3/5 |
| Progress | GraphRAG | **1.00** (50%) | **1.80** | **5/5** | 2/5 |

**Why there are two order columns.** The judge's order verdicts turned out to be unreliable. For example, on
question M1 it said laboratory analysis was listed before the facility inspection, but the reply lists the
inspection at step 9 and the analysis at step 10. So I checked the order with code as well: for each reply, find
every step name, then check that no step appears before something it depends on in the reviewed graph. This found
no order mistakes in any of the 10 GraphRAG checklists. It was a one-off check, not yet part of `run_eval.py`.

The code check has a limit: it only sees steps written with their exact names. The baseline replies name far
fewer steps (about 2 to 6 on average, against 9 to 19 for GraphRAG), so they have fewer chances to go wrong.

Per-question correctness (0–2):

| | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---|---|---|---|---|
| Lookup, baseline | 2 | 2 | 2 | 2 | 1 |
| Lookup, GraphRAG | 2 | 2 | 2 | 2 | 1 |
| Multi-step, baseline | 1 | 1 | 1 | 1 | 1 |
| Multi-step, GraphRAG | 1 | **2** | 1 | **2** | 1 |
| Progress, baseline | 1 | **0** | 1 | 1 | 1 |
| Progress, GraphRAG | 1 | 1 | 1 | 1 | 1 |

Effort across the same 15 questions:

| | Baseline | GraphRAG |
|---|---|---|
| `vector_search` calls in total | 33 | **5** |
| Average input tokens per turn (including cached) | 19,856 | **17,287** |
| Average time per turn (using Neon from a laptop) | 28.3 s | 23.4 s |

**Compared with 27 October.** GraphRAG's correctness went up on multi-step (50% → 70%) and down on progress
(80% → 50%). Progress is the one to watch: the replies now list fewer of the remaining steps. Each category has
only 5 questions and the model writes each reply differently, so one run can't show whether this is a real drop.
Three things have changed since then: the system prompt, the memory design, and the standard names in the graph.
Times are also much longer than the 8.9 s measured on 27 October, because that run used a local database (see
section 8).

The earlier report said GraphRAG used about 40% fewer input tokens. Adding up the saved numbers the same way for
both runs gives 19% for that run and 13% for this one, so I now report the lower figure.

## 4. Where the graph helped

**Multi-step questions: better coverage, order and citations (50% → 70%, valid order 3/5 → 5/5).**
"What do I need, and in what order?" depends on connections across several documents: CAC registration comes
before tax, which comes before the state premises permit, which comes before the NAFDAC inspection, and so on.
Vector search returns the 4 closest paragraphs per search, so the baseline needed 5 to 7 searches on most of these
questions and still missed many steps. The graph returns the connected list in one call.

**Progress questions: better citations and order (citations 50% → 90%, correctness 40% → 50%).**
The graph knows every requirement for the profile, so `plan_steps` removes the steps already on record and returns
the rest with their sources. The baseline can only reason from retrieved paragraphs. It searched once or not at
all on these questions, and its replies named only about 2 steps on average. In the 27 October run, this gap was
much larger (30% → 80%), and the baseline's general knowledge led it to name the old tax agency, FIRS.

**Efficiency.** One graph call replaces several searches: 5 searches instead of 33 across the 15 questions, and
about 13% fewer input tokens per turn.

## 5. Where it made no difference

**Lookups (90% vs 90%).** A single fact ("the business-name fee is ₦10,000") lives in one paragraph, and both modes
find it with the same vector search. The graph isn't involved, so no difference is expected, and none was found.

**Long checklists are still often only "partly right".** Most GraphRAG checklist answers scored 1, not 2, mainly
because Navi **shortens** long plans (20 to 30 steps) when writing the reply. The graph supplied every step; the
steps were lost when the model wrote the answer. Having code write out the checklist would close this gap.

## 6. Limitations (read the numbers as direction, not precision)

1. **Small sample.** 5 questions per type: one question moves an average by 0.4. Across the full runs the
   direction never changed, but the exact numbers moved (GraphRAG multi-step correctness has been 1.4, 1.0, 1.0
   and 1.4; progress was 1.6 on 27 October and 1.0 on 3 November).
2. **The gold answers come from the same graph GraphRAG uses.** This favours GraphRAG on completeness.
   It is mitigated by the graph being extracted from the same documents the baseline searches and then
   checked by hand, but a fully independent gold list (written from the documents by a person) would be
   stronger.
3. **The judge sees only the expected section.** Some details it called "invented" may come from another
   section of the same document (for example the SON "60 days" timeline, flagged in both modes).
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

## 8. Other evaluation results (3 November 2026)

| Test | Result | Report |
|---|---|---|
| Unit tests | **55/55 passed** | `pytest -q` |
| Safety cases (12) | **12/12 passed** | `20261103-221225_safety_both.md` |
| Tool scenarios (11, incl. the 7 demo scenarios) | **10/11 passed** | `20261103-221826_tools_both.md` |
| RAG questions (31, incl. 6 in Pidgin across suites) | Correctness 1.84/2, citation 1.86/2, "I don't know" handled 2/2 | `20261103-222709_rag_graphrag.md` |
| Asking for a person (20 messages, one-off test) | 13/20: requests 5/6, frustration 2/6, look-alikes 6/8 | ADR 0009 |
| Guardrail alone (40 messages, one-off test) | Caught 9 of 15 attacks; wrongly flagged 3 of 25 normal questions | ADR 0020 |
| Text-to-Cypher retry (one-off test) | All checks passed | – |

**The one tool failure.** In scenario 7, the user says in Pidgin "I never register anything yet". Navi didn't save
that as a fact, so it asked again in the second turn, and the checklist hadn't appeared by the end of the scenario.
This failed in both runs on 3 November, so it's a real weak spot, not chance.

**Reply time.** Using Neon from a laptop, lookup questions took 15 to 17 seconds per reply. With a temporary local
database, three of the same questions took about 7 seconds. Neon queries from the laptop took 0.6 to 5.8 seconds
each, and each reply makes many of them. A server in the same region as Neon should be much faster, but this hasn't
been measured yet.

## Conclusion

The graph helps exactly where the brief predicts. Vector search finds paragraphs that look like the
question, so it handles one-fact lookups well, and the graph adds nothing there. Questions whose answer
depends on how requirements connect across documents ("what do I need, in what order?", "what is left?")
need the graph: with it, the agent gave fuller, correctly ordered, cited plans, though it still shortens long ones.
Without it, the agent listed far fewer steps, put some out of order, and cited its sources less well.

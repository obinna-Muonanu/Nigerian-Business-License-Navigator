# Key experiment: vector-only RAG vs GraphRAG

**Question asked by the brief:** does adding a knowledge graph help an agent answer licensing questions,
compared with retrieving from the same documents with vector search alone? Where does it help, and where
does it make no difference?

**Short answer:** the graph made **no difference for simple lookups**, helped **moderately for "what do I
need, and in what order?"**, and helped **most for "I have done X, what is left?"**. It also used about
40% fewer input tokens per turn and 85% fewer document searches.

Raw results: `evaluation/results/20261027-222926_comparison_both.md` (and `.json` for every answer).

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
| **Order OK** | the checklist never lists a step before something it depends on (count out of the checklists given) |

Each table cell is the **average of 5 questions**. Multiply by 50 for a percentage (1.6 = 80%).

## 3. Results

| Question type | Mode | Correctness | Citation | Order OK |
|---|---|---|---|---|
| Lookup | Baseline | **1.60** (80%) | 2.00 | – |
| Lookup | GraphRAG | **1.60** (80%) | 1.80 | – |
| Multi-step | Baseline | 0.80 (40%) | 1.60 | 2/5 |
| Multi-step | GraphRAG | **1.00** (50%) | **1.80** | **4/5** |
| Progress | Baseline | 0.60 (30%) | 0.60 | 3/5 |
| Progress | GraphRAG | **1.60** (80%) | **2.00** | **5/5** |

Per-question correctness (0–2):

| | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---|---|---|---|---|
| Lookup, baseline | 2 | 2 | 1 | 2 | 1 |
| Lookup, GraphRAG | 1 | 2 | 2 | 2 | 1 |
| Multi-step, baseline | 1 | 1 | **0** | 1 | 1 |
| Multi-step, GraphRAG | 1 | 1 | 1 | 1 | 1 |
| Progress, baseline | **0** | 1 | 1 | **0** | 1 |
| Progress, GraphRAG | **2** | 1 | **2** | **2** | 1 |

Effort per question type (same 15 questions):

| | Baseline | GraphRAG |
|---|---|---|
| `vector_search` calls in total | 32 | 5 |
| Average input tokens per turn (incl. cached) | 7,701 | **4,545** |
| Average latency per turn | 8.6 s | 8.9 s |

## 4. Where the graph helped

**Progress questions: the biggest difference (30% → 80%).**
The graph knows every requirement for the profile, so `plan_steps` simply removes the steps already on
record and returns the rest with their prerequisites. The baseline has no way to know what is "left" except
by reasoning about retrieved paragraphs. In 4 of 5 progress questions it **did not search the documents at
all** and answered from the model's general knowledge. That is where its errors came from: it named
"FIRS" (replaced by the Nigeria Revenue Service on 1 January 2026, as the knowledge base says), invented a
"Company Income Tax registration" step, and listed 4–6 steps where about 30 remained (questions P1 and P4
scored 0). GraphRAG listed the remaining steps with sources in every case (citation 2.0 vs 0.6).

**Multi-step questions: better order and coverage (40% → 50%, valid order 2/5 → 4/5).**
"What do I need, and in what order?" depends on connections across several documents: CAC registration
comes before tax, which comes before the state premises permit, which comes before NAFDAC inspection, and
so on. Vector search returns the 4 most similar paragraphs per query, so the baseline needed up to 7
searches per question and still missed whole regulators. For the cosmetics importer (M3) it listed 7 of
32 steps and scored 0. For the pharmacy (M2) it left out the data-protection steps. The graph returns the
complete, ordered list in one call, so GraphRAG's checklists were in a valid order 4 times out of 5.

**Efficiency.** One graph call replaces several searches: 5 searches instead of 32 across the 15
questions, and about 40% fewer input tokens per turn, at the same speed.

## 5. Where it made no difference

**Lookups (80% vs 80%).** A single fact ("the business-name fee is ₦10,000") lives in one paragraph, and
both modes find it with the same vector search. The graph is not involved, so no difference is expected,
and none was found. The small citation gap (2.0 vs 1.8) is one answer.

**Long checklists are still only "partly right" in both modes.** GraphRAG multi-step answers scored 1, not
2, mainly because the agent **summarised** long plans (20–30 steps): it grouped optional, conditional
and recurring steps (VAT, renewals, trademark sub-steps) or left them out to keep the reply readable. The
graph supplied every step; the omissions happened when the model wrote the reply. A fixed checklist
format, or showing the full list in the UI panel instead of the chat, would close this gap.

## 6. Limitations (read the numbers as direction, not precision)

1. **Small sample.** 5 questions per type: one question moves an average by 0.4. Across three full runs
   the direction never changed, but the exact numbers moved (GraphRAG multi-step correctness was 1.4, 1.0
   and 1.0 in successive runs).
2. **The gold answers come from the same graph GraphRAG uses.** This favours GraphRAG on completeness.
   It is mitigated by the graph being extracted from the same documents the baseline searches and then
   checked by hand, but a fully independent gold list (written from the documents by a person) would be
   stronger.
3. **The judge sees only the expected section.** Some details it called "invented" may come from another
   section of the same document (for example the SON "60 days" timeline, flagged in both modes).
4. **The judge is not perfect.** A few order verdicts contradict themselves in the rationale. Every
   verdict and rationale is in the `.json` file for checking.
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

## 8. Other evaluation results (same final agent)

| Suite | Result | Report |
|---|---|---|
| RAG questions (31, incl. 6 in Pidgin across suites) | Correctness 1.81/2, citation 1.90/2, "I don't know" handled 2/2 | `20261027-212517_rag_graphrag.md` |
| Tool scenarios (11, incl. the 7 demo scenarios) | **11/11 passed** | `20261027-222750_tools_both.md` |
| Safety / attack cases (5) | **5/5 passed** | `20261027-222654_safety_both.md` |

## Conclusion

The graph helps exactly where the brief predicts. Vector search finds paragraphs that look like the
question, so it handles one-fact lookups well, and the graph adds nothing there. Questions whose answer
depends on how requirements connect across documents ("what do I need, in what order?", "what is left?")
need the graph: with it, the agent gave complete, correctly ordered, cited plans. Without it, the agent
missed whole regulators, put steps out of order, and in progress questions fell back on general
knowledge, including outdated facts.

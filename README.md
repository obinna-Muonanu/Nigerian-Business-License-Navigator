# Business Licensing Navigator

**An AI agent that tells a Nigerian entrepreneur which registrations, licences and permits they need to
start a regulated business, in what order, and how much each one costs, with sources for every answer.**

Built with **Strands Agents** and **Amazon Bedrock**, using a **knowledge graph + document search
("GraphRAG")** in **Neo4j**.

> *"I want to start selling packaged zobo drinks in Ibadan. What do I need, and in what order?"*
>
> The navigator asks a few questions, then returns an ordered checklist (CAC registration → tax ID →
> state premises permit → NAFDAC inspection → laboratory analysis → NAFDAC product registration → ...).
> It can explain why each step comes before the next, answer fee and document questions with
> citations, remember the user's progress across sessions, and reply in English or Nigerian Pidgin.

**Contents**
1. [The problem](#1-the-problem)
2. [The approach](#2-the-approach)
3. [The results](#3-the-results)
4. [Running the project](#4-running-the-project)
5. [Project structure](#5-project-structure)
6. [Further reading](#6-further-reading)

---

## 1. The problem

### Starting a business in Nigeria is confusing
To start a regulated business, an entrepreneur has to deal with **several separate bodies**:

- the **corporate registry** (CAC);
- the **tax authorities** (Nigeria Revenue Service and the state revenue services);
- **product regulators** (NAFDAC, SON, the Pharmacy Council);
- the **data-protection commission** (NDPC);
- the **state government**, for business premises permits.

The rules are spread across many web pages, they **depend on the type of business and the state**, and
the steps **must be done in a particular order**. For example, NAFDAC will not register a drink until
the factory has been inspected, and the inspection needs the CAC registration and tax ID first.

Most people only find out what they missed when they get stuck.

### What the brief asked for
Project 3 of the AI Engineering Capstone asks for a conversational agent that:

| Requirement | In plain words |
|---|---|
| **Conversational** | Holds a multi-turn conversation, asks clarifying questions, handles English and Pidgin |
| **Agentic** | Decides which tools to call, chains steps, and asks for a "yes" before changing anything |
| **RAG** | Answers detail questions from documents and shows the source (document and section) |
| **Knowledge graph** | Stores what depends on what, so it can produce an ordered checklist and explain *why* |
| **Progress** | Saves the checklist, marks steps done, sets (mock) reminders, re-plans what is left |
| **No guessing** | Says "I don't know" and points to the official source when it has no information |
| **Handoff** | Passes the conversation to a human, with a summary, when asked or when the user is upset |
| **Logging** | Records every tool call: name, inputs and result |
| **Key experiment** | Compares GraphRAG with vector-only RAG on 15 questions and explains where the graph helps |

### Why a knowledge graph
Ordinary RAG (vector search) finds paragraphs that *look like* the question. That works for "how much
is the CAC fee?", which lives in one paragraph. It struggles with "what do I need, **and in what
order**?", because the answer depends on **connections across several documents**. A knowledge graph
stores those connections directly:

```
(Packaged fruit drinks) -REQUIRES-> (NAFDAC product registration) -DEPENDS_ON-> (NAFDAC facility inspection)
                                                                                       -DEPENDS_ON-> (CAC registration)
```

So: **the graph answers *what* and *in what order*; the documents answer *how*, *how much* and *which forms*.**

### Scope
- **Business types (4):** packaged fruit drinks (e.g. zobo), retail pharmacy, online cosmetics store,
  furniture business.
- **States (6):** Oyo, Lagos, FCT, Rivers, Ogun, Edo.
- **Knowledge base:** 9 summaries of official regulator sources (CAC, NRS and state tax, NAFDAC food and
  cosmetics, PCN, NDPC, SON, trademarks, state premises permits). Each records its source URLs and the
  date it was read.
- **Data:** synthetic users only, no real BVN, NIN or card numbers (NDPA).

---

## 2. The approach

### 2.1 The big picture

```
                        ┌──────────────────── Amazon Bedrock ────────────────────┐
                        │  Claude Haiku 4.5 (agent)   Claude Sonnet 4.5 (graph   │
                        │  Titan Embeddings V2         extraction + eval judge)  │
                        └───────────────▲────────────────────────────────────────┘
                                        │
 Streamlit chat UI ──HTTP/SSE──► FastAPI ──► Strands Agent ──► Neo4j AuraDB
 CLI (main_agent.py) ─────────────────────►  (tools + hooks)    (knowledge graph + vector index, read-only)
 Evaluation harness ──────────────────────►        │
                                                   ├──► SQLite (memory, checklists, progress, tool log)
                                                   └──► Session files (short-term memory)

 Offline: 9 documents ──► Claude extracts the graph ──► human review ──► load graph + embeddings ──► Neo4j
```

Diagrams: [system architecture](https://app.eraser.io/workspace/oZNSA2VMj1YHSIuG4kwz?diagram=95KNr-iFdeEZI_Au6z5f&layout=canvas)
and [agent architecture](https://app.eraser.io/workspace/oZNSA2VMj1YHSIuG4kwz?diagram=0i5lM5zV6FZ-_CClaTXd&layout=canvas) (Eraser).

### 2.2 Step 1: Build the knowledge (offline, once)

The same 9 documents are processed **twice**: once into the graph, once into searchable chunks.

1. **Extract the graph with an LLM.** Claude Sonnet reads each document and fills in a strict form
   (structured output). For each requirement it records: its ID and name, the regulator, which business
   types need it **and under which condition** (e.g. "only if you sell online"), the states it applies
   in, the steps that must come first (each with a **reason**), and the documents needed.
2. **Check it by hand.** A review report compares the model's output with each document's own
   "Must be done after" lines and flags anything that disagrees. The graph was checked by hand in Neo4j
   Browser and found correct, so no corrections were needed.
3. **Load Neo4j.** The reviewed graph is loaded, and each document is split into chunks by section,
   embedded with Titan, and stored with a **vector index**. A link `(Chunk)-[:DESCRIBES]->(Requirement)`
   joins each piece of text to the step it describes.

**The resulting knowledge graph:**

| Nodes (238) | | Relationships (861) | |
|---|---|---|---|
| Requirement | 72 | APPLIES_IN (requirement → state) | 352 |
| RequiredDocument | 135 | REQUIRES (business type → requirement, with a condition) | 198 |
| Regulator | 21 | NEEDS_DOCUMENT | 152 |
| State | 6 | DEPENDS_ON (with the reason) | 83 |
| BusinessType | 4 | ISSUED_BY | 72 |
| | | SATISFIES (the 4 CAC registration routes) | 4 |

Plus **117 document chunks** from 9 documents, for vector search. The brief's minimum is 30 nodes and
60 relationships.

### 2.3 Step 2: Answer a question (one turn)

```
User message ─► 1. Input guard ─► 2. Build context ─► 3. Agent loop (Claude Haiku) ─► 4. Checks ─► 5. Streamed reply
                                                          ▲      │
                                                          └ tools ┘
```

1. **Input guard.** Detects whether *this* message is English or Pidgin. Masks NIN/BVN-style and card
   numbers before the model sees them. Flags prompt-injection attempts and requests for a human.
2. **Build the context:**
   - the system prompt and tool list (identical for every user, so Bedrock caches them);
   - a short **memory block** (what we already know about this user);
   - the recent conversation.
3. **Agent loop.** Claude Haiku decides what to do, calls tools, reads the results, and repeats until
   it can answer. The **11 tools**, grouped by purpose:

   | Group | Tools | Used for |
   |---|---|---|
   | **Retrieve** | `vector_search`, `get_requirements`, `get_dependencies`, `explain_path`, `query_graph` | Fees, forms, rules (documents); requirements and dependencies (graph); unusual graph questions (guarded text-to-Cypher) |
   | **Plan** | `plan_steps` | The ordered checklist for this user, without the steps already done |
   | **Act** (need a "yes") | `save_checklist`, `update_progress`, `set_reminder` | Change the user's records |
   | **Escalate and remember** | `handoff_to_human`, `remember_profile` | Pass to a person; remember a fact about the business |

4. **Checks (hooks).** Small pieces of code that run around every turn and tool call, so the rules
   hold **whatever the model does**:
   - **Confirmation:** the three Act tools only run after the user says "yes" to that exact action.
   - **Audit:** every tool call is logged (name, inputs, status, full result).
   - **Grounding:** fees or timelines without a source get a warning, and a reply that claims a
     blocked action was done gets a visible correction.
   - **Compaction:** old tool results are shortened to save tokens.
5. **Streamed reply.** The answer streams word by word, in the user's language. Facts carry numbered
   footnotes [1] and a **Sources** list (document, section, "information as of" date, official link).
   Internal requirement IDs are filtered out.

### 2.4 Memory

| | Short-term memory | Long-term memory |
|---|---|---|
| **Belongs to** | One chat session (`session_id`) | One user (`user_id`) |
| **Holds** | The conversation and pending confirmations | Profile (business type, state, structure, ...), completed steps, a 3-line summary of the last session |
| **Stored in** | Session files on disk | SQLite |
| **Special behaviour** | After 30 user turns, the last 12 messages are kept word for word and older ones become one rolling summary | Facts are saved the moment the user states them, so a new chat starts with an empty history but a full profile ("Welcome back, still zobo in Ibadan?") |

### 2.5 Key design decisions

Each decision is explained in full (the problem, the options, why, and the trade-offs) in the
[Architecture Decision Records](docs/adr/README.md). In short:

| Decision | Why |
|---|---|
| **Strands Agents + Amazon Bedrock** | Bedrock was the available provider; Strands gives the agent loop, streaming, sessions and hooks ([0001](docs/adr/0001-strands-agents-on-amazon-bedrock.md)) |
| **One agent with 11 tools** | Cheaper and faster than several agents, and confirmations stay in one conversation ([0002](docs/adr/0002-one-agent-with-tools.md)) |
| **Graph and vectors in one Neo4j** | One query can use both; citations come from the graph; a fair baseline ([0003](docs/adr/0003-graph-and-vectors-in-one-neo4j.md)) |
| **LLM extraction, then human review** | Fast to build, and the brief requires a hand check ([0004](docs/adr/0004-llm-extraction-then-human-review.md)) |
| **Fixed graph queries first** | Predictable and safe; text-to-Cypher is a guarded, read-only extra ([0005](docs/adr/0005-fixed-graph-tools-first.md)) |
| **The agent only writes to SQLite** | Neo4j stays read-only, so the knowledge can never be damaged ([0006](docs/adr/0006-sqlite-for-everything-the-agent-writes.md)) |
| **Rules enforced in code (hooks)** | A prompt can be ignored or bypassed; code cannot ([0009](docs/adr/0009-enforce-rules-in-code-with-hooks.md), [0010](docs/adr/0010-confirm-before-write.md)) |
| **Claude Haiku for the agent, Sonnet for extraction and judging** | Low running cost, with accuracy where it matters ([0014](docs/adr/0014-model-choice-and-cost-control.md)) |

### 2.6 How it was evaluated

Four test suites, all re-runnable with one command (section 4.5):

| Suite | Size | How it is graded |
|---|---|---|
| **Key experiment** | 15 questions, each answered by **both** a vector-only baseline and GraphRAG | An independent judge (Claude Sonnet), against gold answers |
| **RAG questions** | 31 questions (6 Pidgin messages across the suites) | The judge, against the expected document section |
| **Tool scenarios** | 11 scripted conversations, including the 7 demo scenarios | Hard checks on the audit log: did the right tools **actually run**? |
| **Safety cases** | 5 attacks (prompt injection, fake confirmation, prompt extraction, ID numbers, "just guess") | Hard checks **and** the judge |

To keep the experiment **fair**, the baseline and GraphRAG use the same model, documents, vector index
and prompt. **The only difference is the graph.** Gold answers for checklist questions are computed
directly from the hand-reviewed graph, and any order that respects the prerequisites counts as correct.

---

## 3. The results

All results come from the final version of the agent (Claude Haiku 4.5), saved in `evaluation/results/`.

### 3.1 Summary

| Suite | Result |
|---|---|
| **Tool scenarios** | **11 / 11 passed**: every demo scenario works, and no false "done" claims |
| **Safety cases** | **5 / 5 passed**: injection, fake confirmation, prompt extraction, ID masking, refusing to guess |
| **RAG questions** | Correctness **1.81 / 2**, citation **1.90 / 2**, "I don't know" handled correctly **2 / 2** |

### 3.2 The key experiment: does the graph help?

Each answer was graded **0** (wrong), **1** (partly right) or **2** (fully right), averaged over 5
questions per type, and shown here as a percentage.

| Question type | Vector-only | GraphRAG | Valid order (vector → graph) |
|---|---|---|---|
| **Simple lookup** ("What is the CAC fee?") | 80% | 80% | – |
| **Multi-step** ("What do I need, and in what order?") | 40% | **50%** | 2/5 → **4/5** |
| **Progress** ("I've done X, what's left?") | 30% | **80%** | 3/5 → **5/5** |

**Where the graph helped:**
- **Progress questions (30% → 80%).** The graph knows every requirement, so the agent simply removes
  the completed steps. Without it, the baseline usually **did not search at all** and answered from
  general knowledge. It named the old tax agency (FIRS instead of the Nigeria Revenue Service) and
  invented a step.
- **Multi-step questions.** The graph returns the complete, connected list in one call, so checklists
  were in a valid order 4 times out of 5 (baseline 2 out of 5). The baseline needed up to 7 searches
  per question and still missed whole regulators: 7 of 32 steps for the cosmetics importer.
- **Efficiency.** 5 document searches instead of 32 across the 15 questions, and about 40% fewer input
  tokens per turn, at the same speed.

**Where it made no difference:**
- **Simple lookups.** A single fact lives in one paragraph, and both versions find it with the same
  search.
- **Very long checklists stayed "partly right" in both versions**, because the agent summarised 20–30
  step plans to keep replies readable.

**Conclusion:** the graph helps exactly where the brief predicts. It matters for questions whose answer
depends on connections across documents, and makes no difference for single-fact lookups.

**Limitations:** 5 questions per type, so read the differences as direction, not precision. The gold
answers come from the same graph GraphRAG uses. The full write-up, with every caveat, is in
[evaluation/EXPERIMENT_REPORT.md](evaluation/EXPERIMENT_REPORT.md).

### 3.3 Problems found and fixed during testing

Testing found real bugs, which were fixed before the final run:

| Problem | Fix |
|---|---|
| After one Pidgin message, the agent kept replying in Pidgin | The reply language is decided from each message on its own ([0012](docs/adr/0012-reply-language-follows-each-message.md)) |
| Internal IDs like "D05" appeared in answers | Tools give names, and a stream filter removes any ID ([0011](docs/adr/0011-footnote-citations-and-hidden-ids.md)) |
| The user's "yes" was sometimes ignored | The confirmation check reads only what the user typed ([0010](docs/adr/0010-confirm-before-write.md)) |
| The agent called covered topics "out of scope" without searching | A per-message "search before saying you don't know" reminder |
| The agent held back "what's left" while asking to record progress | It now shows the answer at once and asks for the "yes" at the end |
| One reply claimed a blocked save had happened | A visible correction is added, and every tool scenario now checks for this |

---

## 4. Running the project

### 4.1 Prerequisites
- **Python 3.12+** with a virtual environment.
- **An AWS account with Amazon Bedrock access** to Claude Haiku 4.5, Claude Sonnet 4.5 and
  Titan Text Embeddings V2 (use the `us.` inference-profile IDs for Claude).
- **A Neo4j AuraDB Free instance** (its URI and password).

### 4.2 Install and configure (Windows PowerShell)
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # then fill in AWS, the model IDs and Neo4j
```
All settings are checked at start-up. If anything is missing or wrong, one message lists every
variable to fix.

### 4.3 Build the knowledge base (once)
```powershell
python -m ingestion.extract_graph            # Claude extracts the graph -> data/graph/extracted.json + review_report.txt
python -m ingestion.extract_graph --approve  # after your review -> data/graph/reviewed.json
python -m ingestion.load_graph --reset       # load graph + embedded chunks into Neo4j (prints the counts)
```

### 4.4 Run the agent
```powershell
uvicorn server:app --port 8000               # terminal 1: the API
streamlit run ui/streamlit_app.py            # terminal 2: the web chat
python main_agent.py --user ada-ibadan       # or chat in the terminal, no server needed
```
- **The web UI** has a Claude-style sidebar: **New chat**, your past chats (click one to reopen it),
  your saved checklist, and a collapsed **Developer settings** section (user ID, baseline/GraphRAG
  mode, and a token and latency display).
- **Start clean** before a demo (deletes chats, logs and memory, but not the graph):
  `python -m scripts.reset_local --yes`

**Demo scenarios to try:**

| # | Say | What happens |
|---|---|---|
| 1 | "I want to start selling packaged zobo drinks in Ibadan. What do I need, and in what order?" | Clarifying questions, then an ordered checklist with a dependency diagram |
| 2 | "How much is the CAC business name fee and how long does it take?" | Answer with footnotes and a Sources list |
| 3 | "I have finished my business registration. What is next?" | Shows what is left at once, then asks to record the progress; "yes" saves it |
| 4 | "Why do I need the NAFDAC facility inspection before product registration?" | The chain of dependencies, with reasons and sources |
| 5 | "I also want to sell online and collect customers' details. Does anything change?" | Adds the NDPC data-protection steps to the plan |
| 6 | "What permit do I need to export zobo to Ghana?" | Says it does not have that, points to official sources, offers a human |
| 7 | "Abeg, wetin I need to open pharmacy for Lagos?" | The same help, replied in Pidgin |
| ★ | Click **New chat**, then "What should I do next?" | Remembers the business; no questions asked again |

### 4.5 Run the evaluation
```powershell
python -m evaluation.run_eval --suite safety                   # 5 attack cases
python -m evaluation.run_eval --suite tools                    # 11 tool scenarios
python -m evaluation.run_eval --suite rag --mode graphrag      # 31 RAG questions
python -m evaluation.run_eval --suite comparison --mode both   # the key experiment
```
Each run writes a readable `.md` report and a `.json` file (every answer, verdict and tool call) to
`evaluation/results/`.

---

## 5. Project structure

```
agent/                 the agent (modular AI framework)
  config.py            the only module that reads .env (validated Pydantic settings)
  prompts.py           every prompt in one place
  schemas.py           shared vocabularies and data models
  core.py              builds the agent and streams one turn
  output_filter.py     removes internal IDs from replies while streaming
  llm/                 Bedrock models and Titan embeddings
  storage/             SQLite (everything the agent writes) and Neo4j (read-only knowledge)
  knowledge/           graph planner, vector search, citations, text-to-Cypher guard
  memory/              short-term, long-term, rolling summary, session history
  tools/               one file per tool, registered by purpose in __init__.py
  hooks/               input guard, confirmation, audit, grounding, compaction
ingestion/             parse documents, extract the graph, load Neo4j
evaluation/            datasets, judge, runner, results, EXPERIMENT_REPORT.md
knowledge_base/        the 9 source documents
data/graph/            the extracted and reviewed graph
docs/adr/              Architecture Decision Records
server.py              FastAPI API (streaming /chat, sessions, checklist, health)
ui/streamlit_app.py    web chat
main_agent.py          command-line chat
scripts/reset_local.py start from a clean slate
```

### Data and compliance
- **Synthetic users only.** ID and card numbers are masked before the model sees them, and only a fixed
  set of business fields is stored about a user (NDPA).
- **Freshness.** Every source shows the date its information was read. Fees and rules change, so the
  agent always tells users to confirm with the regulator.
- **Logging.** Every tool call is kept in SQLite (`tool_calls`) and in `logs/audit_<session>.jsonl`.

---

## 6. Further reading

| Document | What it covers |
|---|---|
| [evaluation/EXPERIMENT_REPORT.md](evaluation/EXPERIMENT_REPORT.md) | The full key-experiment write-up: setup, scoring, findings, limitations |
| [docs/adr/](docs/adr/README.md) | 17 Architecture Decision Records: why each part was built the way it is |
| [Eraser diagrams](https://app.eraser.io/workspace/oZNSA2VMj1YHSIuG4kwz) | The system and agent architecture diagrams |

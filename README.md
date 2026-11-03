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
 React web app ──HTTPS/SSE──► FastAPI ──► Strands Agent ──► Neo4j AuraDB
 (Supabase sign-in)   (checks the sign-in pass)
 CLI (main_agent.py) ─────────────────────►  (tools + hooks)    (knowledge graph + vector index, read-only)
 Evaluation harness ──────────────────────►        │
                                                   └──► App database: SQLite locally, Postgres in production
                                                        (chats, memory, checklists, progress, tool log)

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
3. **Load Neo4j.** The reviewed graph is loaded, with every regulator and required document given one
   standard name from a reviewed list (`data/graph/canonical_names.json`, ADR 0021), so the same thing
   isn't stored under several spellings. Then each document is split into chunks by section,
   embedded with Titan, and stored with a **vector index**. A link `(Chunk)-[:DESCRIBES]->(Requirement)`
   joins each piece of text to the step it describes.

**The resulting knowledge graph:**

| Nodes (149) | | Relationships (837) | |
|---|---|---|---|
| Requirement | 72 | APPLIES_IN (requirement → state) | 352 |
| RequiredDocument | 52 | REQUIRES (business type → requirement, with a condition) | 198 |
| Regulator | 15 | NEEDS_DOCUMENT (keeps the document's own wording) | 128 |
| State | 6 | DEPENDS_ON (with the reason) | 83 |
| BusinessType | 4 | ISSUED_BY | 72 |
| | | SATISFIES (the 4 CAC registration routes) | 4 |

Plus **117 document chunks** from 9 documents, for vector search (275 nodes and 1,040 relationships in
all). The brief's minimum is 30 nodes and 60 relationships.

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
   it can answer. The **12 tools**, grouped by purpose:

   | Group | Tools | Used for |
   |---|---|---|
   | **Retrieve** | `vector_search`, `get_requirements`, `get_dependencies`, `explain_path`, `query_graph` | Fees, forms, rules (documents); requirements and dependencies (graph); unusual graph questions (guarded text-to-Cypher) |
   | **Plan** | `plan_steps` | The ordered checklist for one of the user's businesses, without the steps already done |
   | **Act** (need a "yes") | `save_checklist`, `update_progress`, `set_reminder` | Change the user's records |
   | **Escalate and remember** | `handoff_to_human`, `remember_profile`, `add_business` | Pass to a person; remember a fact about a business; add another business |

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

Navi has four kinds of memory, each with its own job, size and level of trust
([ADR 0018](docs/adr/0018-production-memory.md)):

| | Working memory | Short-term memory | Long-term memory | Episodic memory |
|---|---|---|---|---|
| **Question it answers** | What am I looking at right now? | What have we said in this chat? | What do I know for sure about this user? | What happened last time? |
| **Holds** | Rules, memory block, recent messages, fresh tool results | The whole chat and any action waiting for a "yes" | Each business's confirmed facts and finished steps, checklists, reminders | A three-line note per past chat |
| **Lives for** | One reply | One chat | Months (until the retention limit) | Months (the last 3 are shown) |
| **Stored in** | The model's context window | `chat_*` tables | `businesses`, `profile_facts`, `progress`, ... | `episodes` |
| **Kept small by** | Old tool results trimmed after each turn, prompt caching | At ~24,000 tokens, the last 5 turns stay word for word and older ones are summarised | Only a fixed list of business fields can be stored | Three lines each |

The rules that make it production-ready:
- **Everything lives in a real database.** SQLite on your own computer; set `DATABASE_URL` to a Postgres
  address in production, so chats and memory survive restarts and several servers can share them. Tables
  are created and upgraded by numbered migrations.
- **One user, several businesses.** Each business has its own profile, checklist, progress and reminders.
  If one message mentions two businesses, Navi plans both, under separate headings.
- **Facts are confirmed, sourced and never silently overwritten.** Each fact records where it came from and
  when, every change is kept in a history, and a contradicting fact makes Navi ask the user first.
- **Notes never override facts.** The AI-written notes from past chats are labelled as possibly incomplete.
- **Users control their data** (NDPA): the **My data** page (`GET /me/memory`, `/me/export`) shows
  everything, and `DELETE /me` erases it. Users not seen for `MEMORY_RETENTION_DAYS` (365) are deleted
  automatically.
- **Old businesses retire on their own.** A business nobody has worked on for 6 months becomes
  *inactive*: kept, but shown to Navi as one line, and brought straight back if the user mentions it.
  After 18 months unused it's deleted. A business with an upcoming reminder is never retired.

### 2.5 Key design decisions

Each decision is explained in full (the problem, the options, why, and the trade-offs) in the
[Architecture Decision Records](docs/adr/README.md). In short:

| Decision | Why |
|---|---|
| **Strands Agents + Amazon Bedrock** | Bedrock was the available provider; Strands gives the agent loop, streaming, sessions and hooks ([0001](docs/adr/0001-strands-agents-on-amazon-bedrock.md)) |
| **One agent with 12 tools** | Cheaper and faster than several agents, and confirmations stay in one conversation ([0002](docs/adr/0002-one-agent-with-tools.md)) |
| **Graph and vectors in one Neo4j** | One query can use both; citations come from the graph; a fair baseline ([0003](docs/adr/0003-graph-and-vectors-in-one-neo4j.md)) |
| **LLM extraction, then human review** | Fast to build, and the brief requires a hand check ([0004](docs/adr/0004-llm-extraction-then-human-review.md)) |
| **Fixed graph queries first** | Predictable and safe; text-to-Cypher is a guarded, read-only extra ([0005](docs/adr/0005-fixed-graph-tools-first.md)) |
| **The agent only writes to its own app database** | Neo4j stays read-only, so the knowledge can never be damaged ([0006](docs/adr/0006-sqlite-for-everything-the-agent-writes.md)) |
| **Four kinds of memory, in Postgres for production** | Memory survives restarts, handles several businesses per user, and keeps facts apart from AI-written notes ([0018](docs/adr/0018-production-memory.md)) |
| **Rules enforced in code (hooks)** | A prompt can be ignored or bypassed; code cannot ([0009](docs/adr/0009-enforce-rules-in-code-with-hooks.md), [0010](docs/adr/0010-confirm-before-write.md)) |
| **Claude Haiku for the agent, Sonnet for extraction and judging** | Low running cost, with accuracy where it matters ([0014](docs/adr/0014-model-choice-and-cost-control.md)) |

### 2.6 How it was evaluated

Four test suites, all re-runnable with one command (section 4.6):

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
- **Node.js** (the LTS version) for the React web app.
- **A Postgres database** for chats and memory, for example a free **Neon** project (or leave
  `DATABASE_URL` empty to use a local SQLite file).
- **A Supabase project** for sign-in (email and password). For a demo, turn off "Confirm email" under
  Authentication → Sign In / Providers → Email, so testers can sign up instantly.

### 4.2 Install and configure (Windows PowerShell)
```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"            # the app and its test tools, from pyproject.toml
Copy-Item .env.example .env      # then fill in AWS, the model IDs and Neo4j
```
In `.env`, also set:
- `DATABASE_URL`: your Postgres address (for example Neon's `dev` branch); the tables are created on first start.
- `SUPABASE_URL`: your Supabase project address (`https://<project-id>.supabase.co`). Without it the API
  refuses every request except `/health`.
- `ALLOWED_ORIGINS`: the website addresses allowed to call the API (default `http://localhost:5173`).

Then set up the web app:
```powershell
cd frontend
npm install
Copy-Item .env.example .env.local   # then fill in VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY
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
uvicorn api.server:app --port 8000           # terminal 1: the API
npm --prefix frontend run dev                # terminal 2: the web app, at http://localhost:5173
python main_agent.py --user ada-ibadan       # or chat in the terminal, no server needed
```
- **The web app** (React + TypeScript + Tailwind) starts with a sign-in page. After signing in, a
  Claude-style sidebar has **New chat**, your past chats grouped by date, your saved checklists (one per
  business), **My data** (see, download or delete what Navi remembers), and **Developer settings**
  (baseline/GraphRAG mode, and a tools, latency and token display). Replies stream word by word, and a
  checklist reply can show its step diagram.
- **Several people can test at once.** Each person signs in with their own email; the API takes their
  identity from the Supabase sign-in pass, so nobody can see anyone else's chats or memory.
- **Start clean** before a demo (deletes chats, logs and memory, but not the graph). It only works on
  a local SQLite setup and refuses to run when `DATABASE_URL` is set:
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

### 4.5 Run the tests
```powershell
pytest -q        # 55 unit tests, in seconds, with no AWS, Neo4j or real database needed
```
The unit tests check Navi's own rules: the query guard, Pidgin detection and number masking, removing
internal codes from replies, memory (one business per fact, no silent overwrites, no mixing between users),
the sign-in check, the API's access rules, and the knowledge graph's standard names. They also run
automatically on GitHub on every push (`.github/workflows/tests.yml`), together with a build of the website.

The evaluation below is different: it calls the real models to grade Navi's answers, so it costs money and
takes minutes.

### 4.6 Run the evaluation
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
  storage/             app database (SQLite or Postgres, with migrations), chat history, Neo4j (read-only)
  knowledge/           graph planner, vector search, citations, text-to-Cypher guard
  memory/              short-term, long-term (per business), episodic notes, rolling summary
  tools/               one file per tool, registered by purpose in __init__.py
  hooks/               input guard, confirmation, audit, grounding, compaction
ingestion/             parse documents, extract the graph, load Neo4j
evaluation/            datasets, judge, runner, results, EXPERIMENT_REPORT.md
knowledge_base/        the 9 source documents
data/graph/            the extracted and reviewed graph
docs/adr/              Architecture Decision Records
api/server.py          FastAPI API (streaming /chat, sessions, checklists, memory, export/delete, health)
api/auth.py            checks the Supabase sign-in pass on every request
tests/                 fast unit tests (pytest): safety checks, memory, sign-in, API access rules
.github/workflows/     runs the unit tests and the website build on every push
pyproject.toml         the project's dependencies and test settings
frontend/              React + TypeScript + Tailwind web app (sign-in, chat, sidebar, My data)
main_agent.py          command-line chat
scripts/reset_local.py start from a clean slate (local SQLite only)
scripts/purge_old_data.py delete users past the retention period (schedule daily)
```

### Data and compliance
- **Synthetic users only.** ID and card numbers are masked before the model sees them, and only a fixed
  set of business fields is stored about a user (NDPA).
- **Freshness.** Every source shows the date its information was read. Fees and rules change, so the
  agent always tells users to confirm with the regulator.
- **Logging.** Every tool call is kept in the app database (`tool_calls`) and in `logs/audit_<session>.jsonl`.
- **Retention and erasure.** Users can see, export or delete everything Navi holds about them on the
  **My data** page, and inactive users are deleted after `MEMORY_RETENTION_DAYS`.
- **Access control.** Every route except `/health` needs a valid Supabase sign-in pass, and the user's
  identity comes from that pass, never from the browser. Only the addresses in `ALLOWED_ORIGINS` may call
  the API from a browser, each user may send at most `CHAT_MESSAGES_PER_MINUTE` messages a minute, and
  error details stay in the server log instead of being shown to users.
- **Prompt-injection defence** ([ADR 0020](docs/adr/0020-prompt-injection-defence.md)). Every message is
  screened by an Amazon Bedrock Guardrail (prompt-attack filter) before Navi reads it; a suspected attack is
  flagged with a warning rather than refused, because the filter also flags some genuine questions. The real
  protection is in code: records change only after a genuine "yes", identity comes from the sign-in, and the
  knowledge graph is read-only. Create the guardrail once with `python -m scripts.create_guardrail`.

---

## 6. Further reading

| Document | What it covers |
|---|---|
| [evaluation/EXPERIMENT_REPORT.md](evaluation/EXPERIMENT_REPORT.md) | The full key-experiment write-up: setup, scoring, findings, limitations |
| [docs/adr/](docs/adr/README.md) | 20 Architecture Decision Records: why each part was built the way it is |
| [Eraser diagrams](https://app.eraser.io/workspace/oZNSA2VMj1YHSIuG4kwz) | The system and agent architecture diagrams |

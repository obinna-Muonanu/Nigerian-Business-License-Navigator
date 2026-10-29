# Architecture Decision Records (ADRs)

An Architecture Decision Record is a short note about **one important decision**: the problem I
was facing, what I chose, why I chose it, and what it costs.

I wrote them so that anyone reading the project, whether a reviewer, a teammate or me in six
months, can understand **why** the system is built the way it is, not just how.

## How each ADR is laid out

Every ADR follows the same order, so they are quick to read:

| Section | What it answers |
|---|---|
| **Context** | The situation and the problem I needed to solve |
| **Decision** | What I chose, in a little detail |
| **Why I chose this** | The reasons behind it |
| **What I considered instead** | The alternatives, and why each one lost |
| **Consequences** | What I gained, and the trade-offs I accepted |
| **Where to find it** | The files that implement it |

Every ADR has the status "Accepted", because they all describe what was actually built.

## The decisions

### Platform and knowledge
| # | Decision |
|---|---|
| [0001](0001-strands-agents-on-amazon-bedrock.md) | Build the agent with Strands Agents on Amazon Bedrock |
| [0002](0002-one-agent-with-tools.md) | Use one agent with tools, not several agents |
| [0003](0003-graph-and-vectors-in-one-neo4j.md) | Keep the knowledge graph and the vector search in one Neo4j database |
| [0004](0004-llm-extraction-then-human-review.md) | Build the graph with an LLM, then check it by hand |
| [0005](0005-fixed-graph-tools-first.md) | Use fixed graph queries first; text-to-Cypher only as a guarded extra |
| [0006](0006-sqlite-for-everything-the-agent-writes.md) | Store everything the agent writes in SQLite, separate from the knowledge |

### Memory and safety
| # | Decision |
|---|---|
| [0007](0007-two-tier-memory.md) | Two kinds of memory: short-term per session, long-term per user |
| [0008](0008-rolling-summary-conversation-manager.md) | Our own conversation manager: after 30 turns, keep the last 12 messages and summarise the rest |
| [0009](0009-enforce-rules-in-code-with-hooks.md) | Enforce the brief's rules in code (hooks), not only in the prompt |
| [0010](0010-confirm-before-write.md) | How "confirm before acting" works |
| [0011](0011-footnote-citations-and-hidden-ids.md) | Cite sources as numbered footnotes, and never show internal IDs |
| [0012](0012-reply-language-follows-each-message.md) | Reply in the language of each message |

### Delivery, cost and quality
| # | Decision |
|---|---|
| [0013](0013-streaming-api-and-thin-ui.md) | A streaming FastAPI server, with Streamlit as a thin client |
| [0014](0014-model-choice-and-cost-control.md) | Claude Haiku for the agent, Sonnet for extraction and judging, plus caching |
| [0015](0015-configuration-with-pydantic-settings.md) | Read configuration through one validated Pydantic settings model |
| [0016](0016-modular-layout-one-tool-per-file.md) | A modular code layout, with one file per tool |
| [0017](0017-how-we-evaluate.md) | Evaluate with a fair baseline, gold answers from the reviewed graph, a judge and hard checks |

## Adding a new ADR

Copy any existing file, give it the next number, keep it short, and add it to the table above.
Never edit an old decision to say something different: write a new ADR that replaces it, and mark
the old one "Replaced by 00XX".

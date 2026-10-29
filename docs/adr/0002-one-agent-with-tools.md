# ADR 0002: Use one agent with tools, not several agents

**Status:** Accepted · **Date:** 2026-10-26

## Context

The navigator has quite a few jobs. It asks clarifying questions, looks things up in the documents
and the graph, builds an ordered checklist, explains why one step has to come before another, saves
the user's progress, and hands over to a human when the user asks for one.

A popular way to build something like this is to give each job to its own agent: a planner, a
researcher, a record keeper and so on, with a manager agent on top deciding who does what. It looks
tidy on a diagram, so I had to decide whether this project actually needed it.

## Decision

I used **one** Strands agent with **11 tools**, grouped by what they are for:

| Group | Tools | What they do |
|---|---|---|
| Retrieve | `vector_search`, `get_requirements`, `get_dependencies`, `explain_path`, `query_graph` | Read the documents and the graph |
| Plan | `plan_steps` | Build the ordered checklist |
| Act (needs a "yes") | `save_checklist`, `update_progress`, `set_reminder` | Change the user's records |
| Escalate and remember | `handoff_to_human`, `remember_profile` | Pass to a person, or remember a fact |

## Why I chose this

Eleven tools is a comfortable number for one model to choose from. At this size there was no sign
that the model was confused about which tool to pick, so there was nothing for extra agents to fix.

What extra agents would have added is cost and delay. Every hand-off between agents is another model
call, so the user waits longer and I pay more. Each hand-off is also a chance for information to get
lost, because one agent has to summarise its work for the next.

There was also a practical reason. The brief says the agent must get an explicit "yes" before it
changes a record. That question ("Shall I mark CAC registration as done?") has to be asked by the
agent the user is actually talking to. So the write tools would have ended up in the main agent
anyway.

Finally, one agent is much easier to debug. There is one conversation, one set of hooks and one
audit log, so when something goes wrong I can follow exactly what happened.

The grouping isn't just for show. It makes the safety rules obvious: everything in the "Act" group
needs a confirmation, and nothing else does.

## What I considered instead

The main alternative was a **manager agent with specialist sub-agents** (the "agents as tools"
pattern). At this size it would have been slower and more expensive per answer, with no clear gain
in quality.

I could also have used **one agent with an ungrouped list of tools**. That would have worked just as
well for the model, but the design and the safety rules would have been harder to see.

## Consequences

The agent is fast, cheap and easy to trace. If the project grew to many more tools, say 30 or more,
splitting it into specialist agents could become worth it. Because the tools are already grouped,
that split would be straightforward.

## Where to find it

The tools are registered, by group, in `agent/tools/__init__.py` (`GRAPHRAG_TOOLS`, `WRITE_TOOLS`).
Each tool has its own file in `agent/tools/` (see ADR 0016).

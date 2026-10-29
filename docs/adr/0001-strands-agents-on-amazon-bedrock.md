# ADR 0001: Build the agent with Strands Agents on Amazon Bedrock

**Status:** Accepted · **Date:** 2026-10-26

## Context

The License Navigator has to do more than answer one question at a time. It needs to hold a
conversation, decide for itself which tool to call, chain several steps together (look up the
user's business type, find the requirements, order them, then explain them), and stream the
answer back while it is still being written so the user isn't left staring at a blank screen.

All of that sits on top of what is usually called the agent loop. The model thinks, asks for a
tool, the tool runs, the result goes back to the model, and this repeats until the model has
enough to answer. You can write that loop yourself, but it is fiddly. Once you add streaming,
retries, saving sessions and error handling, it becomes a lot of code that is easy to get subtly
wrong. I also had one hard constraint: Amazon Bedrock was the only place I could get language
models from, so whatever I picked had to work well with Bedrock.

## Decision

I built the agent with the **Strands Agents** framework and took every model from **Amazon
Bedrock**. Strands runs the loop, and Bedrock supplies the models: Claude Haiku answers the user,
Claude Sonnet extracts the knowledge graph and grades the evaluation, and Titan Text Embeddings
V2 turns text into vectors for search.

## Why I chose this

The deciding factor was Bedrock. Strands has a ready-made `BedrockModel` class, so connecting it
to Bedrock took a few lines of configuration rather than a custom integration. That class also
handles prompt caching, which matters a lot for keeping costs down, as later ADRs explain.

Beyond that, Strands already handles the parts I least wanted to build myself. The tool loop is
built in. Streaming is one call (`stream_async`). Sessions can be saved to disk with
`FileSessionManager`, so a conversation survives a restart. Structured output lets me ask a model
to fill in a fixed form, which I rely on both for building the graph and for the evaluation
judge. Most importantly, it has **hooks**: places where my own code runs before and after every
tool call. That gave me a clean spot for the safety rules, such as asking the user before saving
anything, without tangling them into the tools themselves (see ADR 0009).

Tools are also pleasant to write in Strands. Each one is an ordinary Python function with a
`@tool` decorator, and its docstring becomes the description the model reads when it decides
which tool to use. So the code and the model's instructions stay in the same place and can't drift
apart.


## What I considered instead

The obvious alternative was **writing the agent loop from scratch**. It would have given me full
control, but I would have spent my time rebuilding streaming, sessions and retries instead of
working on the actual problem of licensing guidance.

**LangChain and LangGraph** were also on the table. They are capable, but they bring a lot of
abstraction that this project doesn't need, and the extra layers make it harder to see what is
actually happening on each turn.

I also looked at **Amazon Bedrock AgentCore**, which hosts the agent and its memory for you. It
would have meant setting up and paying for more AWS services, and a small FastAPI app running
locally was all this project needed.

## Consequences

The result is less code, streaming and sessions that worked from day one, and a natural home
for the safety rules. The price is that the project now depends on Strands' APIs. Some of the
features I use, such as the cache configuration, are fairly recent, so I pinned
`strands-agents>=1.61.0` to make sure nobody installs an older version where they're missing.

## Where to find it

The agent is built in `agent/core.py` (`build_agent`), which also streams each turn
(`stream_turn`). The Bedrock models and the Titan embedding call are set up in
`agent/llm/bedrock.py`.

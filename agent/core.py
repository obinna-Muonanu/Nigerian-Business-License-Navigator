"""
This is the heart of Navi. It assembles the assistant and runs each turn of a conversation.

When a chat starts, it puts Navi together: the AI model, its instructions, what it remembers about the user,
the actions it can take, and the safety rules. When the user sends a message, it passes the message to Navi,
lets Navi think and use its tools, and sends the reply back a few words at a time, so the user sees the
answer appear as it's being written.

It also keeps a small pool of recently used chats ready in memory, so replies are quicker, and makes sure two
messages in the same chat are never handled at the same time.

HOW IT FITS IN
The web app, the command-line chat and the testing scripts all use this file to talk to Navi.
"""

import asyncio
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any, Literal

from strands import Agent
from strands.types.exceptions import MaxTokensReachedException

from agent.hooks import build_hooks
from agent.hooks.input_guard import mask_pii
from agent.llm import build_agent_model
from agent.memory import LongTermMemory, build_conversation_manager, build_session_manager, maybe_summarise, seed_state
from agent.output_filter import RequirementIdFilter
from agent.prompts import BASELINE_ADDENDUM, STATIC_SYSTEM_PROMPT, render_memory_block
from agent.storage import sqlite_store
from agent.tools import BASELINE_TOOLS, GRAPHRAG_TOOLS

# The two versions of the agent compared in the key experiment. Using a fixed list of allowed values
# means a typo like "graph_rag" fails straight away instead of quietly doing the wrong thing.
Mode = Literal["graphrag", "baseline"]


def build_agent(user_id: str, session_id: str, mode: Mode = "graphrag") -> Agent:
    """Create the agent for one user's chat, or pick up where a saved chat left off."""
    # Load what we remember about this user first, because it goes into the system prompt.
    memory = LongTermMemory.load(user_id)

    # The system prompt has three parts: the fixed rules, a cache marker, and the user's memory block.
    # Bedrock caches everything before the marker. Putting the user's details after it means the big,
    # expensive set of rules is cached once and shared by every user on every turn.
    static =STATIC_SYSTEM_PROMPT + (BASELINE_ADDENDUM if mode == "baseline" else "")
    system_prompt = [
        {"text": static},
        {"cachePoint": {"type": "default"}},
        {"text": render_memory_block(memory.profile, memory.completed, memory.summary)},
    ]

    # Here everything from the architecture diagram gets wired together: the model, the prompt, the tools,
    # the safety hooks and both halves of short-term memory. The session manager saves the chat to disk,
    # and the conversation manager summarises it once it gets long. We stream through stream_async, so
    # Strands' own printing callback is switched off. The trace attributes label each turn with the user,
    # chat and mode, which makes it easy to find a turn later when debugging.
    agent = Agent(
        name="license-navigator",
        model=build_agent_model(),
        system_prompt=system_prompt,
        tools=GRAPHRAG_TOOLS if mode == "graphrag" else BASELINE_TOOLS,
        hooks=build_hooks(session_id),
        session_manager=build_session_manager(session_id),
        conversation_manager=build_conversation_manager(),
        callback_handler=None,
        trace_attributes={"user_id": user_id, "session_id": session_id, "mode": mode},
    )
    # We fill in the agent's starting state only after it's built. While the Agent is being created, the
    # session manager restores any state saved from an earlier visit, and that would overwrite anything
    # we had set beforehand.
    seed_state(agent, user_id, session_id, memory)
    # Remember the mode with the chat, so the UI can list GraphRAG and baseline chats separately.
    agent.state.set("mode", mode)
    return agent


TITLE_MAX_CHARS = 48


def session_title(first_message: str) -> str:
    """Make a short title for the chat list from the first message.

    The title is stored and shown in the sidebar, so personal numbers are masked first. Otherwise a
    first message like "My BVN is 2212..." would put that number in plain sight.
    """
    # Squash line breaks and extra spaces into single spaces, and mask any personal numbers.
    text, _ = mask_pii(" ".join(first_message.split()))
    if len(text) <= TITLE_MAX_CHARS:
        return text
    # If it's too long, cut at the last space before the limit so no word is chopped in half.
    return text[:TITLE_MAX_CHARS].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


class AgentPool:
    """Keeps recently used agents in memory, one per chat.

    Rebuilding an agent from disk on every message would be slow, so we keep the busy ones ready to go.
    That also preserves the in-memory trimming of old tool results. When there are too many, the one
    used least recently is dropped. Each chat also gets its own lock, so two messages for the same chat
    can never run at the same time.
    """

    def __init__(self, max_agents: int = 64):
        # The most agents we keep at once, to put a ceiling on memory use.
        self.max_agents = max_agents
        # An OrderedDict remembers the order things were used in, which is exactly what we need to know
        # which agent was used least recently.
        self._agents: OrderedDict[str, Agent] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        # FastAPI can call get() from several threads at once, so this lock protects the dictionary itself.
        self._guard = threading.Lock()

    def get(self, user_id: str, session_id: str, mode: Mode = "graphrag") -> Agent:
        # The mode is part of the key, so the baseline and GraphRAG agents for the same chat never get mixed up.
        key = f"{mode}:{session_id}"
        with self._guard:
            # If we already have this agent, mark it as just used and hand it back.
            if key in self._agents:
                self._agents.move_to_end(key)
                return self._agents[key]
            # Otherwise build it, and if that takes us over the limit, drop the least recently used one.
            # Nothing is lost when we drop it, because its chat is already saved on disk.
            agent = build_agent(user_id, session_id, mode)
            self._agents[key] = agent
            if len(self._agents) > self.max_agents:
                old_key, _ = self._agents.popitem(last=False)
                self._locks.pop(old_key, None)
            return agent

    def lock(self, session_id: str, mode: Mode = "graphrag") -> asyncio.Lock:
        # One lock per chat. A double click or a retry can't run two turns on the same agent at once,
        # which would jumble the messages together and corrupt the history.
        return self._locks.setdefault(f"{mode}:{session_id}", asyncio.Lock())

    def drop(self, session_id: str, mode: Mode = "graphrag") -> None:
        # Called when a chat ends, to free the memory. The chat's files stay on disk for the record.
        with self._guard:
            self._agents.pop(f"{mode}:{session_id}", None)


def _usage_snapshot(agent: Agent) -> dict[str, int]:
    """Read the agent's running token totals.

    Strands only keeps a running total for the whole chat, so stream_turn takes one reading before the
    turn and one after, and subtracts them to get what this one turn used.
    """
    usage =agent.event_loop_metrics.accumulated_usage or {}
    return {k: int(usage.get(k, 0) or 0) for k in
            ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheWriteInputTokens")}


async def stream_turn(agent: Agent, message: str) -> AsyncIterator[dict[str, Any]]:
    """Run one user message and hand back events for the UI as they happen.

    These are the kinds of event it sends:
        {"type": "text", "text": "..."}            a piece of the reply
        {"type": "tool", "name": "plan_steps"}      a tool has started (for a "thinking" indicator)
        {"type": "graph", "graph": {...}}           the steps and links to draw as a diagram
        {"type": "warning", "text": "..."}          a note from the grounding check
        {"type": "handoff", "ticket": 12}           the chat was passed to a human
        {"type": "done", "usage": {...}, "latency_ms": ...}
    """
    # First, some bookkeeping for this turn. We start a timer and take a reading of token use so far.
    state = agent.state
    started = time.perf_counter()
    before = _usage_snapshot(agent)
    # Record the chat for the sidebar. On the first message this creates it with its title; after that
    # it just updates when the chat was last active.
    sqlite_store.touch_session(state.get("user_id"), state.get("session_id"),
                               state.get("mode") or "graphrag", session_title(message))
    # Clear last turn's diagram, so an old graph never shows up under a new answer. We also note the
    # current hand-off ticket so we can spot a new one being created this turn.
    state.set("last_graph", None)
    handoff_before = state.get("handoff_ticket")
    seen_tools: set[str] = set()
    # This filter removes internal requirement codes (R01, D05 and so on) from the reply as it streams.
    id_filter = RequirementIdFilter()

    # Now the main event: the Strands loop, streamed. stream_async runs the whole think, call a tool,
    # read the result, repeat cycle, and gives us events as they happen. Events with "data" are pieces
    # of reply text. We pass each one through the ID filter and send on whatever it releases. The filter
    # only holds back the last few characters, so the reply still streams smoothly.
    try:
        async for event in agent.stream_async(message):
            if "data" in event:
                visible = id_filter.feed(event["data"])
                if visible:
                    yield {"type": "text", "text": visible}
            # The same tool call shows up many times while the model is still writing its inputs, so we
            # keep track of the ones we've already announced and only mention each one once.
            tool_use = event.get("current_tool_use")
            if tool_use and tool_use.get("toolUseId") and tool_use["toolUseId"] not in seen_tools:
                seen_tools.add(tool_use["toolUseId"])
                # Send any text the filter is still holding first, so it appears before the tool
                # indicator and everything stays in the right order.
                held = id_filter.flush()
                if held:
                    yield {"type": "text", "text": held}
                yield {"type": "tool", "name": tool_use.get("name")}
    except MaxTokensReachedException:
        # The reply ran into the model's length limit. Strands has already saved the partial reply in the
        # history, so rather than crashing the turn (and with it the UI or a whole evaluation run), we end
        # it politely. The user can say "continue" and the agent will carry on from where it stopped.
        held = id_filter.flush()
        if held:
            yield {"type": "text", "text": held}
        yield {"type": "text", "text": "\n\n_(My reply was too long and got cut off. Say \"continue\" for the rest, "
                                       "or ask about one step at a time.)_"}

    # The reply is finished, so release anything the filter is still holding.
    held = id_filter.flush()
    if held:
        yield {"type": "text", "text": held}

    # Next come the extras that tools and hooks left behind during the turn: a diagram, a warning, or a
    # hand-off ticket. We send them after the text so they never hold up the answer, and the UI shows
    # them underneath it.
    if state.get("last_graph"):
        yield {"type": "graph", "graph": state.get("last_graph")}
    if state.get("grounding_warning"):
        yield {"type": "warning", "text": state.get("grounding_warning")}
    if state.get("handoff_ticket") and state.get("handoff_ticket") != handoff_before:
        yield {"type": "handoff", "ticket": state.get("handoff_ticket")}

    # Finally, work out how many tokens this turn used and how long it took, log that, and count the turn.
    # The long-term summary isn't written here; that happens later, in the background.
    after = _usage_snapshot(agent)
    usage = {k: after[k] - before[k] for k in after}
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    sqlite_store.log_turn(state.get("user_id"), state.get("session_id"), usage, latency_ms)
    state.set("turns", int(state.get("turns") or 0) + 1)
    yield {"type": "done", "usage": usage, "latency_ms": latency_ms}


def after_turn(agent: Agent, force_summary: bool = False) -> None:
    """Do the background work after a reply: refresh the user's long-term summary every few turns.

    This is kept separate from stream_turn so the server can run it after the reply has already gone
    out, and the user never waits for it.
    """
    maybe_summarise(agent.state.get("user_id"), agent.messages, int(agent.state.get("turns") or 0), force=force_summary)


async def run_turn(agent: Agent, message: str) -> dict[str, Any]:
    """Run one turn and return the whole reply at once, instead of streaming it.

    The /invoke endpoint, the command-line tests and the evaluation use this. It's built on top of
    stream_turn rather than calling the agent directly, so streaming and non-streaming callers get
    exactly the same behaviour, the same hooks and the same metrics.
    """
    reply, tools, extras = [], [], {}
    async for event in stream_turn(agent, message):
        if event["type"] == "text":
            reply.append(event["text"])
        elif event["type"] == "tool":
            tools.append(event["name"])
        elif event["type"] in ("graph", "warning", "handoff", "done"):
            extras[event["type"]] = {k: v for k, v in event.items() if k != "type"}
    return {"reply": "".join(reply), "tools_started": tools, **extras}

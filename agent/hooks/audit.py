"""
It keeps a record of every action Navi takes.

Each time Navi uses a tool (searching, planning, saving and so on), this file writes down which tool, what it was
asked, what it returned, whether it worked or was blocked, and how long it took. The record is saved in the database
and in a log file for each chat.

WHY IT MATTERS
It's how we can prove what really happened, for example that a record was never changed without the user's "yes".
The testing scripts rely on this log.
"""

import json
import time
from pathlib import Path
from typing import Any

from strands.hooks import (
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

from agent.config import get_settings
from agent.storage import sqlite_store


def _result_text(result: Any) -> str:
    """Get a tool's result as plain text, whether it came back as text, as data, or as an error.

    A tool can return text blocks, data blocks, or crash with an error. Turning all of those into one
    string means the log always looks the same.
    """
    if isinstance(result, Exception):
        return f"{type(result).__name__}: {result}"
    parts = [c.get("text", "") or json.dumps(c.get("json", "")) for c in (result or {}).get("content", []) if isinstance(c, dict)]
    return "".join(parts)


class AuditHook(HookProvider):
    def __init__(self, session_id: str):
        self.session_id = session_id
        # One JSONL file per chat. It's easy to read line by line, or to attach to the report as evidence.
        self.path = Path(get_settings().logs_dir) / f"audit_{session_id}.jsonl"
        # When each tool call started, keyed by the call's own ID rather than the tool's name, because Strands
        # can run several tools at the same time.
        self._started: dict[str, float] = {}

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self.reset_turn)
        registry.add_callback(BeforeToolCallEvent, self.start)
        registry.add_callback(AfterToolCallEvent, self.finish)

    def reset_turn(self, event: BeforeInvocationEvent) -> None:
        # At the start of a turn, clear the list of tools used. The grounding check judges one reply at a
        # time, so it must only see the tools used for that reply.
        event.agent.state.set("turn_tools", [])

    def start(self, event: BeforeToolCallEvent) -> None:
        # Start the stopwatch for this call. We write the log entry when it finishes, so the inputs we record
        # are the final ones.
        self._started[event.tool_use["toolUseId"]] = time.perf_counter()

    def finish(self, event: AfterToolCallEvent) -> None:
        tool_use = event.tool_use
        started = self._started.pop(tool_use["toolUseId"], None)
        duration_ms = round((time.perf_counter() - started) * 1000, 1) if started else None
        text = _result_text(event.result)

        # Work out what happened: the call was blocked by a hook (like the confirmation gate), it failed, or it
        # succeeded. Telling "blocked" apart from "success" is what lets the safety evaluation prove that a
        # write tool never actually ran without a yes. Our own tools report their errors as JSON starting
        # with "status":"error", so we check for that too.
        if getattr(event, "cancel_message", None) or text.startswith("CONFIRMATION_REQUIRED"):
            status = "blocked"
        elif (isinstance(event.result, Exception)
              or (isinstance(event.result, dict) and event.result.get("status") == "error")
              or text.startswith('{"status":"error"')):
            status = "error"
        else:
            status = "success"

        # Write the entry in two places: the JSONL file (easy for a person to read, one per chat) and SQLite
        # (easy for the evaluation to query). Both keep the full result, so the log is a complete record of
        # what the agent saw, plus a short preview for skimming.
        state = event.agent.state
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "session_id": self.session_id,
            "tool": tool_use["name"],
            "input": tool_use.get("input", {}),
            "status": status,
            "duration_ms": duration_ms,
            "output_preview": text[:300],
            "output": text,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
        sqlite_store.log_tool_call(state.get("user_id"), self.session_id, tool_use["name"],
                                   tool_use.get("input", {}), status, text, duration_ms)

        # Add this call to the turn's list for the grounding check. "found" notes whether the tool came back
        # with real evidence ("status":"ok"), rather than nothing relevant or an error.
        turn_tools = list(state.get("turn_tools") or [])
        turn_tools.append({"tool": tool_use["name"], "status": status, "found": '"status":"ok"' in text})
        state.set("turn_tools", turn_tools)

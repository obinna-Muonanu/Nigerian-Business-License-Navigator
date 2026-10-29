"""
It holds small helpers that all the tools share, so each tool doesn't have to repeat them.

For example, it formats a tool's answer in a compact way, gets the current user's business details, works out
whose records a tool should touch (always the current user, never someone the AI names), and keeps track of
actions waiting for the user's "yes".
"""

import json
from typing import Any

from strands import ToolContext

from agent.schemas import UserProfile


def signature(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Build a fingerprint for a write action: the tool's name plus its inputs, ignoring case and extra spaces.

    The confirmation hook ties every "yes" to one of these fingerprints. That way, a yes to "mark CAC
    registration as done" can't be used to mark a different step. It lives here rather than in the hook
    because some tools also register actions waiting for a yes (plan_steps does, with assume_done), and
    the hooks already import the tools, so putting it here avoids a circular import.
    """
    normalised = {k: " ".join(str(v).lower().split()) for k, v in sorted((tool_input or {}).items())}
    return f"{tool_name}:{json.dumps(normalised, sort_keys=True)}"


def add_pending_confirmation(ctx: ToolContext, tool_name: str, tool_input: dict[str, Any]) -> None:
    """Add a write action to the list waiting for the user's yes, in the same format the confirmation hook uses."""
    sig = signature(tool_name, tool_input)
    pending = [p for p in (ctx.agent.state.get("pending_action") or []) if p["sig"] != sig]
    pending.append({"tool": tool_name, "input": tool_input, "sig": sig})
    ctx.agent.state.set("pending_action", pending)


def as_json(payload: Any) -> str:
    """Turn a tool's result into compact JSON text, which is small (fewer tokens) and easy for the model to read.

    It leaves out the spaces JSON normally adds, which saves tokens on every result. It keeps characters
    like "₦" and Pidgin text readable instead of turning them into escape codes. And if a value is
    something unusual, like a date, it's simply turned into text so the tool doesn't crash.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def ok(**payload: Any) -> str:
    """Build a success reply. The audit and grounding hooks look for "status":"ok" at the start."""
    return as_json({"status": "ok", **payload})


def error(message: str, **payload: Any) -> str:
    """Build a reply for an expected problem, like bad input or a step we can't find.

    It's returned as text rather than raised as an error, so the model can read the message and recover,
    for example by asking the user again or retrying with a valid code, instead of the whole turn crashing.
    """
    return as_json({"status": "error", "message": message, **payload})


def profile_of(ctx: ToolContext) -> UserProfile:
    """Get the user's current profile from the agent's state (where it was loaded from long-term memory).

    It's rebuilt as a proper UserProfile each time, so the tools work with checked, typed facts rather
    than a loose dictionary.
    """
    return UserProfile(**(ctx.agent.state.get("profile") or {}))


def ids_of(ctx: ToolContext) -> tuple[str, str]:
    """Get the user's ID and the chat's ID, for saving things.

    These always come from the agent's state, never from the tool's inputs. The model must never be able
    to choose whose records a tool writes to.
    """
    return ctx.agent.state.get("user_id"), ctx.agent.state.get("session_id")

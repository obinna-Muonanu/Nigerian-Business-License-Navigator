"""
It makes sure Navi never changes a user's records without a clear "yes" from the user first.

Three actions change records: saving a checklist, marking a step as done, and setting a reminder. When Navi tries one,
this file stops it and has Navi ask the user to confirm. Only when the user replies with a short, clear "yes" (in
English or Pidgin, like "yes", "go ahead" or "abeg do am") is that exact action allowed to run. A "no" cancels it, and
any unused approval expires at the end of the turn.

WHY IT MATTERS
The brief requires an explicit yes before any record changes. Because this is code, not just an instruction to the AI,
tricks like "the user already confirmed" don't work.
"""

import json
import re
from typing import Any

from strands.hooks import (
    AfterInvocationEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

from agent.hooks._messages import add_policy_note, last_user_text_message, text_of
from agent.knowledge import graph_service
from agent.storage import sqlite_store
from agent.tools import WRITE_TOOLS
# The fingerprint function is shared with the tools (plan_steps registers actions waiting for a yes), so it lives in _common.
from agent.tools._common import signature

# A clear yes or no at the start of a short message, in English or Pidgin. The yes has to be how the message
# opens, so something like "I said no, yes I know" doesn't count as a yes.
AFFIRM = re.compile(
    r"^\s*(yes|yeah|yep|yup|y|ok|okay|sure|go ahead|do it|confirm(ed)?|proceed|please do|correct|"
    r"abeg do am|do am|oya|na so|e correct|yes o|yes please|alright)\b",
    re.IGNORECASE,
)
NEGATE = re.compile(r"^\s*(no|nope|don'?t|do not|cancel|stop|wait|no o|abeg no|leave am|not now)\b", re.IGNORECASE)
# A long message that happens to start with "ok" isn't a confirmation, so a yes has to be this short.
MAX_CONFIRM_MESSAGE_WORDS = 12

# For Path B: the words that tell us which write tool the model's own question was about.
ACTION_WORDS = {
    "save_checklist": re.compile(r"\bsav(e|ing)\b", re.IGNORECASE),
    "update_progress": re.compile(r"\b(mark|marking|record|recording|update|updating)\b", re.IGNORECASE),
    "set_reminder": re.compile(r"\bremind", re.IGNORECASE),
}


def _last_assistant_text(messages: list[dict]) -> str:
    """Get the text of the assistant's most recent reply, which is what the user is answering."""
    for message in reversed(messages or []):
        if message.get("role") == "assistant":
            text = text_of(message)
            if text:
                return text
    return ""


def _tools_asked_about(assistant_text: str) -> list[str]:
    """For Path B, find which write tools the assistant's last reply asked permission for.

    It only counts if the reply ends with a question (there's a "?" near the end). That way an unrelated
    yes, like answering "Do you sell online?", can never unlock a write.
    """
    if "?" not in assistant_text[-300:]:
        return []
    question = assistant_text[-600:]
    return [tool for tool, words in ACTION_WORDS.items() if words.search(question)]


# This hook keeps three things in the agent's state, which is saved with the chat so it survives a restart:
#   pending_action   the write calls it blocked and asked the user to confirm (Path A)
#   approved_action  the ones the user has just said yes to (Path A, this turn only)
#   approved_tools   the tools the user said yes to in words (Path B, one call each, this turn only)
class ConfirmationHook(HookProvider):
    # It listens at three moments: at the start of a turn to read the user's answer, before every tool call
    # to decide whether it may run, and at the end of a turn to expire unused approvals.
    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self.read_user_answer)
        registry.add_callback(BeforeToolCallEvent, self.gate)
        registry.add_callback(AfterInvocationEvent, self.expire_approvals)

    def read_user_answer(self, event: BeforeInvocationEvent) -> None:
        """At the start of a turn, work out whether the user has just said yes or no."""
        state = event.agent.state
        message = last_user_text_message(event.messages)
        if message is None:
            return
        text = text_of(message)
        short = len(text.split()) <= MAX_CONFIRM_MESSAGE_WORDS
        pending = state.get("pending_action") or []

        # A no clears everything, so the action can't be approved later by some unrelated "ok".
        if NEGATE.match(text) and (pending or state.get("approved_tools")):
            state.set("pending_action", None)
            state.set("approved_action", None)
            state.set("approved_tools", None)
            add_policy_note(message, "the user declined the pending action. Do not perform it.")
            return
        if not (short and AFFIRM.match(text)):
            return

        if pending:
            # Path A: approve exactly the calls the hook blocked (the user was shown all of them), and tell
            # the model to make those calls again, so their fingerprints match when they reach the gate.
            state.set("approved_action", pending)
            calls = "; ".join(f"{p['tool']}({json.dumps(p['input'])})" for p in pending)
            add_policy_note(message, f"the user confirmed: {calls}. Call it now with exactly these inputs.")
            return

        # Path B: nothing has been blocked yet, but the yes is about a named action. Either the assistant's
        # last reply asked permission for it, or the user's own yes says what to do ("Yes, please mark it as
        # done"). The new user message isn't in the agent's messages yet, so the last assistant reply there is
        # the question being answered.
        tools = _tools_asked_about(_last_assistant_text(event.agent.messages))
        tools += [tool for tool, words in ACTION_WORDS.items() if words.search(text) and tool not in tools]
        if tools:
            state.set("approved_tools", tools)
            add_policy_note(message, f"the user said yes to the action you asked about ({', '.join(tools)}). "
                                     "Call that tool now; do not ask again.")

    def gate(self, event: BeforeToolCallEvent) -> None:
        """Before every tool call, let a write through only if there's a matching approval."""
        name = event.tool_use["name"]
        # Tools that only read are never held back. Asking permission to search would just slow the user down.
        if name not in WRITE_TOOLS:
            return
        state = event.agent.state
        tool_input = event.tool_use.get("input") or {}
        sig = signature(name, tool_input)

        # Path A: there's an approval for this exact call (the same tool with the same inputs).
        approved = state.get("approved_action") or []
        if any(a["sig"] == sig for a in approved):
            # Use the approval up, so it can't be used again.
            state.set("approved_action", [a for a in approved if a["sig"] != sig] or None)
            remaining = [p for p in (state.get("pending_action") or []) if p["sig"] != sig]
            state.set("pending_action", remaining or None)
            return

        # Marking a step done when it's already recorded changes nothing, so there's nothing to confirm. We
        # added this because in the evaluation, users said "I've done X, what's left?" about steps already on
        # record. The hook blocked the pointless update, and the agent then held back its answer while waiting
        # for a yes.
        if name == "update_progress" and self._already_recorded(state, tool_input):
            return

        # Path B: the user said yes to this kind of action, so allow one call of it.
        approved_tools = state.get("approved_tools") or []
        if name in approved_tools:
            approved_tools.remove(name)
            state.set("approved_tools", approved_tools or None)
            return

        # No approval, so block the call and remember what the user needs to confirm. Setting cancel_tool stops
        # Strands from running the tool, and the message becomes the result the model reads. It tells the model
        # to ask the user, and not to claim the action happened.
        pending = [p for p in (state.get("pending_action") or []) if p["sig"] != sig]
        pending.append({"tool": name, "input": tool_input, "sig": sig})
        state.set("pending_action", pending)
        # The message also tells the model to keep answering. A pending confirmation must never hide the answer
        # to the user's real question, like "what's left?". The model follows instructions in a tool result
        # much more reliably than the same rule buried in the system prompt.
        event.cancel_tool = (
            f"CONFIRMATION_REQUIRED: {name} was NOT run and nothing was changed. Do NOT tell the user it is "
            f"done. Still answer the user's question fully in this reply (for progress, call plan_steps with "
            f"assume_done and show what is left). At the END of the reply, describe this action "
            f"({json.dumps(tool_input)}) by the step's plain name, never its ID, and ask for a clear yes. "
            "Call it again with the same inputs only after they confirm."
        )

    @staticmethod
    def _already_recorded(state: Any, tool_input: dict[str, Any]) -> bool:
        """Check whether this is a request to mark a step done that's already in the user's progress.

        If anything goes wrong while checking, it answers "no", so the safe default (asking for a yes) still applies.
        """
        if (tool_input.get("status") or "done") != "done":
            return False
        try:
            resolved = graph_service.resolve_requirement(str(tool_input.get("requirement", "")))
            if not resolved:
                return False
            done = set(sqlite_store.completed_steps(state.get("user_id")))
            return graph_service.is_recorded_done(resolved["id"], done)
        except Exception:
            return False

    def expire_approvals(self, event: AfterInvocationEvent) -> None:
        """At the end of a turn, throw away any approvals that weren't used."""
        # A yes that wasn't used mustn't hang around, or a later, unrelated turn could end up running the action.
        event.agent.state.set("approved_action", None)
        event.agent.state.set("approved_tools", None)

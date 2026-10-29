"""WHAT THIS FOLDER IS
This folder holds Navi's safety rules. They're written as code that runs automatically around every message and every
action, so the AI can't ignore them or be talked out of them.

There are five:
    input_guard.py   checks each incoming message (language, private numbers, trick instructions).
    confirmation.py  stops any change to the user's records until they clearly say "yes".
    audit.py         keeps a log of every action Navi takes.
    grounding.py     checks each reply for facts without sources, and for false "done" claims.
    compaction.py    trims old search results to keep conversations cheap.

This file creates a fresh set of these rules for each chat.
"""

from agent.hooks.audit import AuditHook
from agent.hooks.compaction import CompactionHook
from agent.hooks.confirmation import ConfirmationHook
from agent.hooks.grounding import GroundingHook
from agent.hooks.input_guard import InputGuardHook


def build_hooks(session_id: str, compact: bool = True) -> list:
    """Create the full set of hooks for one chat.

    Every chat gets brand-new hooks, because the audit hook remembers its chat's log file and its timers,
    so hooks must never be shared between chats. You can switch compaction off, which is handy for
    measuring how many tokens it saves in a test.
    """
    hooks = [InputGuardHook(), ConfirmationHook(), AuditHook(session_id), GroundingHook()]
    if compact:
        hooks.append(CompactionHook())
    return hooks


__all__ = ["build_hooks", "InputGuardHook", "ConfirmationHook", "AuditHook", "GroundingHook", "CompactionHook"]

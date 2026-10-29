"""
This is the tool Navi uses to set a reminder for a step on a future date.

It checks the date is real and not in the past, works out which step the reminder is for, and saves it. In this
project the reminder is a demonstration: it's saved, but no message is actually sent. Because it changes the user's
records, it only runs after the user has clearly said "yes".
"""

from datetime import date

from strands import ToolContext, tool

from agent.knowledge import graph_service
from agent.storage import sqlite_store
from agent.tools._common import error, ids_of, ok


@tool(context=True)
def set_reminder(requirement: str, remind_on: str, tool_context: ToolContext, note: str = "") -> str:
    """Create a (mock) reminder for a step on a future date. Changes a record: ask the user first and only
    call after a clear yes.

    Args:
        requirement: Requirement ID or name.
        remind_on: Date in YYYY-MM-DD format, today or later.
        note: Optional short note, e.g. "Bring the lab results".
    """
    # Check the date before saving anything. The model works the date out itself from things like "next
    # Monday" or "15 Jan", so a badly formatted or past date is caught here and sent back as an error the
    # model can fix, rather than being saved as a useless reminder.
    try:
        when = date.fromisoformat(remind_on)
    except ValueError:
        return error("remind_on must be a date like 2026-11-15.")
    if when < date.today():
        return error("The reminder date is in the past.")

    # Work out which step the reminder is for. The user might give a code or a name.
    resolved = graph_service.resolve_requirement(requirement)
    if not resolved:
        return error(f"No requirement matches '{requirement}'.")

    # Save the reminder.
    user_id, _ = ids_of(tool_context)
    reminder_id = sqlite_store.add_reminder(user_id, resolved["id"], when.isoformat(), note[:200])
    return ok(reminder_id=reminder_id, requirement=resolved, remind_on=when.isoformat(),
              message="Reminder saved (mock: no message is actually sent).")

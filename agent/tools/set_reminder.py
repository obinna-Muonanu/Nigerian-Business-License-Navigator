"""
This is the tool Navi uses to set a reminder for a step on a future date.

It checks the date is real and not in the past, works out which step and which business the reminder is for, and
saves it. In this project the reminder is a demonstration: it's saved, but no message is actually sent. Because it
changes the user's records, it only runs after the user has clearly said "yes".
"""

from datetime import date

from strands import ToolContext, tool

from agent.knowledge import graph_service
from agent.memory import BusinessNotFound
from agent.storage import store
from agent.tools._common import business_of, error, ids_of, ok


@tool(context=True)
def set_reminder(requirement: str, remind_on: str, tool_context: ToolContext, note: str = "",
                 business: str | None = None) -> str:
    """Create a (mock) reminder for a step on a future date. Changes a record: ask the user first and only
    call after a clear yes.

    Args:
        requirement: Requirement ID or name.
        remind_on: Date in YYYY-MM-DD format, today or later.
        note: Optional short note, e.g. "Bring the lab results".
        business: Which business (its label). Required when the user has more than one business.
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

    # Work out which step the reminder is for (the user might give a code or a name), and which business.
    resolved = graph_service.resolve_requirement(requirement)
    if not resolved:
        return error(f"No requirement matches '{requirement}'.")
    try:
        target = business_of(tool_context, business, create_if_none=True)
    except BusinessNotFound as exc:
        return error(str(exc))

    # Save the reminder.
    user_id, _ = ids_of(tool_context)
    reminder_id = store.add_reminder(user_id, target.business_id, resolved["id"], when.isoformat(), note[:200])
    return ok(business=target.label, reminder_id=reminder_id, requirement=resolved, remind_on=when.isoformat(),
              message="Reminder saved (mock: no message is actually sent).")

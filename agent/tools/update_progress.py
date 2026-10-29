"""
This is the tool Navi uses to record that the user has finished a step (or to reopen one).

It saves the progress so future checklists leave that step out. If the finished step is CAC registration, it also
remembers that the business is now registered. If the step was already recorded, nothing changes. Because it changes
the user's records, it only runs after the user has clearly said "yes".
"""

from strands import ToolContext, tool

from agent.knowledge import graph_service
from agent.memory import LongTermMemory
from agent.storage import sqlite_store
from agent.tools._common import error, ids_of, ok, profile_of


@tool(context=True)
def update_progress(requirement: str, tool_context: ToolContext, status: str = "done") -> str:
    """Record that the user has completed a step (or reopen it). Changes a record: ask the user first and
    only call after a clear yes. Afterwards call plan_steps to show what is left.

    Args:
        requirement: Requirement ID or name, e.g. "R01" or "CAC business registration".
        status: "done" (default) or "pending" to reopen a step.
    """
    # Check the inputs before saving anything.
    if status not in ("done", "pending"):
        return error("status must be 'done' or 'pending'.")
    resolved = graph_service.resolve_requirement(requirement)
    if not resolved:
        return error(f"No requirement matches '{requirement}'.")

    # If the step is already recorded as done, just say so. (The confirmation hook lets this through
    # without asking, because nothing actually changes.)
    user_id, _ = ids_of(tool_context)
    if status == "done" and graph_service.is_recorded_done(resolved["id"], set(sqlite_store.completed_steps(user_id))):
        return ok(requirement=resolved, new_status="done", already_recorded=True,
                  next="Nothing changed: this step was already recorded. Call plan_steps to show what is left.")

    # Record the progress against the user, so it carries over to future chats.
    sqlite_store.set_progress(user_id, resolved["id"], status)

    # Finishing CAC registration (or one of its routes) is also worth remembering as a fact about the user.
    # Updating the profile as well as the progress keeps the two in step: the next chat's memory block says
    # "registered with CAC", and the planner already treats CAC registration as done. Annual returns (R01-AR)
    # are left out, because filing returns isn't the same thing as registering.
    if status == "done" and resolved["id"].startswith("R01") and resolved["id"] != "R01-AR":
        profile = LongTermMemory.remember(user_id, profile_of(tool_context), "cac_registered", "yes")
        tool_context.agent.state.set("profile", profile.model_dump())

    return ok(requirement=resolved, new_status=status, next="Call plan_steps to re-plan the remaining steps.")

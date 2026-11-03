"""
This is the tool Navi uses to record that one of the user's businesses has finished a step (or to reopen one).

It saves the progress against that business, so its future checklists leave the step out. If the finished step is
CAC registration, it also remembers that the business is now registered. If the step was already recorded, nothing
changes. Because it changes the user's records, it only runs after the user has clearly said "yes".
"""

from strands import ToolContext, tool

from agent.knowledge import graph_service
from agent.memory import BusinessNotFound, LongTermMemory
from agent.storage import store
from agent.tools._common import business_of, error, ids_of, ok


@tool(context=True)
def update_progress(requirement: str, tool_context: ToolContext, status: str = "done",
                    business: str | None = None) -> str:
    """Record that one of the user's businesses has completed a step (or reopen it). Changes a record: ask the
    user first and only call after a clear yes. Afterwards call plan_steps to show what is left.

    Args:
        requirement: Requirement ID or name, e.g. "R01" or "CAC business registration".
        status: "done" (default) or "pending" to reopen a step.
        business: Which business (its label). Required when the user has more than one business.
    """
    # Check the inputs before saving anything.
    if status not in ("done", "pending"):
        return error("status must be 'done' or 'pending'.")
    resolved = graph_service.resolve_requirement(requirement)
    if not resolved:
        return error(f"No requirement matches '{requirement}'.")
    try:
        target = business_of(tool_context, business)
    except BusinessNotFound as exc:
        return error(str(exc))
    if target is None:
        return error("Nothing is known about the user's business yet. Save its facts with remember_profile first.")

    # If the step is already recorded as done, just say so. (The confirmation hook lets this through
    # without asking, because nothing actually changes.)
    if status == "done" and graph_service.is_recorded_done(resolved["id"], set(target.completed)):
        return ok(business=target.label, requirement=resolved, new_status="done", already_recorded=True,
                  next="Nothing changed: this step was already recorded. Call plan_steps to show what is left.")

    # Record the progress against this business, so it carries over to future chats.
    user_id, session_id = ids_of(tool_context)
    store.set_progress(target.business_id, resolved["id"], status, "user_stated", session_id)

    # Finishing CAC registration (or one of its routes) is also worth remembering as a fact about the business.
    # Updating the profile as well as the progress keeps the two in step: the next chat's memory block says
    # "registered with CAC", and the planner already treats CAC registration as done. The user has just confirmed
    # the step, so this counts as a confirmed change. Annual returns (R01-AR) are left out, because filing returns
    # isn't the same thing as registering.
    if status == "done" and resolved["id"].startswith("R01") and resolved["id"] != "R01-AR":
        LongTermMemory.remember(user_id, target, "cac_registered", "yes", source="progress_update",
                                session_id=session_id, confirm_change=True)

    return ok(business=target.label, requirement=resolved, new_status=status,
              next="Call plan_steps to re-plan the remaining steps.")

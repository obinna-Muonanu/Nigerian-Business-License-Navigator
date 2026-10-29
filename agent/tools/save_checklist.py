"""
This is the tool Navi uses to save the user's checklist, so it's there next time.

It rebuilds the checklist fresh from the knowledge graph right before saving, so the saved copy can never contain a
made-up step or steps in the wrong order. Because it changes the user's records, the safety rules make sure it only
runs after the user has clearly said "yes".
"""

from strands import ToolContext, tool

from agent.knowledge import graph_service
from agent.storage import sqlite_store
from agent.tools._common import error, ids_of, ok, profile_of


@tool(context=True)
def save_checklist(tool_context: ToolContext) -> str:
    """Save the user's current ordered checklist so it is there next time. Changes a record: ask the user
    first and only call after a clear yes.
    """
    # Build the plan again right now, so the saved copy matches the latest profile and progress. The tool
    # deliberately takes no inputs: it saves what the planner works out, not a list the model typed out, so
    # the saved checklist can never contain a made-up step or steps in the wrong order.
    profile = profile_of(tool_context)
    user_id, _ = ids_of(tool_context)
    plan = graph_service.plan_steps(profile, set(sqlite_store.completed_steps(user_id)))
    if plan["status"] != "ok":
        return error("Cannot save yet: the profile is incomplete.", missing=plan.get("missing"))

    # Save a compact copy of each remaining step: its code, name and status.
    steps = [{"id": s["id"], "name": s["name"], "status": s["status"]} for s in plan["remaining_steps"]]
    sqlite_store.save_checklist(user_id, profile.business_type, profile.state, steps)
    return ok(saved_steps=len(steps), message="Checklist saved.")

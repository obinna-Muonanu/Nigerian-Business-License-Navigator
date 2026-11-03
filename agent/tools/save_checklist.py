"""
This is the tool Navi uses to save a business's checklist, so it's there next time.

It rebuilds the checklist fresh from the knowledge graph right before saving, so the saved copy can never contain a
made-up step or steps in the wrong order. Each business keeps its own saved checklist. Because this changes the
user's records, the safety rules make sure it only runs after the user has clearly said "yes".
"""

from strands import ToolContext, tool

from agent.knowledge import graph_service
from agent.memory import BusinessNotFound
from agent.storage import store
from agent.tools._common import business_of, error, ids_of, ok


@tool(context=True)
def save_checklist(tool_context: ToolContext, business: str | None = None) -> str:
    """Save one business's current ordered checklist so it is there next time. Changes a record: ask the user
    first and only call after a clear yes.

    Args:
        business: Which business (its label). Required when the user has more than one business.
    """
    # Find the business, then build its plan again right now, so the saved copy matches the latest profile and
    # progress. The tool deliberately takes no list of steps: it saves what the planner works out, not a list the
    # model typed out, so the saved checklist can never contain a made-up step or steps in the wrong order.
    try:
        target = business_of(tool_context, business)
    except BusinessNotFound as exc:
        return error(str(exc))
    if target is None:
        return error("Cannot save yet: nothing is known about the user's business.")
    plan = graph_service.plan_steps(target.profile, set(target.completed))
    if plan["status"] != "ok":
        return error("Cannot save yet: the profile is incomplete.", missing=plan.get("missing"))

    # Save a compact copy of each remaining step: its code, name and status.
    user_id, _ = ids_of(tool_context)
    steps = [{"id": s["id"], "name": s["name"], "status": s["status"]} for s in plan["remaining_steps"]]
    store.save_checklist(user_id, target.business_id, target.profile.business_type, target.profile.state, steps)
    return ok(business=target.label, saved_steps=len(steps), message="Checklist saved.")

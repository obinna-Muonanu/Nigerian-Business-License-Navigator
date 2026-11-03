"""
This is the tool Navi uses to build a checklist: every step one of the user's businesses needs, in the right order.

It uses that business's saved details and the steps it has already finished, and leaves the finished ones out. A
user with several businesses gets one checklist per business, by calling this tool once for each.
Each step says whether it can be started now or what it's waiting on, and which official document it comes from.

If the user has just said they finished a step that isn't recorded yet, the checklist leaves it out straight away,
so the user gets their answer immediately, while Navi asks for a "yes" before actually recording the progress.
"""

from strands import ToolContext, tool

from agent.knowledge import graph_service
from agent.memory import BusinessNotFound
from agent.schemas import UserProfile
from agent.tools._common import add_pending_confirmation, as_json, business_of, error


@tool(context=True)
def plan_steps(tool_context: ToolContext, business: str | None = None, assume_done: list[str] | None = None) -> str:
    """Ordered checklist for ONE of the user's businesses, following the dependency graph and leaving out steps
    already completed. Each step says whether it is ready now or what it is waiting on, and has a `source`
    number pointing into `sources` (cite it as a footnote).
    Call it for "what do I need, and in what order?" and whenever the user reports progress. For several
    businesses, call it once per business.

    Args:
        business: Which business (its label). Required when the user has more than one business.
        assume_done: Steps the user says they have just finished but that are not recorded yet (names or IDs),
            e.g. ["CAC business registration"]. They are left out of the plan, so you can show what is left
            straight away while update_progress waits for the user's yes.
    """
    # Get the business's remembered profile and the steps it has finished, fresh from the database. The plan is
    # always built from the real stored profile, so the model can't plan from a profile it imagined.
    try:
        target = business_of(tool_context, business)
    except BusinessNotFound as exc:
        return error(str(exc))
    profile = target.profile if target else UserProfile()
    done = set(target.completed if target else [])

    # Add any steps the user has only just told us they finished. Recording progress needs their yes first,
    # but their question "what's left?" deserves an answer now, not after another round of back and forth.
    assumed = []
    for ref in assume_done or []:
        resolved = graph_service.resolve_requirement(ref)
        if resolved:
            done.add(resolved["id"])
            assumed.append(resolved["name"])

    plan = graph_service.plan_steps(profile, done)
    if plan["status"] != "ok":
        return as_json({**plan, "business": target.label if target else None,
                        "message": "Ask the user for the missing details first."})
    # Label the plan with its business, so a reply covering several businesses keeps them apart.
    plan = {"business": target.label, **plan}

    # Keep the diagram data for the UI, but take it out of what the model sees so it doesn't cost tokens.
    # core.stream_turn sends it on to the UI.
    tool_context.agent.state.set("last_graph", plan.pop("graph"))
    tool_context.agent.state.set("last_plan_ids", [s["id"] for s in plan["remaining_steps"]])
    if assumed:
        # Register "shall I record these steps as done?" as actions waiting for a yes, exactly as if
        # update_progress had been blocked. We do this because the model sometimes showed the plan but never
        # called update_progress, so the user's "yes" had nothing to approve and the agent then called the
        # wrong tool. Now a yes approves exactly these updates, and the hook tells the model which calls to make.
        # The business is included in the action exactly as the model named it, so its follow-up
        # update_progress call (with the same inputs) matches the approval.
        for name in assumed:
            action = {"requirement": name, "status": "done", **({"business": business} if business else {})}
            add_pending_confirmation(tool_context, "update_progress", action)
        plan["assumed_done_not_recorded"] = assumed
        plan["next"] = ("Show what is left, then ask the user to confirm recording these steps as done. "
                        "When they say yes, call update_progress for each one, with the same business.")
    return as_json(plan)

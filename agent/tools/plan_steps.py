"""
This is the tool Navi uses to build the user's checklist: every step their business needs, in the right order.

It uses the user's saved business details and the steps they've already finished, and leaves the finished ones out.
Each step says whether it can be started now or what it's waiting on, and which official document it comes from.

If the user has just said they finished a step that isn't recorded yet, the checklist leaves it out straight away,
so the user gets their answer immediately, while Navi asks for a "yes" before actually recording the progress.
"""

from strands import ToolContext, tool

from agent.knowledge import graph_service
from agent.storage import sqlite_store
from agent.tools._common import add_pending_confirmation, as_json, ids_of, profile_of


@tool(context=True)
def plan_steps(tool_context: ToolContext, assume_done: list[str] | None = None) -> str:
    """Ordered checklist for the user's business, following the dependency graph and leaving out steps
    already completed. Each step says whether it is ready now or what it is waiting on, and has a `source`
    number pointing into `sources` (cite it as a footnote).
    Call it for "what do I need, and in what order?" and whenever the user reports progress.

    Args:
        assume_done: Steps the user says they have just finished but that are not recorded yet (names or IDs),
            e.g. ["CAC business registration"]. They are left out of the plan, so you can show what is left
            straight away while update_progress waits for the user's yes.
    """
    # Get the user's remembered profile and the steps they've finished. Progress comes from SQLite, saved
    # against the user, so it carries over between chats. The plan is always built from this user's real
    # profile, so the model can't plan from a profile it imagined.
    profile = profile_of(tool_context)
    user_id, _ = ids_of(tool_context)
    done = set(sqlite_store.completed_steps(user_id))

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
        return as_json({**plan, "message": "Ask the user for the missing details first."})

    # Keep the diagram data for the UI, but take it out of what the model sees so it doesn't cost tokens.
    # core.stream_turn sends it on to the UI.
    tool_context.agent.state.set("last_graph", plan.pop("graph"))
    tool_context.agent.state.set("last_plan_ids", [s["id"] for s in plan["remaining_steps"]])
    if assumed:
        # Register "shall I record these steps as done?" as actions waiting for a yes, exactly as if
        # update_progress had been blocked. We do this because the model sometimes showed the plan but never
        # called update_progress, so the user's "yes" had nothing to approve and the agent then called the
        # wrong tool. Now a yes approves exactly these updates, and the hook tells the model which calls to make.
        for name in assumed:
            add_pending_confirmation(tool_context, "update_progress", {"requirement": name, "status": "done"})
        plan["assumed_done_not_recorded"] = assumed
        plan["next"] = ("Show what is left, then ask the user to confirm recording these steps as done. "
                        "When they say yes, call update_progress for each one.")
    return as_json(plan)

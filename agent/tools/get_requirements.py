"""
This is the tool Navi uses to list every registration, licence and permit that applies to a type of business in a
particular state.

Each item is marked as required, optional, or "depends" (for example, "only if you sell online"). The list isn't in
any particular order; for an ordered checklist, Navi uses the plan_steps tool instead.
"""

from strands import ToolContext, tool

from agent.knowledge import graph_service
from agent.tools._common import error, ok, profile_of


@tool(context=True)
def get_requirements(tool_context: ToolContext, business_type: str | None = None, state: str | None = None) -> str:
    """List every registration, licence and permit linked to a business type in a state, each marked
    required, conditional (depends on something not known yet) or optional. Unordered; use plan_steps
    for an ordered checklist.

    Args:
        business_type: DRINKS, PHARM, COSM or FURN. Defaults to the user's profile.
        state: Oyo, Lagos, FCT, Rivers, Ogun or Edo. Defaults to the user's profile.
    """
    # Start from the user's remembered profile, but let the model swap in a different business type or state.
    # That's what lets the user ask something like "and what about Lagos?".
    profile = profile_of(tool_context)
    updates = {k: v for k, v in {"business_type": (business_type or "").upper() or None,
                                 "state": state}.items() if v}
    profile = profile.model_copy(update=updates)
    if not profile.business_type or not profile.state:
        return error("Business type and state are needed first.", missing=profile.missing_for_planning())

    # Ask the graph, keep only the requirements that apply, and send back just the useful fields. Internal
    # details like dependencies and conditions are left out to keep the result small; questions about order
    # belong to plan_steps anyway.
    rows = graph_service.get_requirements(profile)
    applicable = [
        {k: r[k] for k in ("id", "name", "regulator", "status", "note") if r.get(k)}
        for r in rows if r["status"] != "no"
    ]
    return ok(business_type=profile.business_type, state=profile.state, requirements=applicable)

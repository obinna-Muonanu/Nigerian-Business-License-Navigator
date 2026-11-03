"""
This is the tool Navi uses when a user mentions another business they want to register.

One person can run several businesses, say a zobo drinks business in Oyo and a pharmacy in Lagos, and each needs its
own checklist and progress. This tool creates a new, empty business with a short name the user will recognise, so
Navi can then save its facts and plan it separately from the others.

If the user is really coming back to a business they set aside months ago (an "inactive" one), the tool brings that
business back with all its saved details instead of creating an empty duplicate, and tells Navi so.

Like remember_profile, it doesn't ask permission first, because the user has just told Navi about the business.
"""

from strands import ToolContext, tool

from agent.memory import LongTermMemory
from agent.storage import store
from agent.tools._common import error, ids_of, ok


@tool(context=True)
def add_business(name: str, tool_context: ToolContext, force_new: bool = False) -> str:
    """Create a new business for this user, when they want help with a business that is not in the memory
    block yet. Then save its facts with remember_profile(business=<name>) and plan it with plan_steps(business=<name>).
    If the name matches one of the user's INACTIVE businesses, that business is brought back instead, with its saved
    details.

    Args:
        name: A short name the user will recognise, e.g. "zobo business", "Lagos pharmacy", "Glow Cosmetics".
        force_new: Set true only when the user has confirmed this is a different business from an inactive one with
            a similar name.
    """
    user_id, _ = ids_of(tool_context)
    try:
        business = LongTermMemory.add_business(user_id, name, force_new=force_new)
    except ValueError as exc:
        return error(str(exc))

    # The user was coming back to a business they'd set aside: say so, and list what's already known about it, so
    # Navi carries on from there instead of asking everything again.
    if business.reactivated:
        return ok(business=business.label, reactivated=True,
                  known_profile=business.profile.model_dump(exclude_none=True),
                  still_missing_for_planning=business.profile.missing_for_planning(),
                  next=(f'This is the user\'s existing business "{business.label}", which had been inactive. It is '
                        "active again with its saved details: do not ask again for what is already known. If the "
                        "user actually meant a separate, new business, ask them, then call add_business again with "
                        "force_new=true."))

    # Listing every business tells the model the exact labels to use in later tool calls.
    return ok(business=business.label,
              all_businesses=[b["label"] for b in store.list_businesses(user_id)],
              next=f'Save this business\'s facts with remember_profile(business="{business.label}").')

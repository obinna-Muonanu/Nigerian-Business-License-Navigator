"""
This is the tool Navi uses to remember a fact about one of the user's businesses, such as what it sells, its state,
or whether it's registered with CAC.

It saves the fact straight away, so future chats already know it and the user is never asked the same question
twice. Only a short, approved list of business facts can be saved. Each fact is saved with where it came from and
when. If the user says something that contradicts a fact already saved, the tool doesn't overwrite it; it tells Navi
about the conflict, and Navi checks with the user first.

Navi doesn't ask permission before using this tool, because the user has just told it the fact themselves.
"""

from strands import ToolContext, tool

from agent.memory import BusinessNotFound, LongTermMemory
from agent.tools._common import as_json, business_of, error, ids_of, ok


@tool(context=True)
def remember_profile(field: str, value: str, tool_context: ToolContext, business: str | None = None,
                     confirm_change: bool = False) -> str:
    """Save one fact about one of the user's businesses so future sessions already know it. Call it as soon as
    the user tells you something. The user's first business is created automatically.

    Args:
        field: One of business_type (DRINKS|PHARM|COSM|FURN), state (Oyo|Lagos|FCT|Rivers|Ogun|Edo),
            legal_structure (sole_proprietorship|partnership|private_company|public_company|undecided),
            cac_registered (yes|no), sells_online (yes|no), collects_personal_data (yes|no),
            product_variant (resell|import|make_locally), business_name.
        value: The value, using the codes above.
        business: Which business (its label from the memory block or add_business). Required when the user has
            more than one business.
        confirm_change: Set true only when the user has clearly said this fact CHANGED, or has confirmed the
            new value after you asked about a FACT_CONFLICT.
    """
    user_id, session_id = ids_of(tool_context)
    # Find the business. For a brand-new user this creates their first one, so a user with a single business
    # never has to think about businesses at all.
    try:
        target = business_of(tool_context, business, create_if_none=True)
        result = LongTermMemory.remember(user_id, target, field, value, source="user_stated",
                                         session_id=session_id, confirm_change=confirm_change)
    except (BusinessNotFound, ValueError) as exc:
        return error(str(exc))

    # A conflict means nothing was saved. The message tells the model exactly what to do next, because a model
    # follows an instruction in a tool result much more reliably than a rule buried in the system prompt.
    if result.conflict:
        c = result.conflict
        return as_json({
            "status": "FACT_CONFLICT", "business": target.label, **c,
            "message": (f"Nothing was saved. Memory already says {c['field']} = {c['stored_value']!r}, but you "
                        f"tried to save {c['new_value']!r}. Ask the user which is right. If they confirm the "
                        "change, call remember_profile again with confirm_change=true."),
        })

    # Sending back what's still missing tells the model which clarifying question to ask next.
    saved = result.business
    return ok(business=saved.label, saved={field: getattr(saved.profile, field)},
              still_missing_for_planning=saved.profile.missing_for_planning())

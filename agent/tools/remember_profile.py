"""
This is the tool Navi uses to remember a fact about the user's business, such as what they sell, their state, or
whether they're registered with CAC.

It saves the fact straight away, so future chats already know it and the user is never asked the same question
twice. Only a short, approved list of business facts can be saved. Navi doesn't ask permission before using this
tool, because the user has just told it the fact themselves.
"""

from strands import ToolContext, tool

from agent.memory import LongTermMemory
from agent.tools._common import error, ids_of, ok, profile_of


@tool(context=True)
def remember_profile(field: str, value: str, tool_context: ToolContext) -> str:
    """Save one fact about the user's business so future sessions already know it. Call it as soon as the
    user tells you something, and again if it changes.

    Args:
        field: One of business_type (DRINKS|PHARM|COSM|FURN), state (Oyo|Lagos|FCT|Rivers|Ogun|Edo),
            legal_structure (sole_proprietorship|partnership|private_company|public_company|undecided),
            cac_registered (yes|no), sells_online (yes|no), collects_personal_data (yes|no),
            product_variant (resell|import|make_locally), business_name.
        value: The value, using the codes above.
    """
    # Check the fact and save it straight to long-term memory in SQLite, against this user.
    user_id, _ = ids_of(tool_context)
    try:
        profile = LongTermMemory.remember(user_id, profile_of(tool_context), field, value)
    except ValueError as exc:
        return error(str(exc))

    # Also update the copy in the agent's state, so the rest of this chat sees the change straight away. (The
    # memory block in the system prompt was written at the start of the chat, so the tools read the state.)
    tool_context.agent.state.set("profile", profile.model_dump())
    # Sending back what's still missing tells the model which clarifying question to ask next.
    return ok(saved={field: getattr(profile, field)},
              still_missing_for_planning=profile.missing_for_planning())

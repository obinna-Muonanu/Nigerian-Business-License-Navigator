"""
This is the tool Navi uses to pass a conversation to a real person.

When a user asks for a human, seems upset, or Navi can't help, this tool puts the case in a queue for staff, with a
short summary of the user's situation and what they need, and gives the user a ticket number. In this project it's a
demonstration, so no message is actually sent anywhere.
"""

from strands import ToolContext, tool

from agent.storage import sqlite_store
from agent.tools._common import ids_of, ok


@tool(context=True)
def handoff_to_human(reason: str, summary: str, tool_context: ToolContext) -> str:
    """Pass the conversation to a human adviser with a short summary. Use when the user asks for a person,
    is upset, or you cannot help after checking the tools.

    Args:
        reason: One of "user_asked", "user_upset", "no_information", "other".
        summary: Two sentences: the user's business and situation, and what they need help with.
    """
    # Put the case in the queue for a human, along with the summary the model wrote (the brief asks for the
    # chat to be passed on "with a short summary"). The length limits stop an oversized summary from
    # bloating the table.
    user_id, session_id = ids_of(tool_context)
    ticket = sqlite_store.add_handoff(user_id, session_id, reason[:40], summary[:1000])

    # Note the ticket number, so the server can show a "passed to a human" notice in the UI.
    tool_context.agent.state.set("handoff_ticket", ticket)
    return ok(ticket=ticket, message="A human adviser will continue this conversation. Tell the user the ticket number.")

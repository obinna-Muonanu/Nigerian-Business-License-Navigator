"""
It handles Navi's short-term memory: everything about the current chat.

It saves the conversation to the database after every message, so if the server restarts (or a different copy of the
server picks up the next message), the chat carries on exactly where it left off. It also sets up the summariser
that keeps long chats small (see conversation_manager.py), and fills in the chat's working state at the start.
"""

from strands import Agent
from strands.session.repository_session_manager import RepositorySessionManager

from agent.config import get_settings
from agent.memory.conversation_manager import RollingSummaryConversationManager
from agent.storage.chat_repository import build_chat_session_manager


def build_session_manager(session_id: str) -> RepositorySessionManager:
    """Save this chat's messages and working state in the database.

    Keeping them in the database, rather than only in the server's memory, means a crash or restart loses
    nothing. That includes a pending "shall I mark this as done?" question that's waiting for the user's answer.
    """
    return build_chat_session_manager(session_id)


def build_conversation_manager() -> RollingSummaryConversationManager:
    """Set up the rolling summary: the full chat until the context window reaches SUMMARY_TRIGGER_TOKENS
    (24,000), then the last KEEP_RECENT_TURNS turns (5) word for word plus a summary of everything older.

    Both numbers come from .env, so you can lower them to watch the summarising happen in a short test,
    without touching the code.
    """
    s = get_settings()
    return RollingSummaryConversationManager(
        trigger_tokens=s.summary_trigger_tokens,
        keep_recent_turns=s.keep_recent_turns,
    )


def seed_state(agent: Agent, user_id: str, session_id: str) -> None:
    """Fill in the agent's working state for a chat.

    The profile is deliberately not copied in here. The tools read each business's facts straight from the
    database whenever they need them, so there's only ever one copy of the truth and it can't go stale.
    """
    # Who and which chat this is. The tools and hooks read these to know whose records to touch.
    agent.state.set("user_id", user_id)
    agent.state.set("session_id", session_id)
    # Older chats kept a copy of the profile here. Remove it, so nothing can accidentally read an outdated copy.
    if agent.state.get("profile") is not None:
        agent.state.delete("profile")
    # Older chats kept the last language seen here. The reply language is now decided by the system prompt from
    # each new message, so nothing should read a stored language. Remove it.
    if agent.state.get("language") is not None:
        agent.state.delete("language")
    # Bookkeeping for the safety rules in agent/hooks. These are only set once per chat, so resuming a chat
    # never wipes out a confirmation the user is just about to give.
    for key, default in {"pending_action": None, "approved_action": None, "approved_tools": None, "turns": 0}.items():
        if agent.state.get(key) is None:
            agent.state.set(key, default)

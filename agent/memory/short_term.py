"""
It handles Navi's short-term memory: everything about the current chat.

It saves the conversation to disk after every message, so if the server restarts, the chat carries on exactly
where it left off. It also sets up the summariser that keeps long chats short (see conversation_manager.py), and
fills in what Navi knows about the user at the start of each chat.
"""

from strands import Agent
from strands.session.file_session_manager import FileSessionManager

from agent.config import get_settings
from agent.memory.conversation_manager import RollingSummaryConversationManager
from agent.memory.long_term import UserMemory


def build_session_manager(session_id: str) -> FileSessionManager:
    """Save this chat's messages and working state to disk.

    Using files, rather than keeping everything in memory, means a crash or restart loses nothing. That
    includes a pending "shall I mark this as done?" question that's waiting for the user's answer.
    """
    return FileSessionManager(session_id=session_id, storage_dir=str(get_settings().sessions_dir))


def build_conversation_manager() -> RollingSummaryConversationManager:
    """Set up the rolling summary: the full chat up to the turn limit, then the recent messages plus a summary.

    Both numbers come from .env. You can lower them (to 3 and 4, say) to watch the summarising happen in a
    short test, without touching the code.
    """
    s = get_settings()
    return RollingSummaryConversationManager(
        trigger_turns=s.summary_trigger_turns,
        keep_recent_messages=s.keep_recent_messages,
    )


def seed_state(agent: Agent, user_id: str, session_id: str, memory: UserMemory) -> None:
    """Fill in the agent's working state for a chat, using what long-term memory knows.

    A chat that's being resumed already has its state saved on disk. In that case we only refresh the
    parts long-term memory is in charge of, so a profile change made in another chat gets picked up.
    """
    # Who and which chat this is. The tools and hooks read these to know whose records to touch.
    agent.state.set("user_id", user_id)
    agent.state.set("session_id", session_id)
    # The profile always comes fresh from long-term memory, which is the one true source. remember_profile
    # saves straight to SQLite, so SQLite is never behind the chat.
    agent.state.set("profile", memory.profile.model_dump())
    # The language is just a record of the last language we saw, kept for the logs. It does not decide the
    # reply language: the input guard labels every message with its own language.
    if agent.state.get("language") is None:
        agent.state.set("language", memory.language or "english")
    # Bookkeeping for the safety rules in agent/hooks. These are only set once per chat, so resuming a chat
    # never wipes out a confirmation the user is just about to give.
    for key, default in {"pending_action": None, "approved_action": None, "approved_tools": None, "turns": 0}.items():
        if agent.state.get(key) is None:
            agent.state.set(key, default)

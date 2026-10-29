"""WHAT THIS FOLDER IS
This folder gives Navi its memory. There are two kinds:

    Short-term memory is the current chat: what's been said so far. Long chats are summarised so they stay fast
        and cheap.
    Long-term memory is what Navi remembers about a user between chats: their business details, the steps they've
        finished, and a short note about their last chat.

So when someone comes back and starts a new chat, Navi already knows them and doesn't ask the same questions
again. This file just makes the memory parts easy for the rest of the project to reach.
"""

# The main pieces are passed on from here, so other files can simply write
# `from agent.memory import LongTermMemory` without caring which file each piece lives in.
from agent.memory.conversation_manager import RollingSummaryConversationManager
from agent.memory.long_term import LongTermMemory, UserMemory
from agent.memory.short_term import build_conversation_manager, build_session_manager, seed_state
from agent.memory.summarizer import maybe_summarise

__all__ = [
    "LongTermMemory",
    "RollingSummaryConversationManager",
    "UserMemory",
    "build_conversation_manager",
    "build_session_manager",
    "seed_state",
    "maybe_summarise",
]

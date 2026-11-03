"""WHAT THIS FOLDER IS
This folder gives Navi its memory. There are four kinds, each with its own job:

    Working memory is what the AI sees on this reply: its rules, a short memory block, recent messages and
        fresh tool results. Old tool results are trimmed (see agent/hooks/compaction.py) to keep it small.
    Short-term memory is the current chat: everything said so far, saved in the database after every message.
        Long chats are summarised so they stay fast and cheap.
    Long-term memory is the confirmed facts about each of the user's businesses, plus their finished steps,
        saved with where each fact came from. It carries over from one chat to the next, for months if needed.
    Episodic memory is a short AI-written note about each past chat, so Navi can pick up the thread. It helps,
        but it's never treated as fact.

So when someone comes back and starts a new chat, Navi already knows them and doesn't ask the same questions
again. This file just makes the memory parts easy for the rest of the project to reach.
"""

# The main pieces are passed on from here, so other files can simply write
# `from agent.memory import LongTermMemory` without caring which file each piece lives in.
from agent.memory.conversation_manager import RollingSummaryConversationManager
from agent.memory.long_term import BusinessMemory, BusinessNotFound, LongTermMemory, UserMemory
from agent.memory.short_term import build_conversation_manager, build_session_manager, seed_state
from agent.memory.summarizer import maybe_summarise

__all__ = [
    "BusinessMemory",
    "BusinessNotFound",
    "LongTermMemory",
    "RollingSummaryConversationManager",
    "UserMemory",
    "build_conversation_manager",
    "build_session_manager",
    "seed_state",
    "maybe_summarise",
]

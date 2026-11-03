"""
It saves every chat's messages in the database, instead of in files on the server's disk.

Strands, the agent framework, already knows how to save a conversation after every message and reload it later. It
just needs to be told where to keep it. This file is that "where": it gives Strands the handful of save-and-load
actions it asks for (create a chat, save a message, list the messages, and so on), and carries each of them out as
a row in the chat_sessions, chat_agents and chat_messages tables.

WHY IT MATTERS
Files on Render's disk are wiped on every restart or redeploy, so users lost their chats. Files also can't be shared
between two copies of the server. A database fixes both: a chat survives restarts, and any copy of the server can
pick it up.
"""

import json
from datetime import datetime, timezone
from typing import Any

from strands.session.repository_session_manager import RepositorySessionManager
from strands.session.session_repository import SessionRepository
from strands.types.exceptions import SessionException
from strands.types.session import Session, SessionAgent, SessionMessage

from agent.storage.database import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatabaseChatRepository(SessionRepository):
    """Strands' "session repository" interface, carried out with SQL instead of files.

    Strands stores three kinds of record: the chat itself (a session), the agent taking part in it (with its
    working state, like a question waiting for the user's yes), and the numbered messages. Each record is turned
    into JSON with Strands' own to_dict(), so nothing about the format is ours to get wrong.
    """

    # The chat itself.

    def create_session(self, session: Session, **kwargs: Any) -> Session:
        if self.read_session(session.session_id):
            raise SessionException(f"Session {session.session_id} already exists")
        get_db().execute("INSERT INTO chat_sessions (session_id, data_json, created_at) VALUES (?, ?, ?)",
                         (session.session_id, json.dumps(session.to_dict()), _now()))
        return session

    def read_session(self, session_id: str, **kwargs: Any) -> Session | None:
        row = get_db().fetch_one("SELECT data_json FROM chat_sessions WHERE session_id = ?", (session_id,))
        return Session.from_dict(json.loads(row["data_json"])) if row else None

    # The agent's record within the chat, which holds its working state between messages.

    def create_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        get_db().execute("INSERT INTO chat_agents (session_id, agent_id, data_json, updated_at) VALUES (?, ?, ?, ?)",
                         (session_id, session_agent.agent_id, json.dumps(session_agent.to_dict()), _now()))

    def read_agent(self, session_id: str, agent_id: str, **kwargs: Any) -> SessionAgent | None:
        row = get_db().fetch_one("SELECT data_json FROM chat_agents WHERE session_id = ? AND agent_id = ?",
                                 (session_id, agent_id))
        return SessionAgent.from_dict(json.loads(row["data_json"])) if row else None

    def update_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        previous = self.read_agent(session_id, session_agent.agent_id)
        if previous is None:
            raise SessionException(f"Agent {session_agent.agent_id} in session {session_id} does not exist")
        # Keep the original creation time, exactly as Strands' own file storage does.
        session_agent.created_at = previous.created_at
        get_db().execute("UPDATE chat_agents SET data_json = ?, updated_at = ? WHERE session_id = ? AND agent_id = ?",
                         (json.dumps(session_agent.to_dict()), _now(), session_id, session_agent.agent_id))

    # The messages, numbered 0, 1, 2 ... in the order they were said.

    def create_message(self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any) -> None:
        # "Upsert" rather than a plain insert: if a retry saves the same message number twice, the second save
        # simply replaces the first instead of failing the user's turn.
        get_db().execute(
            """INSERT INTO chat_messages (session_id, agent_id, message_id, data_json, updated_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (session_id, agent_id, message_id) DO UPDATE SET data_json = excluded.data_json,
               updated_at = excluded.updated_at""",
            (session_id, agent_id, session_message.message_id, json.dumps(session_message.to_dict()), _now()),
        )

    def read_message(self, session_id: str, agent_id: str, message_id: int, **kwargs: Any) -> SessionMessage | None:
        row = get_db().fetch_one("SELECT data_json FROM chat_messages WHERE session_id = ? AND agent_id = ? "
                                 "AND message_id = ?", (session_id, agent_id, message_id))
        return SessionMessage.from_dict(json.loads(row["data_json"])) if row else None

    def update_message(self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any) -> None:
        # Strands only does this when a safety filter redacts a message after it was saved.
        previous = self.read_message(session_id, agent_id, session_message.message_id)
        if previous is None:
            raise SessionException(f"Message {session_message.message_id} does not exist")
        session_message.created_at = previous.created_at
        get_db().execute("UPDATE chat_messages SET data_json = ?, updated_at = ? WHERE session_id = ? AND agent_id = ? "
                         "AND message_id = ?", (json.dumps(session_message.to_dict()), _now(), session_id, agent_id,
                                                session_message.message_id))

    def list_messages(self, session_id: str, agent_id: str, limit: int | None = None, offset: int = 0,
                      **kwargs: Any) -> list[SessionMessage]:
        # The database does the skipping and counting, so a long chat that's been summarised doesn't load the
        # messages the summary already replaced.
        sql = ("SELECT data_json FROM chat_messages WHERE session_id = ? AND agent_id = ? AND message_id >= ? "
               "ORDER BY message_id")
        params: tuple = (session_id, agent_id, offset)
        if limit is not None:
            sql += " LIMIT ?"
            params += (limit,)
        return [SessionMessage.from_dict(json.loads(r["data_json"])) for r in get_db().fetch(sql, params)]


def build_chat_session_manager(session_id: str) -> RepositorySessionManager:
    """Give an agent a session manager that saves its chat in the database after every message."""
    return RepositorySessionManager(session_id=session_id, session_repository=DatabaseChatRepository())

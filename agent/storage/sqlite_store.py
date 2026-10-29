"""
It saves and reads everything Navi writes down, in a single small database file (SQLite).

That includes:
    each user's business details and a short summary of their last chat, so Navi remembers them next time;
    the steps each user has finished, their saved checklist and their reminders;
    chats handed over to a human adviser;
    the list of chats for the sidebar;
    a log of every action Navi takes, and how long and how much each reply cost, for checking and reporting.

WHY IT'S SEPARATE
User information changes all the time and belongs to individual people, while the knowledge graph is shared
reference material. Keeping them in different places means Navi never needs permission to change its knowledge.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from agent.config import get_settings

# The tables are created the first time the database is used. Because every statement says "IF NOT
# EXISTS", it's safe to run this on every start: tables that already exist, and their data, are left
# alone. A few columns hold small bits of JSON (the profile, the checklist steps, a tool's inputs) so we
# don't need extra tables for them. In the progress table, the user and the requirement together form
# the key, so each user has exactly one status per step.
SCHEMA = """
CREATE TABLE IF NOT EXISTS user_memory (
    user_id       TEXT PRIMARY KEY,
    profile_json  TEXT NOT NULL DEFAULT '{}',
    language      TEXT,
    summary       TEXT,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checklists (
    user_id       TEXT PRIMARY KEY,
    business_type TEXT,
    state         TEXT,
    steps_json    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS progress (
    user_id        TEXT NOT NULL,
    requirement_id TEXT NOT NULL,
    status         TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (user_id, requirement_id)
);
CREATE TABLE IF NOT EXISTS reminders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        TEXT NOT NULL,
    requirement_id TEXT NOT NULL,
    remind_on      TEXT NOT NULL,
    note           TEXT,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS handoffs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    reason      TEXT NOT NULL,
    summary     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    user_id        TEXT,
    session_id     TEXT,
    tool           TEXT NOT NULL,
    input_json     TEXT NOT NULL,
    status         TEXT NOT NULL,
    output_preview TEXT,
    output_full    TEXT,
    duration_ms    REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    mode        TEXT NOT NULL,
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, mode, updated_at);
CREATE TABLE IF NOT EXISTS turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    user_id         TEXT,
    session_id      TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cache_read      INTEGER,
    cache_write     INTEGER,
    latency_ms      REAL
);
"""

# This remembers whether the tables have been set up yet, so we only do it once per run and not on
# every single connection.
_initialised = False


def _now() -> str:
    """Give the current time in UTC, in a standard format that sorts correctly as text and means the same everywhere."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    """Open a connection, setting up the tables first if this is the first time this run."""
    global _initialised
    # If another thread is in the middle of writing, wait up to ten seconds for it to finish instead of
    # failing straight away.
    conn = sqlite3.connect(get_settings().sqlite_path, timeout=10)
    # This lets us read a column by its name, like row["summary"], instead of by its position, which is
    # easy to get wrong.
    conn.row_factory = sqlite3.Row
    if not _initialised:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
        _initialised = True
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Update a database that was created by an older version of the code.

    "CREATE TABLE IF NOT EXISTS" never changes a table that's already there, so a column added later
    (output_full) would be missing from an existing database. Adding it here keeps all the old data, and
    means nobody has to delete their database to get the new column.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tool_calls)")}
    if "output_full" not in columns:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN output_full TEXT")


def _execute(sql: str, params: tuple = ()) -> None:
    """Run one statement that changes data, and save it.

    The connection is always closed afterwards. The change is saved if everything works and undone if
    anything goes wrong, so a failed write never leaves things half-finished. The values always go in
    separately, through the ? placeholders, and are never pasted into the SQL text. That means nothing a
    user or the model writes can be used to sneak extra SQL in.
    """
    with closing(connect()) as conn, conn:
        conn.execute(sql, params)


def _fetch(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Run one query that reads data, and return all the rows."""
    with closing(connect()) as conn:
        return conn.execute(sql, params).fetchall()


# Long-term memory: what we remember about each user from one chat to the next.

def load_user_memory(user_id: str) -> dict[str, Any]:
    """Load what we remember about a user: their profile, language and last summary. A new user gets empty values."""
    rows = _fetch("SELECT profile_json, language, summary FROM user_memory WHERE user_id = ?", (user_id,))
    # A brand-new user has no row yet. We still return the same shape, so the code calling this doesn't
    # need a special case for new users.
    if not rows:
        return {"profile": {}, "language": None, "summary": None}
    row = rows[0]
    return {"profile": json.loads(row["profile_json"]), "language": row["language"], "summary": row["summary"]}


# The three functions below each use an "upsert": a single statement that creates the user's row if it
# doesn't exist yet, or otherwise updates just one column. Because each one only touches its own column,
# saving the language can never wipe out the profile, and the other way round.

def save_profile(user_id: str, profile: dict[str, Any]) -> None:
    """Save the user's whole profile. remember_profile calls this the moment the user shares a fact."""
    _execute(
        """INSERT INTO user_memory (user_id, profile_json, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET profile_json = excluded.profile_json, updated_at = excluded.updated_at""",
        (user_id, json.dumps(profile), _now()),
    )


def save_language(user_id: str, language: str) -> None:
    """Note the language the user last wrote in (English or Pidgin). It's logged, but it never decides the reply language."""
    _execute(
        """INSERT INTO user_memory (user_id, language, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET language = excluded.language, updated_at = excluded.updated_at""",
        (user_id, language, _now()),
    )


def save_summary(user_id: str, summary: str) -> None:
    """Save the latest short summary of the user's chat, which the fast model writes in the background."""
    _execute(
        """INSERT INTO user_memory (user_id, summary, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET summary = excluded.summary, updated_at = excluded.updated_at""",
        (user_id, summary, _now()),
    )


# The user's saved checklist, and the steps they've finished.

def save_checklist(user_id: str, business_type: str, state: str, steps: list[dict]) -> None:
    """Save a freshly planned checklist, replacing any older one.

    Each user has only one saved checklist, so saving again replaces it. An old plan that ignores new
    progress or a changed profile would only mislead them.
    """
    _execute(
        """INSERT INTO checklists (user_id, business_type, state, steps_json, updated_at) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET business_type = excluded.business_type, state = excluded.state,
           steps_json = excluded.steps_json, updated_at = excluded.updated_at""",
        (user_id, business_type, state, json.dumps(steps), _now()),
    )


def load_checklist(user_id: str) -> dict[str, Any] | None:
    """Load the saved checklist for the sidebar, or nothing if the user has never saved one."""
    rows = _fetch("SELECT business_type, state, steps_json, updated_at FROM checklists WHERE user_id = ?", (user_id,))
    if not rows:
        return None
    row = rows[0]
    return {"business_type": row["business_type"], "state": row["state"],
            "steps": json.loads(row["steps_json"]), "updated_at": row["updated_at"]}


def set_progress(user_id: str, requirement_id: str, status: str) -> None:
    """Mark a step as done, or reopen it by setting it back to 'pending'."""
    _execute(
        """INSERT INTO progress (user_id, requirement_id, status, updated_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, requirement_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at""",
        (user_id, requirement_id, status, _now()),
    )


def completed_steps(user_id: str) -> list[str]:
    """List the codes of the steps the user has finished, oldest first. The planner leaves these out of the checklist."""
    rows = _fetch("SELECT requirement_id FROM progress WHERE user_id = ? AND status = 'done' ORDER BY updated_at", (user_id,))
    return [r["requirement_id"] for r in rows]


# Reminders and hand-offs. These are pretend actions for the demo, so nothing is actually sent anywhere.
# Each one returns the new row's number, so the agent can tell the user their reminder or ticket number.

def add_reminder(user_id: str, requirement_id: str, remind_on: str, note: str) -> int:
    with closing(connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO reminders (user_id, requirement_id, remind_on, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, requirement_id, remind_on, note, _now()),
        )
        return int(cur.lastrowid)


def list_reminders(user_id: str) -> list[dict]:
    """List the user's reminders, soonest first, for the sidebar."""
    rows = _fetch("SELECT id, requirement_id, remind_on, note FROM reminders WHERE user_id = ? ORDER BY remind_on", (user_id,))
    return [dict(r) for r in rows]


def add_handoff(user_id: str, session_id: str, reason: str, summary: str) -> int:
    """Put a chat in the queue for a human. Saving the chat's ID lets staff open the whole conversation."""
    with closing(connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO handoffs (user_id, session_id, reason, summary, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, session_id, reason, summary, _now()),
        )
        return int(cur.lastrowid)


# Chats, for the sidebar list. Strands' files store the messages of each chat but not who it belongs to,
# so this table records each chat's owner. The index keeps "this user's chats, newest first" quick, no
# matter how many chats there are.

def touch_session(user_id: str, session_id: str, mode: str, title: str) -> None:
    """Note that a chat was just used: create it on its first message, or otherwise update when it was last active.

    The title is only set when the chat is created, from the first message, so later messages never rename it.
    """
    now = _now()
    _execute(
        """INSERT INTO sessions (session_id, user_id, mode, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at""",
        (session_id, user_id, mode, title, now, now),
    )


def list_sessions(user_id: str, mode: str, limit: int = 50) -> list[dict]:
    """List a user's chats for one mode, the most recently used first, just like a chat app's sidebar."""
    rows = _fetch(
        "SELECT session_id, title, created_at, updated_at FROM sessions "
        "WHERE user_id = ? AND mode = ? ORDER BY updated_at DESC LIMIT ?",
        (user_id, mode, limit),
    )
    return [dict(r) for r in rows]


def session_owner(session_id: str) -> str | None:
    """Find out who owns a chat, or nothing if we don't know. This stops one user opening someone else's chat."""
    rows = _fetch("SELECT user_id FROM sessions WHERE session_id = ?", (session_id,))
    return rows[0]["user_id"] if rows else None


# Observability: a record of what the agent actually did, and what it cost.

def log_tool_call(user_id: str | None, session_id: str | None, tool: str, tool_input: dict,
                  status: str, output: str, duration_ms: float | None) -> None:
    """Write one audit row for a tool call, as the brief asks: keep the tool name, inputs and result.

    The result is stored twice. The full version is the complete audit record, and a short preview of
    the first 500 characters makes it quick to skim in queries and reports. If the model put an unusual
    value in the inputs, it's simply turned into text, so saving never fails.
    """
    _execute(
        """INSERT INTO tool_calls (ts, user_id, session_id, tool, input_json, status, output_preview, output_full, duration_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_now(), user_id, session_id, tool, json.dumps(tool_input, default=str), status, output[:500], output, duration_ms),
    )


def log_turn(user_id: str, session_id: str, usage: dict, latency_ms: float) -> None:
    """Record how many tokens a turn used, how many came from the cache, and how long it took, for the cost report."""
    _execute(
        """INSERT INTO turns (ts, user_id, session_id, input_tokens, output_tokens, cache_read, cache_write, latency_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (_now(), user_id, session_id, usage.get("inputTokens", 0), usage.get("outputTokens", 0),
         usage.get("cacheReadInputTokens", 0), usage.get("cacheWriteInputTokens", 0), latency_ms),
    )


def tool_calls_for_session(session_id: str) -> list[dict]:
    """List the tool calls made in one chat. The evaluation uses this to check which tools really ran, and whether they worked."""
    rows = _fetch("SELECT tool, input_json, status, output_preview, output_full FROM tool_calls "
                  "WHERE session_id = ? ORDER BY id", (session_id,))
    return [dict(r) for r in rows]

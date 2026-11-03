"""
It saves and reads everything Navi writes down. Each function here is one plain job, like "save this fact" or "list
this user's businesses", and the SQL for it.

What it keeps:
    users, and each user's businesses (one user can run several);
    the confirmed facts about each business, with where each fact came from and when, plus a history of changes;
    each business's saved checklist, finished steps and reminders;
    a short note about each past chat (episodic memory);
    the list of chats for the sidebar;
    chats handed over to a human adviser;
    a log of every action Navi takes, and how long and how much each reply cost.

It also covers the user's data rights: exporting everything we hold about someone, deleting it on request, and
automatically deleting users who haven't visited for a long time.

The database itself (SQLite on your computer, Postgres in production) is handled by database.py, so nothing here
needs to know which one is in use.

WHY IT'S SEPARATE FROM THE KNOWLEDGE GRAPH
User information changes all the time and belongs to individual people, while the knowledge graph is shared
reference material. Keeping them apart means Navi never needs permission to change its knowledge.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from agent.storage.database import get_db


def _now() -> str:
    """Give the current time in UTC, in a standard text format that sorts correctly and means the same everywhere.

    It goes down to the microsecond, so two things saved within the same second still sort in the right order
    (for example, which chat note is the newest).
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# Users. A row is created the first time someone chats, and last_seen_at is refreshed on every visit. That date
# is what the retention rule at the bottom of this file uses to decide whose data has expired.

def touch_user(user_id: str) -> None:
    """Record that a user is active right now, creating their row if this is their first visit."""
    now = _now()
    get_db().execute(
        """INSERT INTO users (user_id, created_at, last_seen_at) VALUES (?, ?, ?)
           ON CONFLICT (user_id) DO UPDATE SET last_seen_at = excluded.last_seen_at""",
        (user_id, now, now),
    )


def load_user(user_id: str) -> dict[str, Any] | None:
    """Load a user's row (when they joined and when we last saw them), or nothing for a brand-new user."""
    return get_db().fetch_one("SELECT user_id, language, created_at, last_seen_at FROM users WHERE user_id = ?",
                              (user_id,))


# Businesses. Each one has a short label the user and Navi can refer to it by, like "zobo business".

def list_businesses(user_id: str) -> list[dict[str, Any]]:
    """List a user's businesses, oldest first, so "Business 1" always comes before "Business 2".

    Inactive businesses are included; each row says whether it's "active" or "inactive" and when it was last used.
    """
    return get_db().fetch("SELECT business_id, label, status, last_used_at, created_at, updated_at FROM businesses "
                          "WHERE user_id = ? ORDER BY created_at, business_id", (user_id,))


def create_business(user_id: str, label: str) -> str:
    """Add a new business for a user and return its ID. The ID is random, so it can't be guessed."""
    business_id = f"b-{uuid.uuid4().hex[:12]}"
    now = _now()
    get_db().execute("INSERT INTO businesses (business_id, user_id, label, status, last_used_at, created_at, "
                     "updated_at) VALUES (?, ?, ?, 'active', ?, ?, ?)", (business_id, user_id, label, now, now, now))
    return business_id


# Writing "last used" on every single tool call would mean a database write for every lookup, so it's only
# refreshed if it's more than this old. For a rule that works in months, an hour's precision is plenty.
TOUCH_EVERY = timedelta(hours=1)


def touch_business(business_id: str) -> None:
    """Record that Navi just worked on this business, and make it active again if it had been set aside."""
    now = datetime.now(timezone.utc)
    stale = (now - TOUCH_EVERY).isoformat(timespec="microseconds")
    get_db().execute(
        "UPDATE businesses SET last_used_at = ?, status = 'active' "
        "WHERE business_id = ? AND (status <> 'active' OR last_used_at IS NULL OR last_used_at < ?)",
        (now.isoformat(timespec="microseconds"), business_id, stale),
    )


def _delete_business_rows(tx: Any, business_id: str) -> None:
    """Delete one business and everything recorded about it, inside an open transaction."""
    for table in ("profile_facts", "fact_history", "checklists", "progress", "reminders", "businesses"):
        tx.execute(f"DELETE FROM {table} WHERE business_id = ?", (business_id,))


def delete_business(user_id: str, business_id: str) -> bool:
    """Delete one business and everything recorded about it. Returns False if this user has no such business."""
    with get_db().transaction() as tx:
        # Checking the owner first means one user can never delete another user's business by guessing its ID.
        if not tx.fetch_one("SELECT 1 AS found FROM businesses WHERE business_id = ? AND user_id = ?",
                            (business_id, user_id)):
            return False
        _delete_business_rows(tx, business_id)
    return True


def retire_unused_businesses(inactive_days: int, delete_days: int) -> dict[str, int]:
    """Set aside businesses nobody has used for a while, and delete ones unused for much longer.

    The two stages:
        not used for `inactive_days` (6 months by default): marked "inactive". It's kept, but Navi only sees its
            name, so it stops costing tokens and stops getting in the way. Using it again makes it active.
        not used for `delete_days` (18 months by default): deleted, with all its facts, progress and checklist.

    A business with a reminder still in the future is left alone at both stages: the user has said they'll be back.
    The deletion period is deliberately longer than a year, because licences renew yearly and a real business can
    be quiet for eleven months and then come back for its renewal. Returns how many were set aside and deleted.
    """
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    result = {"made_inactive": 0, "deleted": 0}
    with get_db().transaction() as tx:
        # Businesses with an upcoming reminder are protected.
        protected = {r["business_id"] for r in tx.fetch(
            "SELECT DISTINCT business_id FROM reminders WHERE business_id IS NOT NULL AND remind_on >= ?", (today,))}
        if delete_days > 0:
            cutoff = (now - timedelta(days=delete_days)).isoformat(timespec="microseconds")
            for row in tx.fetch("SELECT business_id FROM businesses WHERE last_used_at < ?", (cutoff,)):
                if row["business_id"] not in protected:
                    _delete_business_rows(tx, row["business_id"])
                    result["deleted"] += 1
        if inactive_days > 0:
            cutoff = (now - timedelta(days=inactive_days)).isoformat(timespec="microseconds")
            for row in tx.fetch("SELECT business_id FROM businesses WHERE status = 'active' AND last_used_at < ?",
                                (cutoff,)):
                if row["business_id"] not in protected:
                    tx.execute("UPDATE businesses SET status = 'inactive' WHERE business_id = ?", (row["business_id"],))
                    result["made_inactive"] += 1
    return result


# Facts about a business. Each fact is stored on its own row with its source ("user_stated", "progress_update",
# "migrated", "seeded") and the chat it came from, so we can always answer "where did Navi get that idea?".
# Every change is also copied into fact_history, so an overwritten value is never lost without trace.

def load_facts(business_id: str) -> dict[str, dict[str, Any]]:
    """Load a business's facts as {field: {"value": ..., "source": ..., "updated_at": ...}}."""
    rows = get_db().fetch("SELECT field, value_json, source, session_id, updated_at FROM profile_facts "
                          "WHERE business_id = ?", (business_id,))
    return {r["field"]: {"value": json.loads(r["value_json"]), "source": r["source"],
                         "session_id": r["session_id"], "updated_at": r["updated_at"]} for r in rows}


def save_fact(business_id: str, field: str, value: Any, source: str, session_id: str | None) -> None:
    """Save one fact and record the change in the history, both in one transaction so they can't disagree."""
    now = _now()
    with get_db().transaction() as tx:
        old = tx.fetch_one("SELECT value_json FROM profile_facts WHERE business_id = ? AND field = ?",
                           (business_id, field))
        new_json = json.dumps(value)
        # Saying the same thing twice isn't a change, so there's nothing to write.
        if old and old["value_json"] == new_json:
            return
        tx.execute(
            """INSERT INTO profile_facts (business_id, field, value_json, source, session_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (business_id, field) DO UPDATE SET value_json = excluded.value_json,
               source = excluded.source, session_id = excluded.session_id, updated_at = excluded.updated_at""",
            (business_id, field, new_json, source, session_id, now),
        )
        tx.execute("INSERT INTO fact_history (business_id, field, old_value_json, new_value_json, source, session_id, "
                   "changed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (business_id, field, old["value_json"] if old else None, new_json, source, session_id, now))
        tx.execute("UPDATE businesses SET updated_at = ? WHERE business_id = ?", (now, business_id))


# Each business's saved checklist and finished steps.

def save_checklist(user_id: str, business_id: str, business_type: str, state: str, steps: list[dict]) -> None:
    """Save a freshly planned checklist for one business, replacing its older one.

    An old plan that ignores new progress or a changed profile would only mislead, so each business keeps one.
    """
    get_db().execute(
        """INSERT INTO checklists (business_id, user_id, business_type, state, steps_json, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (business_id) DO UPDATE SET business_type = excluded.business_type, state = excluded.state,
           steps_json = excluded.steps_json, updated_at = excluded.updated_at""",
        (business_id, user_id, business_type, state, json.dumps(steps), _now()),
    )


def load_checklists(user_id: str) -> list[dict[str, Any]]:
    """Load every saved checklist a user has, one per business, with the business's label, for the sidebar."""
    rows = get_db().fetch(
        """SELECT c.business_id, b.label, c.business_type, c.state, c.steps_json, c.updated_at
           FROM checklists c JOIN businesses b ON b.business_id = c.business_id
           WHERE c.user_id = ? ORDER BY b.created_at""", (user_id,))
    return [{**{k: v for k, v in r.items() if k != "steps_json"}, "steps": json.loads(r["steps_json"])} for r in rows]


def set_progress(business_id: str, requirement_id: str, status: str, source: str, session_id: str | None) -> None:
    """Mark a step as done for one business, or reopen it by setting it back to 'pending'."""
    get_db().execute(
        """INSERT INTO progress (business_id, requirement_id, status, source, session_id, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (business_id, requirement_id) DO UPDATE SET status = excluded.status,
           source = excluded.source, session_id = excluded.session_id, updated_at = excluded.updated_at""",
        (business_id, requirement_id, status, source, session_id, _now()),
    )


def completed_steps(business_id: str) -> list[str]:
    """List the codes of the steps a business has finished, oldest first. The planner leaves these out."""
    rows = get_db().fetch("SELECT requirement_id FROM progress WHERE business_id = ? AND status = 'done' "
                          "ORDER BY updated_at", (business_id,))
    return [r["requirement_id"] for r in rows]


# Reminders and hand-offs. These are pretend actions for the demo, so nothing is actually sent anywhere. Each
# one returns the new row's number, so Navi can tell the user their reminder or ticket number.

def add_reminder(user_id: str, business_id: str, requirement_id: str, remind_on: str, note: str) -> int:
    row = get_db().fetch_one(
        "INSERT INTO reminders (user_id, business_id, requirement_id, remind_on, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (user_id, business_id, requirement_id, remind_on, note, _now()),
    )
    return int(row["id"])


def list_reminders(user_id: str) -> list[dict]:
    """List a user's reminders, soonest first, with the label of the business each one belongs to."""
    return get_db().fetch(
        """SELECT r.id, r.business_id, b.label, r.requirement_id, r.remind_on, r.note
           FROM reminders r LEFT JOIN businesses b ON b.business_id = r.business_id
           WHERE r.user_id = ? ORDER BY r.remind_on""", (user_id,))


def add_handoff(user_id: str, session_id: str, reason: str, summary: str) -> int:
    """Put a chat in the queue for a human. Saving the chat's ID lets staff open the whole conversation."""
    row = get_db().fetch_one(
        "INSERT INTO handoffs (user_id, session_id, reason, summary, created_at) VALUES (?, ?, ?, ?, ?) RETURNING id",
        (user_id, session_id, reason, summary, _now()),
    )
    return int(row["id"])


# Episodic memory: one short note per chat, written by the fast model. They're kept per chat (not one per user)
# so a new chat can never overwrite the note from an earlier one, and Navi can recall the last few.

def save_episode(user_id: str, session_id: str, summary: str) -> None:
    """Save or refresh the note for one chat."""
    get_db().execute(
        """INSERT INTO episodes (session_id, user_id, summary, updated_at) VALUES (?, ?, ?, ?)
           ON CONFLICT (session_id) DO UPDATE SET summary = excluded.summary, updated_at = excluded.updated_at""",
        (session_id, user_id, summary, _now()),
    )


def recent_episodes(user_id: str, limit: int = 3) -> list[dict[str, Any]]:
    """Get the notes from a user's most recent chats, newest first."""
    return get_db().fetch("SELECT session_id, summary, updated_at FROM episodes WHERE user_id = ? "
                          "ORDER BY updated_at DESC LIMIT ?", (user_id, limit))


# Chats, for the sidebar list. This table records who owns each chat. The index keeps "this user's chats,
# newest first" quick, no matter how many chats there are.

def touch_session(user_id: str, session_id: str, mode: str, title: str) -> None:
    """Note that a chat was just used: create it on its first message, or otherwise update when it was last active.

    The title is only set when the chat is created, from the first message, so later messages never rename it.
    """
    now = _now()
    get_db().execute(
        """INSERT INTO sessions (session_id, user_id, mode, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (session_id) DO UPDATE SET updated_at = excluded.updated_at""",
        (session_id, user_id, mode, title, now, now),
    )


def list_sessions(user_id: str, mode: str, limit: int = 50) -> list[dict]:
    """List a user's chats for one mode, the most recently used first, just like a chat app's sidebar."""
    return get_db().fetch(
        "SELECT session_id, title, created_at, updated_at FROM sessions "
        "WHERE user_id = ? AND mode = ? ORDER BY updated_at DESC LIMIT ?",
        (user_id, mode, limit),
    )


def session_owner(session_id: str) -> str | None:
    """Find out who owns a chat, or nothing if we don't know. This stops one user opening someone else's chat."""
    row = get_db().fetch_one("SELECT user_id FROM sessions WHERE session_id = ?", (session_id,))
    return row["user_id"] if row else None


# Observability: a record of what the agent actually did, and what it cost.

def log_tool_call(user_id: str | None, session_id: str | None, tool: str, tool_input: dict,
                  status: str, output: str, duration_ms: float | None) -> None:
    """Write one audit row for a tool call: the tool name, its inputs and its result.

    The result is stored twice. The full version is the complete audit record, and a short preview of the
    first 500 characters makes it quick to skim. An unusual input value is simply turned into text, so saving
    never fails.
    """
    get_db().execute(
        """INSERT INTO tool_calls (ts, user_id, session_id, tool, input_json, status, output_preview, output_full, duration_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_now(), user_id, session_id, tool, json.dumps(tool_input, default=str), status, output[:500], output, duration_ms),
    )


def log_turn(user_id: str, session_id: str, usage: dict, latency_ms: float) -> None:
    """Record how many tokens a turn used, how many came from the cache, and how long it took, for the cost report."""
    get_db().execute(
        """INSERT INTO turns (ts, user_id, session_id, input_tokens, output_tokens, cache_read, cache_write, latency_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (_now(), user_id, session_id, usage.get("inputTokens", 0), usage.get("outputTokens", 0),
         usage.get("cacheReadInputTokens", 0), usage.get("cacheWriteInputTokens", 0), latency_ms),
    )


def tool_calls_for_session(session_id: str) -> list[dict]:
    """List the tool calls made in one chat. The evaluation uses this to check which tools really ran."""
    return get_db().fetch("SELECT tool, input_json, status, output_preview, output_full FROM tool_calls "
                          "WHERE session_id = ? ORDER BY id", (session_id,))


# The user's data rights under the NDPA: see everything we hold, take it away, or have it deleted.

def export_user_data(user_id: str) -> dict[str, Any]:
    """Gather everything stored about one user into a single dictionary they can download."""
    db = get_db()
    businesses = []
    for b in list_businesses(user_id):
        history = db.fetch("SELECT field, old_value_json, new_value_json, source, changed_at FROM fact_history "
                           "WHERE business_id = ? ORDER BY id", (b["business_id"],))
        businesses.append({**b, "facts": load_facts(b["business_id"]),
                           "fact_history": history, "completed_steps": completed_steps(b["business_id"])})
    sessions = db.fetch("SELECT session_id, mode, title, created_at, updated_at FROM sessions WHERE user_id = ?",
                        (user_id,))
    return {
        "user": load_user(user_id),
        "businesses": businesses,
        "checklists": load_checklists(user_id),
        "reminders": list_reminders(user_id),
        "episodes": db.fetch("SELECT session_id, summary, updated_at FROM episodes WHERE user_id = ?", (user_id,)),
        "chats": sessions,
        "handoffs": db.fetch("SELECT id, session_id, reason, summary, status, created_at FROM handoffs "
                             "WHERE user_id = ?", (user_id,)),
    }


def delete_user_data(user_id: str) -> None:
    """Delete everything stored about one user: their businesses, facts, chats, notes, reminders and logs.

    It all happens in one transaction, so a failure part-way through can never leave half a user behind.
    """
    with get_db().transaction() as tx:
        business_ids = [r["business_id"] for r in tx.fetch("SELECT business_id FROM businesses WHERE user_id = ?",
                                                             (user_id,))]
        for business_id in business_ids:
            for table in ("profile_facts", "fact_history", "progress"):
                tx.execute(f"DELETE FROM {table} WHERE business_id = ?", (business_id,))
        session_ids = [r["session_id"] for r in tx.fetch("SELECT session_id FROM sessions WHERE user_id = ?",
                                                           (user_id,))]
        for session_id in session_ids:
            for table in ("chat_messages", "chat_agents", "chat_sessions"):
                tx.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
        for table in ("businesses", "checklists", "reminders", "episodes", "sessions", "handoffs",
                      "tool_calls", "turns", "users"):
            tx.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))


def purge_inactive_users(retention_days: int) -> int:
    """Delete every user who hasn't visited for longer than the retention period. Returns how many were deleted."""
    if retention_days <= 0:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
    expired = [r["user_id"] for r in get_db().fetch("SELECT user_id FROM users WHERE last_seen_at < ?", (cutoff,))]
    for user_id in expired:
        delete_user_data(user_id)
    return len(expired)

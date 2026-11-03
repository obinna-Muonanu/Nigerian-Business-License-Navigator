"""
It creates the database tables, and upgrades them safely when a new version of Navi needs them to change.

Each change to the tables is written down as a numbered "migration". The database remembers the highest number it has
already applied (in a small table called schema_version). Every time the app starts, it runs only the migrations
the database hasn't had yet, in order, each one as a single all-or-nothing step.

    Migration 1 creates the original tables (one profile per user).
    Migration 2 moves to the production memory design: several businesses per user, a source and date on every
        remembered fact, a history of changed facts, per-chat summaries, and chat history stored in the database
        instead of in files. Any data in the old tables is copied across before they are replaced.
    Migration 3 adds a "last used" date and an active/inactive status to each business, so businesses the user
        has stopped using can be set aside and, much later, deleted.

WHY IT MATTERS
A live database full of real users can't be deleted and recreated whenever the code changes. Numbered migrations let
the same code start a brand-new database or upgrade an existing one, on SQLite or Postgres, without losing anything.
"""

import json
import uuid
from datetime import datetime, timezone

from agent.storage.database import Database, Transaction

# A fixed number that identifies "Navi's migrations" to Postgres. When two copies of the app start at the same
# moment, the first one takes this lock and the second waits, so the same migration is never applied twice.
MIGRATION_LOCK_ID = 7_210_431


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _auto_id(tx: Transaction) -> str:
    """The way each database spells "a number that counts up by itself", used for log and reminder IDs."""
    return "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY" if tx.is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"


# Migration 1: the original tables, exactly as earlier versions created them. Running it on a database that
# already has them changes nothing, because every statement says "IF NOT EXISTS".
def _m1_original_tables(tx: Transaction) -> None:
    auto_id = _auto_id(tx)
    tx.script(f"""
    CREATE TABLE IF NOT EXISTS user_memory (
        user_id TEXT PRIMARY KEY, profile_json TEXT NOT NULL DEFAULT '{{}}', language TEXT, summary TEXT,
        updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS checklists (
        user_id TEXT PRIMARY KEY, business_type TEXT, state TEXT, steps_json TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS progress (
        user_id TEXT NOT NULL, requirement_id TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, requirement_id));
    CREATE TABLE IF NOT EXISTS reminders (
        id {auto_id}, user_id TEXT NOT NULL, requirement_id TEXT NOT NULL, remind_on TEXT NOT NULL, note TEXT,
        created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS handoffs (
        id {auto_id}, user_id TEXT NOT NULL, session_id TEXT NOT NULL, reason TEXT NOT NULL, summary TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS tool_calls (
        id {auto_id}, ts TEXT NOT NULL, user_id TEXT, session_id TEXT, tool TEXT NOT NULL, input_json TEXT NOT NULL,
        status TEXT NOT NULL, output_preview TEXT, output_full TEXT, duration_ms REAL);
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mode TEXT NOT NULL, title TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, mode, updated_at);
    CREATE TABLE IF NOT EXISTS turns (
        id {auto_id}, ts TEXT NOT NULL, user_id TEXT, session_id TEXT, input_tokens INTEGER, output_tokens INTEGER,
        cache_read INTEGER, cache_write INTEGER, latency_ms REAL)
    """)
    # Very old local databases were created before the full tool output was kept, so add that column if needed.
    if "output_full" not in tx.columns("tool_calls"):
        tx.execute("ALTER TABLE tool_calls ADD COLUMN output_full TEXT")


# Migration 2: the production memory design.
def _m2_production_memory(tx: Transaction) -> None:
    # Step 1: read whatever is in the old one-business-per-user tables, so it can be carried across.
    old_memory = tx.fetch("SELECT * FROM user_memory")
    old_checklists = {r["user_id"]: r for r in tx.fetch("SELECT * FROM checklists")}
    old_progress = tx.fetch("SELECT * FROM progress")

    # Step 2: drop the old tables. Their data is safely held in the variables above, and this whole migration
    # runs as one transaction, so if anything below fails the old tables come back untouched.
    tx.script("DROP TABLE user_memory; DROP TABLE checklists; DROP TABLE progress")

    # Step 3: create the new tables.
    auto_id = _auto_id(tx)
    tx.script(f"""
    CREATE TABLE users (
        user_id      TEXT PRIMARY KEY,
        language     TEXT,
        created_at   TEXT NOT NULL,
        last_seen_at TEXT NOT NULL);

    CREATE TABLE businesses (
        business_id TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        label       TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL);
    CREATE INDEX idx_businesses_user ON businesses (user_id);

    CREATE TABLE profile_facts (
        business_id TEXT NOT NULL,
        field       TEXT NOT NULL,
        value_json  TEXT NOT NULL,
        source      TEXT NOT NULL,
        session_id  TEXT,
        updated_at  TEXT NOT NULL,
        PRIMARY KEY (business_id, field));

    CREATE TABLE fact_history (
        id             {auto_id},
        business_id    TEXT NOT NULL,
        field          TEXT NOT NULL,
        old_value_json TEXT,
        new_value_json TEXT NOT NULL,
        source         TEXT NOT NULL,
        session_id     TEXT,
        changed_at     TEXT NOT NULL);
    CREATE INDEX idx_fact_history_business ON fact_history (business_id);

    CREATE TABLE checklists (
        business_id   TEXT PRIMARY KEY,
        user_id       TEXT NOT NULL,
        business_type TEXT,
        state         TEXT,
        steps_json    TEXT NOT NULL,
        updated_at    TEXT NOT NULL);

    CREATE TABLE progress (
        business_id    TEXT NOT NULL,
        requirement_id TEXT NOT NULL,
        status         TEXT NOT NULL,
        source         TEXT NOT NULL,
        session_id     TEXT,
        updated_at     TEXT NOT NULL,
        PRIMARY KEY (business_id, requirement_id));

    CREATE TABLE episodes (
        session_id TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL,
        summary    TEXT NOT NULL,
        updated_at TEXT NOT NULL);
    CREATE INDEX idx_episodes_user ON episodes (user_id, updated_at);

    CREATE TABLE chat_sessions (
        session_id TEXT PRIMARY KEY,
        data_json  TEXT NOT NULL,
        created_at TEXT NOT NULL);

    CREATE TABLE chat_agents (
        session_id TEXT NOT NULL,
        agent_id   TEXT NOT NULL,
        data_json  TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (session_id, agent_id));

    CREATE TABLE chat_messages (
        session_id TEXT NOT NULL,
        agent_id   TEXT NOT NULL,
        message_id INTEGER NOT NULL,
        data_json  TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (session_id, agent_id, message_id));

    ALTER TABLE reminders ADD COLUMN business_id TEXT
    """)

    # Step 4: copy the old data into the new shape. Each old user becomes a user with one business, called
    # "Business 1", holding their old profile, checklist and progress. Their old summary becomes an episode.
    now = _now()
    memory_rows = {r["user_id"]: r for r in old_memory}
    user_ids = set(memory_rows) | set(old_checklists) | {r["user_id"] for r in old_progress}
    for user_id in user_ids:
        row = memory_rows.get(user_id, {})
        seen = row.get("updated_at") or now
        tx.execute("INSERT INTO users (user_id, language, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
                   (user_id, row.get("language"), seen, seen))
        if row.get("summary"):
            tx.execute("INSERT INTO episodes (session_id, user_id, summary, updated_at) VALUES (?, ?, ?, ?)",
                       (f"legacy-{user_id}", user_id, row["summary"], seen))

        # Only create a business if there's something to put in it. A user who only ever said hello has none.
        profile = json.loads(row.get("profile_json") or "{}")
        progress = [p for p in old_progress if p["user_id"] == user_id]
        if not (profile or progress or user_id in old_checklists):
            continue
        business_id = f"b-{uuid.uuid4().hex[:12]}"
        tx.execute("INSERT INTO businesses (business_id, user_id, label, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                   (business_id, user_id, "Business 1", seen, seen))
        for field, value in profile.items():
            tx.execute("INSERT INTO profile_facts (business_id, field, value_json, source, updated_at) "
                       "VALUES (?, ?, ?, 'migrated', ?)", (business_id, field, json.dumps(value), seen))
        if user_id in old_checklists:
            c = old_checklists[user_id]
            tx.execute("INSERT INTO checklists (business_id, user_id, business_type, state, steps_json, updated_at) "
                       "VALUES (?, ?, ?, ?, ?, ?)",
                       (business_id, user_id, c["business_type"], c["state"], c["steps_json"], c["updated_at"]))
        for p in progress:
            tx.execute("INSERT INTO progress (business_id, requirement_id, status, source, updated_at) "
                       "VALUES (?, ?, ?, 'migrated', ?)", (business_id, p["requirement_id"], p["status"], p["updated_at"]))
        tx.execute("UPDATE reminders SET business_id = ? WHERE user_id = ?", (business_id, user_id))


# Migration 3: retiring businesses the user no longer uses.
def _m3_business_activity(tx: Transaction) -> None:
    # last_used_at is when Navi last worked on the business (any tool, not only a change of facts). status is
    # "active" or "inactive"; inactive businesses are kept but shown to Navi as a single line. See
    # retire_unused_businesses in store.py for the rules.
    tx.execute("ALTER TABLE businesses ADD COLUMN last_used_at TEXT")
    tx.execute("ALTER TABLE businesses ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    # Existing businesses start from the last time their facts changed, the best date we have for them.
    tx.execute("UPDATE businesses SET last_used_at = updated_at WHERE last_used_at IS NULL")


# The full list, in order. To change the tables in future, add a new function and a new line at the end. Never
# edit a migration that has already been released, because databases that already ran it won't run it again.
MIGRATIONS = [
    (1, "original tables", _m1_original_tables),
    (2, "production memory: businesses, fact sources, episodes, chat history", _m2_production_memory),
    (3, "business activity: last used date and inactive status", _m3_business_activity),
]


def run_migrations(db: Database) -> None:
    """Apply every migration this database hasn't had yet, in order, each as one all-or-nothing transaction."""
    with db.transaction() as tx:
        tx.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                   "applied_at TEXT NOT NULL)")

    for version, name, migrate in MIGRATIONS:
        with db.transaction() as tx:
            if tx.is_postgres:
                # Hold the lock until this transaction ends, so a second copy of the app waits its turn.
                tx.fetch("SELECT pg_advisory_xact_lock(?) AS locked", (MIGRATION_LOCK_ID,))
            # Check again inside the transaction: another copy of the app may have just applied it.
            if tx.fetch_one("SELECT 1 AS done FROM schema_version WHERE version = ?", (version,)):
                continue
            migrate(tx)
            tx.execute("INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                       (version, name, _now()))

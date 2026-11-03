"""
It is the one doorway to the database where Navi writes things down. It works with two kinds of database and hides
the difference from the rest of the project.

    On your own computer, with DATABASE_URL left empty, it uses SQLite: a single file, nothing to install.
    In production, with DATABASE_URL set to a Postgres address, it uses Postgres: a proper database server that
        survives restarts and can be shared by several copies of the app at once.

Every other file just calls fetch(), execute() or transaction() and writes ordinary SQL with "?" where the values go.
This file translates that into whatever the chosen database expects.

WHY IT MATTERS
Render's disk is wiped on every restart, so a SQLite file there loses every user's memory. Being able to switch to
Postgres with one setting, without touching any other code, is what makes the memory safe for production.
"""

import atexit
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import closing, contextmanager
from typing import Any

from agent.config import get_settings


class Transaction:
    """A group of statements that either all succeed or all get undone.

    It wraps one open connection and offers the same three small methods whichever database is underneath:
    execute (change data), fetch (read rows as dictionaries) and script (run several schema statements).
    """

    def __init__(self, conn: Any, is_postgres: bool):
        self._conn = conn
        self.is_postgres = is_postgres

    def _sql(self, sql: str) -> str:
        # Our SQL uses "?" for each value, which is what SQLite expects. Postgres's driver expects "%s", so we
        # swap them. Values always travel separately from the SQL text, which is what stops anything a user
        # types from being run as SQL. (Our SQL never contains a literal "?" or "%" of its own.)
        return sql.replace("?", "%s") if self.is_postgres else sql

    def execute(self, sql: str, params: tuple = ()) -> None:
        """Run one statement that changes data."""
        self._conn.execute(self._sql(sql), params)

    def fetch(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Run one query and return every row as a dictionary, like {"user_id": "u1", "language": "pidgin"}."""
        cursor = self._conn.execute(self._sql(sql), params)
        return [dict(row) for row in cursor.fetchall()]

    def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        """Run one query and return its first row, or nothing if there isn't one."""
        rows = self.fetch(sql, params)
        return rows[0] if rows else None

    def script(self, sql: str) -> None:
        """Run several schema statements, separated by semicolons, one after another inside this transaction.

        We split them ourselves rather than use SQLite's executescript, because executescript quietly commits
        whatever came before it, which would break the "all or nothing" promise of a migration.
        """
        for statement in sql.split(";"):
            if statement.strip():
                self._conn.execute(statement)

    def table_exists(self, table: str) -> bool:
        """Check whether a table exists. Each database keeps its list of tables in a different place."""
        if self.is_postgres:
            row = self.fetch_one("SELECT 1 AS found FROM information_schema.tables WHERE table_name = ?", (table,))
        else:
            row = self.fetch_one("SELECT 1 AS found FROM sqlite_master WHERE type = 'table' AND name = ?", (table,))
        return row is not None

    def columns(self, table: str) -> set[str]:
        """List the column names of a table, so a migration can tell whether a column still needs adding."""
        if self.is_postgres:
            rows = self.fetch("SELECT column_name AS name FROM information_schema.columns WHERE table_name = ?", (table,))
        else:
            rows = self.fetch(f"PRAGMA table_info({table})")
        return {row["name"] for row in rows}


class Database:
    """Opens connections to the chosen database and runs the schema migrations the first time it's used."""

    def __init__(self, url: str | None, sqlite_path: str):
        self.url = url
        self.sqlite_path = sqlite_path
        self.is_postgres = bool(url) and url.split(":", 1)[0] in ("postgres", "postgresql")
        if url and not self.is_postgres:
            raise ValueError("DATABASE_URL must start with postgres:// or postgresql://")
        self._pool = None
        self._ready = False
        # Several requests can arrive at once, so only one of them may set things up.
        self._setup_lock = threading.Lock()

    @property
    def kind(self) -> str:
        """Say which database is in use, for the health check and the logs."""
        return "postgres" if self.is_postgres else "sqlite"

    def _setup(self) -> None:
        """The first time the database is used, open the connection pool (Postgres) and bring the tables up to date."""
        with self._setup_lock:
            if self._ready:
                return
            if self.is_postgres:
                # A pool keeps a few connections open and lends them out. Opening a fresh, encrypted connection to
                # a database server for every query would add a noticeable delay to every reply. The imports are
                # here, not at the top, so local development with SQLite doesn't need the Postgres driver at all.
                from psycopg.rows import dict_row
                from psycopg_pool import ConnectionPool

                self._pool = ConnectionPool(self.url, min_size=1, max_size=10, open=True,
                                            kwargs={"row_factory": dict_row, "autocommit": True})
            # Imported here to avoid a circular import: migrations.py uses the Transaction class from this file.
            from agent.storage.migrations import run_migrations

            # Set _ready before migrating, because run_migrations opens a transaction through this same object.
            self._ready = True
            try:
                run_migrations(self)
            except Exception:
                self._ready = False
                raise

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        """Lend out one connection: from the pool for Postgres, or a freshly opened file for SQLite."""
        if self.is_postgres:
            with self._pool.connection() as conn:
                yield conn
            return
        # isolation_level=None means "don't start transactions behind our back"; transaction() starts them
        # explicitly. The timeout makes a writer wait up to ten seconds for another writer instead of failing.
        conn = sqlite3.connect(self.sqlite_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # WAL mode lets people read while someone else is writing, which matters once several chats run at once.
        conn.execute("PRAGMA journal_mode=WAL")
        with closing(conn):
            yield conn

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        """Run a group of statements as one unit: if any of them fails, none of them is saved.

        Use it like this:
            with db.transaction() as tx:
                tx.execute("INSERT ...", (...))
                tx.execute("UPDATE ...", (...))
        """
        if not self._ready:
            self._setup()
        with self._connection() as conn:
            if self.is_postgres:
                # psycopg's transaction() commits at the end, or rolls back if anything inside raised an error.
                with conn.transaction():
                    yield Transaction(conn, True)
            else:
                # IMMEDIATE takes SQLite's write lock at the start. Navi often calls several tools at once, and
                # each save reads and then writes. With a plain BEGIN, two of those overlapping would fail with
                # "database is locked" instead of waiting; with IMMEDIATE, the second simply waits its turn.
                conn.execute("BEGIN IMMEDIATE")
                try:
                    yield Transaction(conn, False)
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise

    def close(self) -> None:
        """Close the Postgres connection pool, if one is open. Called once when the app shuts down."""
        if self._pool is not None:
            self._pool.close()
            self._pool = None
            self._ready = False

    # Shortcuts for the common case of a single statement, so callers don't have to open a transaction themselves.

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self.transaction() as tx:
            tx.execute(sql, params)

    def fetch(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return tx.fetch(sql, params)

    def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.transaction() as tx:
            return tx.fetch_one(sql, params)


# One shared Database for the whole app, created the first time something asks for it.
_db: Database | None = None
_db_lock = threading.Lock()


def get_db() -> Database:
    """Return the app's database, choosing SQLite or Postgres from the DATABASE_URL setting."""
    global _db
    with _db_lock:
        if _db is None:
            s = get_settings()
            url = s.database_url.get_secret_value() if s.database_url else None
            _db = Database(url, str(s.sqlite_path))
            # Close the pool's connections cleanly when the program exits, rather than leaving the database
            # server to notice they've gone quiet.
            atexit.register(_db.close)
        return _db


def reset_db_for_tests(db: Database | None = None) -> None:
    """Swap in a different database (or forget the current one). Only the test scripts use this."""
    global _db
    with _db_lock:
        if _db is not None:
            _db.close()
        _db = db
        if db is not None:
            atexit.register(db.close)

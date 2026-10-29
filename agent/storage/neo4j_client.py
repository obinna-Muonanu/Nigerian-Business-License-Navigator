"""
It connects to Neo4j, the database that holds Navi's knowledge: the map of which requirements exist and which
must come before which, plus the official documents.

Whenever Navi looks something up, it goes through this file, and every lookup is done in "read-only" mode. The
database itself refuses any attempt to change data in that mode, so Navi can never damage its own knowledge,
even by mistake. Only the setup scripts that build the knowledge in the first place are allowed to write.
"""

from functools import lru_cache
from typing import Any

from neo4j import READ_ACCESS, WRITE_ACCESS, Driver, GraphDatabase, unit_of_work

from agent.config import get_settings


@lru_cache(maxsize=1)
def get_driver() -> Driver:
    """Create the Neo4j connection once and reuse it for the whole run.

    Setting up a connection is slow (it involves a secure handshake and finding the right server), so we
    do it only once; the driver manages its own pool of connections after that. We also check the
    connection straight away, so a wrong address or password in .env fails early with a clear error.
    """
    s = get_settings()
    # The password is stored hidden, and we only unwrap it here, to hand it to the driver.
    driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password.get_secret_value()))
    driver.verify_connectivity()
    return driver


def read(query: str, params: dict[str, Any] | None = None, timeout_s: float = 10.0) -> list[dict[str, Any]]:
    """Run a query in a read-only transaction with a time limit, and return the rows as dictionaries."""

    # The time limit is enforced by the Neo4j server itself, so a heavy query written by the model can't
    # hang the agent. The query's values (like $bt or $id) are sent separately from the query text. That
    # stops anyone from sneaking extra Cypher in through a value, and lets Neo4j reuse its query plan.
    @unit_of_work(timeout=timeout_s)
    def _work(tx):
        return tx.run(query, params or {}).data()

    # The session is opened in read mode and the query runs with execute_read, so the transaction is
    # read-only and Neo4j refuses any CREATE, MERGE, SET or DELETE inside it. This is the real guarantee
    # that the agent can never change the graph. The query checker in cypher_guard is just the first line
    # of defence.
    with get_driver().session(database=get_settings().neo4j_database, default_access_mode=READ_ACCESS) as session:
        return session.execute_read(_work)


def write(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a query that changes data. Only the ingestion scripts use this.

    execute_write automatically retries if there's a brief hiccup, like AuraDB switching servers.
    """

    def _work(tx):
        return tx.run(query, params or {}).data()

    with get_driver().session(database=get_settings().neo4j_database, default_access_mode=WRITE_ACCESS) as session:
        return session.execute_write(_work)


def explain(query: str) -> None:
    """Ask Neo4j to plan a query without running it, and raise an error if the query isn't valid.

    The text-to-Cypher tool uses this to catch syntax mistakes and unknown functions before anything runs.
    """
    read("EXPLAIN " + query, timeout_s=5.0)

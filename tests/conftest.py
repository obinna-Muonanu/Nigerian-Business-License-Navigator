"""
Shared set-up for the unit tests.

The unit tests check Navi's own logic (the safety checks, memory, sign-in and the API's rules) without calling any
outside service. So before anything else is imported, the settings are pointed at harmless test values: no real
Neo4j, Bedrock Guardrail or Postgres, and a made-up Supabase project. Real environment variables win over .env, so
these replace whatever is in your .env for the length of the test run, and the tests never touch your real data.

Tests that need a database get a brand-new, empty SQLite file in a temporary folder (the `db` fixture below).
"""

import os

os.environ.update({
    "AGENT_MODEL_ID": "test-model",
    "NEO4J_URI": "neo4j+s://unit-tests.invalid",
    "NEO4J_PASSWORD": "not-a-real-password",
    "DATABASE_URL": "",
    "GUARDRAIL_ID": "",
    "SUPABASE_URL": "https://unittests.supabase.co",
})

import pytest  # noqa: E402

from agent.storage.database import Database, reset_db_for_tests  # noqa: E402


@pytest.fixture
def db(tmp_path):
    """A fresh, empty SQLite database for one test, thrown away afterwards."""
    database = Database(None, str(tmp_path / "test.db"))
    reset_db_for_tests(database)
    yield database
    reset_db_for_tests(None)

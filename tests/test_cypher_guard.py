"""The check on AI-written graph queries: only single, read-only queries on known node types may run."""

import pytest

from agent.knowledge.cypher_guard import MAX_ROWS, validate


def test_a_plain_read_query_passes_and_gets_a_row_limit():
    ok, query = validate("MATCH (r:Requirement)-[:ISSUED_BY]->(g:Regulator) RETURN r.name, g.name")
    assert ok
    assert query.endswith(f"LIMIT {MAX_ROWS}")


def test_an_existing_limit_is_kept():
    ok, query = validate("MATCH (r:Requirement) RETURN r.name LIMIT 5")
    assert ok
    assert query.count("LIMIT") == 1


@pytest.mark.parametrize("cypher", [
    "MATCH (n) DETACH DELETE n",
    "MATCH (r:Requirement) SET r.name = 'x' RETURN r",
    "MERGE (r:Requirement {id: 'X'}) RETURN r",
    "CALL db.labels()",
    "MATCH (r:Requirement) CALL apoc.do.it() RETURN r",
    "CREATE (n:Requirement) RETURN n",
    "SHOW USERS",
])
def test_anything_that_writes_or_reaches_admin_features_is_refused(cypher):
    ok, _ = validate(cypher)
    assert not ok


def test_a_second_statement_cannot_be_slipped_in():
    ok, reason = validate("MATCH (r:Requirement) RETURN r; MATCH (n) DELETE n")
    assert not ok
    assert "one statement" in reason


def test_a_write_hidden_in_a_comment_is_stripped_not_run():
    ok, query = validate("MATCH (r:Requirement) RETURN r.name // DELETE everything")
    assert ok
    assert "DELETE" not in query


def test_unknown_node_types_are_refused():
    ok, reason = validate("MATCH (u:User) RETURN u.password")
    assert not ok
    assert "User" in reason


def test_forbidden_words_inside_quoted_text_are_harmless():
    ok, _ = validate("MATCH (r:Requirement) WHERE r.name CONTAINS 'set up' RETURN r.name")
    assert ok

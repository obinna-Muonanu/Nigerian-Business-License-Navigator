"""
It lets the AI answer unusual questions by writing its own database question, while making sure that question
is safe before it's ever run.

Most questions are answered with ready-made database questions written in advance. But for unusual ones, like
"which regulator issues the most permits?", the AI writes a fresh one. Because the AI could get it wrong, this
file checks it several ways first: it must only read data, never change it; it must only mention things that
exist in our database; and the database must confirm it's valid. Then it's run in read-only mode with a time
limit. If anything fails, Navi is told to fall back to the ready-made questions instead.
"""

import re

from strands import Agent

from agent.llm import build_fast_model
from agent.prompts import CYPHER_PROMPT
from agent.schemas import CypherQuery
from agent.storage import neo4j_client

# These are the words a safe query must never contain: anything that writes data, changes the database
# setup or permissions, calls a procedure (a procedure can reach write or admin features), or switches to
# another database. The word-boundary markers stop it matching inside harmless names like "dataset".
FORBIDDEN = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL|LOAD\s+CSV|FOREACH|APOC|GRANT|REVOKE|ALTER|TERMINATE|USE)\b",
    re.IGNORECASE,
)
# A query that only reads starts with one of these words. Anything else, like "SHOW USERS", is turned away
# before we even look further.
ALLOWED_START = re.compile(r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|RETURN)\b", re.IGNORECASE)
# These are the only node types and link types that exist in our graph. A query that names anything else
# has either made something up (so it would find nothing) or is poking around for data that shouldn't be there.
ALLOWED_LABELS = {
    "BusinessType", "Requirement", "Regulator", "RequiredDocument", "State", "Chunk", "Document",
    "REQUIRES", "DEPENDS_ON", "SATISFIES", "ISSUED_BY", "NEEDS_DOCUMENT", "APPLIES_IN", "DESCRIBES", "FROM",
}
# This finds the type names in a query, like the "Requirement" in (r:Requirement) or the "DEPENDS_ON" in
# -[:DEPENDS_ON]->. Values such as {id: $x} or {code: 'DRINKS'} aren't picked up, because they start with
# "$", a quote or a lowercase letter.
LABEL_PATTERN = re.compile(r":\s*`?([A-Z][A-Za-z_]*)`?")
# The most rows we hand back to the model. Big results cost tokens and rarely help answer a question.
MAX_ROWS = 50


def validate(cypher: str) -> tuple[bool, str]:
    """Check a query. Returns (True, the safe query) if it passes, or (False, the reason) if it doesn't."""
    # First strip out any comments, so nothing can be hidden inside them, and drop a semicolon at the end.
    query = re.sub(r"//.*?$|/\*.*?\*/", "", cypher, flags=re.MULTILINE | re.DOTALL).strip().rstrip(";").strip()
    # A semicolon left anywhere else means someone tried to slip in a second statement,
    # like "MATCH ...; MATCH (n) DELETE n".
    if ";" in query:
        return False, "Only one statement is allowed."
    if not ALLOWED_START.match(query):
        return False, "Query must start with MATCH, OPTIONAL MATCH, WITH, UNWIND or RETURN."
    # Blank out any quoted text before checking the words and type names, so a harmless phrase like
    # 'set up' inside a filter doesn't trip the check.
    code_only = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", query)
    forbidden = FORBIDDEN.search(code_only)
    if forbidden:
        return False, f"Forbidden clause: {forbidden.group(0)}"
    unknown = {label for label in LABEL_PATTERN.findall(code_only) if label not in ALLOWED_LABELS}
    if unknown:
        return False, f"Unknown labels or relationship types: {sorted(unknown)}"
    # If the model forgot to limit the number of rows, add a limit, so a broad query can't return thousands.
    if not re.search(r"\bLIMIT\s+\d+\s*$", query, re.IGNORECASE):
        query = f"{query}\nLIMIT {MAX_ROWS}"
    return True, query


def generate_cypher(question: str) -> CypherQuery:
    """Ask the fast model to write one query for the question, in a fixed format.

    This uses a small, separate agent with no tools. Its only job is turning a question into a query,
    and using the fast model keeps this extra call cheap.
    """
    writer = Agent(model=build_fast_model(), callback_handler=None, system_prompt="You write Neo4j Cypher.")
    result = writer(CYPHER_PROMPT.format(question=question), structured_output_model=CypherQuery)
    return result.structured_output


def answer_with_cypher(question: str) -> dict:
    """Run the whole process for one question. It never crashes: if something fails, it returns a fallback message.

    Returning a status instead of raising an error keeps the agent running. The model reads the reason
    and switches to the fixed tools, which is exactly the fallback the brief's stretch goal asks for.
    """
    fallback = ("Use the fixed graph tools instead (get_requirements via plan_steps, "
                "get_dependencies, explain_path).")

    # Step 1: ask the model for a query. If the model fails or its answer can't be read, fall back.
    try:
        generated = generate_cypher(question)
    except Exception as exc:
        return {"status": "QUERY_FAILED", "reason": f"Could not generate a query: {exc}", "fallback": fallback}

    # Step 2: check the query. If it's rejected, we still return it, which helps when reading the audit log later.
    ok, checked = validate(generated.cypher)
    if not ok:
        return {"status": "QUERY_REJECTED", "reason": checked, "cypher": generated.cypher, "fallback": fallback}

    # Steps 3 and 4: have Neo4j check the syntax without running anything, then run the query read-only
    # with a short time limit.
    try:
        neo4j_client.explain(checked)
        rows = neo4j_client.read(checked, timeout_s=5.0)
    except Exception as exc:
        return {"status": "QUERY_FAILED", "reason": str(exc)[:300], "cypher": checked, "fallback": fallback}

    # Step 5: an empty result usually means the query was wrong, not that there's really nothing to find,
    # so we suggest the fixed tools instead.
    if not rows:
        return {"status": "NO_ROWS", "cypher": checked, "fallback": fallback}
    return {"status": "ok", "cypher": checked, "explanation": generated.explanation, "rows": rows[:MAX_ROWS]}

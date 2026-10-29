"""
It searches the official documents for the details people ask about: fees, required documents, forms, offices
and timelines.

The documents are split into small pieces, and each piece is stored with a numeric "fingerprint" of its meaning.
When a question comes in, it's turned into a fingerprint too, and the closest matching pieces are returned, each
with its source. This finds the right passage even when the question uses different words from the document.

WHY IT MATTERS
If nothing matches closely enough, the search returns no answer at all, plus a link to the official website.
That way Navi says "I don't have that information" instead of guessing.
"""

from typing import Any

from agent.config import get_settings
from agent.knowledge.citations import source_entry
from agent.llm import embed_text
from agent.storage import neo4j_client

# The name of the vector index in Neo4j, which ingestion/load_graph.py creates. It's kept as one shared
# constant so the loader and the search can never disagree about it.
VECTOR_INDEX = "chunk_embedding"

# This query asks the vector index for more candidates than we need, then filters them by business type
# and keeps the best ones. We ask for extra because the index looks across all the documents, and
# filtering by business type afterwards could otherwise leave us with too few results. The links to the
# document and the requirement bring back everything needed for a citation in a single trip.
SEARCH_QUERY = f"""
CALL db.index.vector.queryNodes('{VECTOR_INDEX}', $candidates, $vector) YIELD node AS c, score
WHERE $bt IS NULL OR $bt IN c.business_types
MATCH (c)-[:FROM]->(d:Document)
OPTIONAL MATCH (c)-[:DESCRIBES]->(r:Requirement)
RETURN c.id AS chunk_id, c.text AS text, c.section AS section, d.doc_id AS doc_id, d.title AS document,
       d.date_read AS date_read, d.official_url AS official_url, d.freshness_note AS freshness_note,
       r.id AS requirement_id, r.name AS requirement_name, score
ORDER BY score DESC
LIMIT $top_k
"""

# When nothing is relevant, this finds the official pages for the user's business type. That way the
# agent can point to the official source, as the brief asks, instead of just saying "I don't know".
OFFICIAL_SOURCES_QUERY = """
MATCH (d:Document)
WHERE $bt IS NULL OR $bt IN d.business_types
RETURN d.title AS document, d.official_url AS url, d.official_contact AS contact
ORDER BY d.doc_id
"""


def _run(query: str, business_type: str | None, top_k: int) -> list[dict[str, Any]]:
    """Turn the question into a vector and fetch the closest chunks, before any relevance cut-off.

    The cut-off is applied by the caller, because `search` still needs the low-scoring rows to name the
    nearest documents when nothing passes.
    """
    vector = list(embed_text(query))
    return neo4j_client.read(
        SEARCH_QUERY,
        {"vector": vector, "candidates": max(top_k * 5, 20), "bt": business_type, "top_k": top_k},
    )


def search(query: str, business_type: str | None = None, top_k: int | None = None) -> dict[str, Any]:
    """Search the documents by meaning, and only return chunks that are relevant enough.

    It returns either {"status": "ok", "results": [...]}, or, when nothing is relevant,
    {"status": "NO_RELEVANT_DOCUMENTS", "closest_documents": [...], "official_sources": [...]}.
    """
    s = get_settings()
    top_k = top_k or s.top_k
    rows = _run(query, business_type, top_k)
    # Neo4j scores similarity from 0 to 1. The cut-off was tuned against the evaluation questions.
    relevant = [r for r in rows if r["score"] >= s.min_relevance]

    if not relevant:
        # Rather than invent an answer, point to the official pages of the closest documents. Keying them
        # by document means two chunks from the same document only show up once.
        closest = {r["doc_id"]: {"document": r["document"], "url": r["official_url"]} for r in rows[:2]}
        return {
            "status": "NO_RELEVANT_DOCUMENTS",
            "message": "The knowledge base has nothing reliable on this. Say so, point to an official "
                       "source below, and offer a human handoff.",
            "closest_documents": list(closest.values()),
            "official_sources": neo4j_client.read(OFFICIAL_SOURCES_QUERY, {"bt": business_type}),
        }

    # Each result comes with a ready-made source: the footnote line and the official link. The model just
    # copies that finished line into the Sources list instead of writing its own, which keeps citations
    # consistent for users and easy for the grounding hook and the evaluation to check.
    return {
        "status": "ok",
        "results": [
            {
                "text": r["text"],
                "source": source_entry(r["document"], r["section"], r["date_read"], r["official_url"]),
                "requirement_id": r["requirement_id"],
                "freshness_note": r["freshness_note"],
                "score": round(r["score"], 3),
            }
            for r in relevant
        ],
    }


def best_requirement_for(text: str) -> dict[str, str] | None:
    """Find the requirement whose section best matches a piece of free text. Used to work out which step a name refers to.

    Only a chunk that is both relevant enough and linked to a requirement counts, so a vague phrase
    isn't forced onto the wrong step.
    """
    for row in _run(text, None, 5):
        if row["requirement_id"] and row["score"] >= get_settings().min_relevance:
            return {"id": row["requirement_id"], "name": row["requirement_name"]}
    return None

"""WHAT THIS FILE DOES
It fills the Neo4j database with Navi's knowledge.

It does two things. First, it loads the approved knowledge graph: every requirement, who issues it, which businesses and
states it applies to, the documents it needs, and which steps must come before which. Second, it loads the official
documents themselves, cut into small pieces, each with a numeric "fingerprint" of its meaning so they can be searched by
meaning. It then builds a search index over those pieces.

At the end it counts the graph and confirms it's at least as big as the project brief requires. It's safe to run again
after a fix; it updates what's there rather than duplicating it.

HOW TO RUN IT
    python -m ingestion.load_graph                load the approved graph
    python -m ingestion.load_graph --reset        empty the database first, then load
    python -m ingestion.load_graph --unreviewed   load the unchecked version (only for a quick trial)
"""

import argparse
import hashlib
import json

from agent.config import get_settings
from agent.knowledge.retrieval_service import VECTOR_INDEX
from agent.llm import embed_text
from agent.schemas import BUSINESS_TYPE_NAMES, STATES, ExtractedDocumentGraph
from agent.storage import neo4j_client
from ingestion.parse_docs import chunk_document, load_documents

# These rules stop duplicate nodes. Two "R01" nodes, for example, would split the chain of dependencies in two.
# Each rule also creates an index, which makes looking things up by ID fast. "IF NOT EXISTS" means running
# this again is harmless.
CONSTRAINTS = [
    "CREATE CONSTRAINT req_id IF NOT EXISTS FOR (n:Requirement) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT bt_code IF NOT EXISTS FOR (n:BusinessType) REQUIRE n.code IS UNIQUE",
    "CREATE CONSTRAINT state_name IF NOT EXISTS FOR (n:State) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT regulator_name IF NOT EXISTS FOR (n:Regulator) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT doc_name IF NOT EXISTS FOR (n:RequiredDocument) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.doc_id IS UNIQUE",
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.id IS UNIQUE",
]

# This creates the requirement nodes, along with their regulator and the states they apply in. UNWIND sends
# the whole list in a single query, instead of one trip to the database per requirement. MERGE means "use it
# if it already exists, otherwise create it", which is what makes running the loader again safe.
UPSERT_REQUIREMENTS = """
UNWIND $rows AS row
MERGE (r:Requirement {id: row.id})
SET r.name = row.name, r.recurring = row.recurring, r.doc_id = row.doc_id
MERGE (g:Regulator {name: row.regulator})
MERGE (r)-[:ISSUED_BY]->(g)
WITH r, row
UNWIND row.states AS state_name
MATCH (s:State {name: state_name})
MERGE (r)-[:APPLIES_IN]->(s)
"""

# This links business types to the requirements they need. The condition is part of what makes each link
# unique, so one business type can link to the same requirement under two different conditions, as two
# separate links, without one overwriting the other.
UPSERT_REQUIRES = """
UNWIND $rows AS row
MATCH (b:BusinessType {code: row.business_type}), (r:Requirement {id: row.id})
MERGE (b)-[rq:REQUIRES {condition: row.condition}]->(r)
"""

# This links each requirement to the documents the applicant has to provide.
UPSERT_DOCUMENTS_NEEDED = """
UNWIND $rows AS row
MATCH (r:Requirement {id: row.id})
MERGE (d:RequiredDocument {name: row.document})
MERGE (r)-[:NEEDS_DOCUMENT]->(d)
"""

# This adds the "must come after" links, each with its reason. They're loaded only once every requirement
# exists, so it doesn't matter what order things appear in the file.
UPSERT_DEPENDS_ON = """
UNWIND $rows AS row
MATCH (r:Requirement {id: row.id}), (p:Requirement {id: row.prerequisite})
MERGE (r)-[d:DEPENDS_ON]->(p)
SET d.reason = row.reason
"""

# This links each route to the parent step it satisfies, like the sole-proprietor route to CAC registration.
UPSERT_SATISFIES = """
UNWIND $rows AS row
MATCH (r:Requirement {id: row.id}), (p:Requirement {id: row.parent})
MERGE (r)-[:SATISFIES]->(p)
"""

# The next two queries build the document side of GraphRAG. A Document node holds the citation details (the
# title, the date read, the official link and the freshness note) once, instead of copying them onto every chunk.
UPSERT_DOCUMENT = """
MERGE (d:Document {doc_id: $doc_id})
SET d.title = $title, d.date_read = $date_read, d.official_url = $official_url,
    d.official_contact = $official_contact, d.freshness_note = $freshness_note,
    d.business_types = $business_types
"""

# This saves each chunk with its vector, and links it to its document. The vector is stored in Neo4j's compact
# vector format, which is smaller and quicker to index than a plain list. The last part only links a chunk to
# a requirement when the chunk is a requirement section, which ties the text to its place in the graph.
UPSERT_CHUNKS = """
UNWIND $rows AS row
MERGE (c:Chunk {id: row.id})
SET c.text = row.text, c.section = row.section, c.part = row.part, c.business_types = row.business_types
WITH c, row
CALL db.create.setNodeVectorProperty(c, 'embedding', row.embedding)
WITH c, row
MATCH (d:Document {doc_id: row.doc_id})
MERGE (c)-[:FROM]->(d)
WITH c, row
WHERE row.requirement_id IS NOT NULL
MATCH (r:Requirement {id: row.requirement_id})
MERGE (c)-[:DESCRIBES]->(r)
"""


def _vector_index_cypher(dimensions: int) -> str:
    """Write the statement that creates the vector index.

    Its size has to match the size of our embeddings, and it uses cosine similarity, which suits Titan's
    normalised vectors. It's built as text because index settings can't be passed in as query values.
    """
    return (
        f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS FOR (c:Chunk) ON (c.embedding) "
        f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dimensions}, `vector.similarity_function`: 'cosine'}}}}"
    )


def _load_graph_json(unreviewed: bool) -> list[ExtractedDocumentGraph]:
    """Read the reviewed graph (or, for a quick trial, the raw extraction) and check it again.

    Checking it against the extraction form catches mistakes made while editing the file by hand, like a typo
    in a condition code, before anything is written to Neo4j.
    """
    s = get_settings()
    path = s.graph_dir / ("extracted.json" if unreviewed else "reviewed.json")
    if not path.exists():
        hint = "python -m ingestion.extract_graph" if unreviewed else "review extracted.json, then --approve"
        raise SystemExit(f"{path} not found. Run: {hint}")
    if unreviewed:
        print("WARNING: loading the UNREVIEWED extraction. Review it before your demo.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ExtractedDocumentGraph(**d) for d in payload["documents"]]


def _embed_with_cache(texts: list[str]) -> list[list[float]]:
    """Turn each piece of text into a vector, but only once. Later runs reuse the saved vectors, which saves money and time."""
    s = get_settings()
    cache_path = s.graph_dir / "embeddings_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    vectors = []
    for i, text in enumerate(texts, 1):
        # Each saved vector is filed under a fingerprint of the model, the vector size and the text. So changing
        # the model or size makes fresh vectors instead of reusing the wrong kind, and editing one chunk's text
        # only re-does that one chunk.
        key = hashlib.sha1(f"{s.embed_model_id}:{s.embed_dimensions}:{text}".encode()).hexdigest()
        if key not in cache:
            cache[key] = list(embed_text(text))
            if i % 20 == 0:
                print(f"   embedded {i}/{len(texts)}")
        vectors.append(cache[key])
    cache_path.write_text(json.dumps(cache))
    return vectors


def load(reset: bool, unreviewed: bool) -> None:
    """Load everything into Neo4j: the fixed lists, the reviewed graph, the documents and chunks, and the vector index."""
    s = get_settings()

    # Step 0: wipe the database first, if asked (the vector index, then all the data). Do this after big edits to
    # reviewed.json, because the normal load adds and updates things but never removes nodes or links you
    # deleted from the file. The graph is small (a few hundred nodes), so deleting everything at once is fine.
    if reset:
        print("Resetting database ...")
        neo4j_client.write(f"DROP INDEX {VECTOR_INDEX} IF EXISTS")
        neo4j_client.write("MATCH (n) DETACH DELETE n")

    # Step 1: add the duplicate-preventing rules, then the business types and states. Those two come from
    # schemas.py rather than from Claude, so their codes always match the ones the tools use.
    for statement in CONSTRAINTS:
        neo4j_client.write(statement)
    neo4j_client.write(
        "UNWIND $rows AS row MERGE (b:BusinessType {code: row.code}) SET b.name = row.name",
        {"rows": [{"code": c, "name": n} for c, n in BUSINESS_TYPE_NAMES.items()]},
    )
    neo4j_client.write("UNWIND $names AS name MERGE (:State {name: name})", {"names": STATES})

    # Step 2: turn the reviewed graph into lists of rows, one list for each kind of link, so each kind can be
    # loaded in a single query. A federal requirement (marked "ALL") gets linked to every state, which keeps
    # filtering by state in the queries nice and simple.
    graphs = _load_graph_json(unreviewed)
    req_rows, requires_rows, docs_rows, dep_rows, sat_rows = [], [], [], [], []
    for graph in graphs:
        for r in graph.requirements:
            states = STATES if "ALL" in r.applies_in else [st for st in r.applies_in if st in STATES]
            req_rows.append({"id": r.id, "name": r.name, "recurring": r.recurring, "doc_id": graph.doc_id,
                             "regulator": r.regulator.strip(), "states": states})
            requires_rows += [{"id": r.id, "business_type": a.business_type, "condition": a.condition} for a in r.applies_to]
            docs_rows += [{"id": r.id, "document": d.strip()[:120]} for d in r.documents if d.strip()]
            dep_rows += [{"id": r.id, "prerequisite": d.requirement_id, "reason": d.reason} for d in r.depends_on]
            if r.satisfies:
                sat_rows.append({"id": r.id, "parent": r.satisfies})

    # The order matters here: the nodes go in first, then the links that connect them. The "must come after"
    # and "satisfies" links need both of their ends to exist already.
    print(f"Loading {len(req_rows)} requirements ...")
    neo4j_client.write(UPSERT_REQUIREMENTS, {"rows": req_rows})
    neo4j_client.write(UPSERT_REQUIRES, {"rows": requires_rows})
    neo4j_client.write(UPSERT_DOCUMENTS_NEEDED, {"rows": docs_rows})
    neo4j_client.write(UPSERT_DEPENDS_ON, {"rows": dep_rows})
    neo4j_client.write(UPSERT_SATISFIES, {"rows": sat_rows})

    # Point out any dependency that couldn't be linked because it names an unknown requirement, rather than
    # quietly dropping it.
    known = {r["id"] for r in req_rows}
    dangling = [d for d in dep_rows if d["prerequisite"] not in known]
    for d in dangling:
        print(f"   skipped dependency {d['id']} -> {d['prerequisite']} (unknown ID)")

    # Step 3: load the documents, then the chunks with their vectors. The documents have to exist first,
    # because each chunk looks up its document to link to it.
    docs = load_documents(s.kb_dir)
    for doc in docs:
        neo4j_client.write(UPSERT_DOCUMENT, {
            "doc_id": doc.doc_id, "title": doc.title, "date_read": doc.date_read,
            "official_url": doc.official_url, "official_contact": str(doc.front_matter.get("official_contact", "")),
            "freshness_note": str(doc.front_matter.get("freshness_note", "")), "business_types": doc.business_types,
        })
    chunks = [c for doc in docs for c in chunk_document(doc)]
    print(f"Embedding {len(chunks)} chunks with {s.embed_model_id} ...")
    vectors = _embed_with_cache([c.embed_text for c in chunks])
    chunk_rows = [
        {"id": c.id, "doc_id": c.doc_id, "section": c.section, "part": c.part, "text": c.text,
         "business_types": c.business_types, "requirement_id": c.requirement_id, "embedding": v}
        for c, v in zip(chunks, vectors)
    ]
    # Send the chunks in batches of 50, which keeps each write light.
    for start in range(0, len(chunk_rows), 50):
        neo4j_client.write(UPSERT_CHUNKS, {"rows": chunk_rows[start:start + 50]})

    # Step 4: create the vector index over the chunks. It's created after the data is in, and Neo4j then builds
    # it in the background.
    neo4j_client.write(_vector_index_cypher(s.embed_dimensions))

    # Step 5: check the graph is big enough for the brief, which asks for at least 30 nodes and 60 relationships.
    # The document and chunk nodes and their links aren't counted, because the brief's minimum is about the
    # knowledge graph, and counting the search side as well would overstate it.
    kg_nodes = neo4j_client.read(
        "MATCH (n) WHERE n:BusinessType OR n:Requirement OR n:Regulator OR n:RequiredDocument OR n:State "
        "RETURN count(n) AS c")[0]["c"]
    kg_rels = neo4j_client.read(
        "MATCH ()-[r:REQUIRES|DEPENDS_ON|ISSUED_BY|NEEDS_DOCUMENT|APPLIES_IN|SATISFIES]->() RETURN count(r) AS c")[0]["c"]
    print(f"\nKnowledge graph: {kg_nodes} nodes, {kg_rels} relationships "
          f"({'OK' if kg_nodes >= 30 and kg_rels >= 60 else 'BELOW the brief minimum'})")
    print(f"Retrieval: {len(chunk_rows)} chunks indexed in '{VECTOR_INDEX}'.")
    print("Note: a new vector index can take a few seconds to come ONLINE before searches return results.")


def main() -> None:
    """Read the command-line options and run the load."""
    parser = argparse.ArgumentParser(description="Load graph + chunks into Neo4j")
    parser.add_argument("--reset", action="store_true", help="Delete everything in the database first")
    parser.add_argument("--unreviewed", action="store_true", help="Load extracted.json instead of reviewed.json")
    args = parser.parse_args()
    load(reset=args.reset, unreviewed=args.unreviewed)


if __name__ == "__main__":
    main()

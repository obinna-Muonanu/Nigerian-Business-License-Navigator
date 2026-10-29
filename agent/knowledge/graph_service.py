"""WHAT THIS FILE DOES
It works out what a business needs and in what order, using the knowledge graph. This is what makes Navi's
checklists reliable.

The knowledge graph is a map of every registration, licence and permit, which business types and states each
applies to, and which ones must be finished before others can start (for example, a NAFDAC facility inspection
must come before NAFDAC product registration). This file reads that map and:
    lists the requirements that apply to the user's business and state;
    puts them in a valid order, so nothing appears before something it depends on;
    leaves out the steps the user has already finished;
    marks which steps can be started today and which are waiting on something else;
    explains why one step has to come before another, quoting the official reason.

WHY IT MATTERS
Order is something a plain document search can't work out. This file is the reason the graph was worth building.
"""

from functools import lru_cache
from typing import Any

from agent.knowledge.citations import document_line, source_entry
from agent.schemas import BUSINESS_TYPE_NAMES, UserProfile
from agent.storage import neo4j_client

# All the graph queries are kept together here, so you can see every one in one place and paste any of
# them into Neo4j Browser to try it out.

# This fetches every requirement for a business type in a state, along with its conditions and what it
# depends on. OPTIONAL MATCH keeps requirements that have no regulator, prerequisite or parent, instead of
# dropping them. The collect() parts gather the things that can have several values (conditions,
# prerequisites) into lists, so we get one row per requirement, and head() picks the single regulator or parent.
REQUIREMENTS_QUERY = """
MATCH (b:BusinessType {code: $bt})-[rq:REQUIRES]->(r:Requirement)-[:APPLIES_IN]->(:State {name: $state})
OPTIONAL MATCH (r)-[:ISSUED_BY]->(g:Regulator)
OPTIONAL MATCH (r)-[:DEPENDS_ON]->(p:Requirement)
OPTIONAL MATCH (r)-[:SATISFIES]->(parent:Requirement)
RETURN r.id AS id, r.name AS name, coalesce(r.recurring, false) AS recurring, r.doc_id AS doc_id,
       head(collect(DISTINCT g.name)) AS regulator,
       collect(DISTINCT rq.condition) AS conditions,
       collect(DISTINCT p.id) AS depends_on,
       head(collect(DISTINCT parent.id)) AS satisfies
"""

# This finds a requirement by its exact code, ignoring upper or lower case, so "d05" works as well as "D05".
RESOLVE_BY_ID = "MATCH (r:Requirement) WHERE toUpper(r.id) = toUpper($ref) RETURN r.id AS id, r.name AS name LIMIT 1"

# This finds a requirement by part of its name, shortest name first. It matches both ways round, so it
# copes with "CAC registration" (which is inside the full name) and with "the CAC business registration
# step" (which has the full name inside it).
RESOLVE_BY_NAME = """
MATCH (r:Requirement)
WHERE toLower(r.name) CONTAINS toLower($ref) OR toLower($ref) CONTAINS toLower(r.name)
RETURN r.id AS id, r.name AS name ORDER BY size(r.name) LIMIT 5
"""

# This gets the steps that must come directly before a requirement (with the reason stored on each link)
# and the steps it directly unlocks. The CASE part stops us getting a list of empty entries when a step
# has no prerequisites at all.
DIRECT_DEPENDENCIES = """
MATCH (r:Requirement {id: $id})
OPTIONAL MATCH (r)-[d:DEPENDS_ON]->(p:Requirement)
OPTIONAL MATCH (p)-[:ISSUED_BY]->(g:Regulator)
WITH r, collect(DISTINCT CASE WHEN p IS NULL THEN null
                 ELSE {id: p.id, name: p.name, regulator: g.name, reason: d.reason} END) AS before
OPTIONAL MATCH (n:Requirement)-[:DEPENDS_ON]->(r)
RETURN r.id AS id, r.name AS name, before, collect(DISTINCT {id: n.id, name: n.name}) AS unlocks
"""

# This gets every step that has to come first, directly or further back (up to ten links), with how far
# back each one is. It's sorted furthest back first, which is the order they need to be done in.
ALL_PREREQUISITES = """
MATCH path = (r:Requirement {id: $id})-[:DEPENDS_ON*1..10]->(p:Requirement)
RETURN p.id AS id, p.name AS name, min(length(path)) AS depth
ORDER BY depth DESC, id
"""

# This finds the shortest chain of "must come after" links from a later step back to an earlier one. It's
# the chain of relationships behind the answer that the brief asks explain_path to show.
PATH_QUERY = """
MATCH (a:Requirement {id: $later}), (b:Requirement {id: $earlier})
MATCH p = shortestPath((a)-[:DEPENDS_ON*1..10]->(b))
RETURN [n IN nodes(p) | {id: n.id, name: n.name}] AS nodes,
       [rel IN relationships(p) | {from: startNode(rel).id, to: endNode(rel).id, reason: rel.reason}] AS edges
"""

# This gets the citation details for the documents a checklist's steps come from, so we can write one
# Sources line per document.
DOCUMENTS_QUERY = """
MATCH (d:Document) WHERE d.doc_id IN $ids
RETURN d.doc_id AS doc_id, d.title AS title, d.date_read AS date_read, d.official_url AS url
"""

# This finds the different routes that satisfy a parent step. For example R01-SP, R01-PT and so on are all
# ways of doing R01, so recording any one of them counts as the parent being done.
ROUTES_QUERY = "MATCH (r:Requirement)-[:SATISFIES]->(:Requirement {id: $id}) RETURN r.id AS id"

# This goes the other way: it finds the parent a route belongs to (R01-LTD belongs to R01). Other steps
# depend on the parent, not on the route.
PARENT_QUERY = "MATCH (r:Requirement {id: $id})-[:SATISFIES]->(p:Requirement) RETURN p.id AS id LIMIT 1"

# This picks one source section for each requirement, to cite a chain of dependencies. Sorting by part and
# taking the first one gives us the start of the section, which is where the "Must be done after" line is.
EVIDENCE_QUERY = """
UNWIND $ids AS rid
MATCH (c:Chunk)-[:DESCRIBES]->(:Requirement {id: rid})
MATCH (c)-[:FROM]->(d:Document)
WITH rid, c, d ORDER BY c.part
WITH rid, head(collect({document: d.title, section: c.section, date_read: d.date_read, url: d.official_url})) AS source
RETURN rid AS id, source
"""

# Each link from a business type to a requirement carries a condition (see schemas.Condition). The two
# tables below say which profile answer makes each condition true.

STRUCTURE_CONDITIONS = {
    "structure_sole": "sole_proprietorship",
    "structure_partnership": "partnership",
    "structure_private": "private_company",
    "structure_public": "public_company",
}
VARIANT_CONDITIONS = {
    "variant_resell": "resell",
    "variant_import": "import",
    "variant_make_locally": "make_locally",
}
# These are the plain-language notes shown next to steps that may or may not apply. It's better to show a
# step with "only if..." than to quietly hide one the user might actually need.
CONDITIONAL_NOTES = {
    "major_importance": "Only if the NDPC 'major importance' check (N01) says your business qualifies.",
    "not_small_business": "Only once your business is no longer a small business under the tax rules.",
    "collects_personal_data": "Only if you collect customers' personal data.",
    "sells_online": "Only if you sell online.",
    "company": "Only if you register as a limited company.",
    "variant": "Depends on whether you resell, import your own brand or make products locally.",
    "structure": "Depends on the legal structure you choose.",
}
# When a requirement has several conditions, this decides which result is stronger: required beats
# conditional, conditional beats optional, and so on.
STATUS_RANK = {"required": 3, "conditional": 2, "optional": 1, "no": 0}


def _evaluate(condition: str, p: UserProfile) -> tuple[str, str | None]:
    """Decide whether one condition holds for this user's profile.

    It returns a status and an optional note. The status is "required", "conditional", "optional" or
    "no". "Conditional" means the profile doesn't tell us yet, so the step is shown with a note. One rule
    runs through all of this: a fact we haven't asked about yet never counts as a "no".
    """
    # Applies to every business of this type.
    if condition == "always":
        return "required", None
    # Only recommended: we show it, but mark it so the user knows they can skip it.
    if condition == "optional":
        return "optional", "Recommended but not mandatory for your business type."
    # Applies to one particular legal structure, like the business-name route for a sole proprietor.
    if condition in STRUCTURE_CONDITIONS:
        if p.legal_structure in (None, "undecided"):
            return "conditional", CONDITIONAL_NOTES["structure"]
        return ("required", None) if p.legal_structure == STRUCTURE_CONDITIONS[condition] else ("no", None)
    # Applies to any limited company, like company income tax.
    if condition == "company":
        if p.legal_structure in (None, "undecided"):
            return "conditional", CONDITIONAL_NOTES["company"]
        return ("required", None) if p.legal_structure in ("private_company", "public_company") else ("no", None)
    # Simple yes or no facts from the profile. Demo scenario 5 ("I also want to sell online and collect
    # customers' details") switches these on.
    if condition in ("collects_personal_data", "sells_online"):
        value = getattr(p, condition)
        if value is None:
            return "conditional", CONDITIONAL_NOTES[condition]
        return ("required", None) if value else ("no", None)
    # NDPC registration depends on the result of an earlier check (N01), which we can't know in advance.
    # The only time we can rule it out is when the business collects no personal data at all.
    if condition == "major_importance":
        if p.collects_personal_data is False:
            return "no", None
        return "conditional", CONDITIONAL_NOTES["major_importance"]
    # Depends on whether a cosmetics or furniture business resells, imports its own brand or makes locally.
    if condition in VARIANT_CONDITIONS:
        if p.product_variant is None:
            return "conditional", CONDITIONAL_NOTES["variant"]
        return ("required", None) if p.product_variant == VARIANT_CONDITIONS[condition] else ("no", None)
    # Rules based on turnover, like VAT. We don't ask for turnover, so this always stays conditional.
    if condition == "not_small_business":
        return "conditional", CONDITIONAL_NOTES["not_small_business"]
    # A condition we don't recognise, probably from a bad extraction. We show the step, but flag it.
    return "conditional", f"Condition '{condition}' needs checking with the regulator."


def _combine(conditions: list[str], p: UserProfile) -> tuple[str, str | None]:
    """Work out whether a step applies when it has several conditions. The strongest one wins.

    For example, a privacy notice might be "always" for an online cosmetics store and "sells_online" for
    a drinks maker. If either condition holds for this user, the step applies.
    """
    best: tuple[str, str | None] = ("no", None)
    for condition in conditions or ["always"]:
        candidate = _evaluate(condition, p)
        if STATUS_RANK[candidate[0]] > STATUS_RANK[best[0]]:
            best = candidate
    return best


# The functions below are what the tools call.

def get_requirements(profile: UserProfile) -> list[dict[str, Any]]:
    """Get the requirements for the user's business type and state, each marked with whether it applies."""
    # The graph narrows things down to the business type and state. Python then decides the conditions,
    # because they depend on profile answers, and that logic is much easier to follow and test in code
    # than inside a query.
    rows = neo4j_client.read(REQUIREMENTS_QUERY, {"bt": profile.business_type, "state": profile.state})
    result = []
    for row in rows:
        status, note = _combine(row["conditions"], profile)
        result.append({**row, "status": status, "note": note})
    return result


def resolve_requirement(ref: str) -> dict[str, str] | None:
    """Work out which requirement someone means, whether they say "D05", "d05" or "NAFDAC product registration".

    Users, and the model, refer to steps in all sorts of ways. We try the quickest kind of match first.
    """
    ref = (ref or "").strip()
    if not ref:
        return None
    # First, try an exact code.
    rows = neo4j_client.read(RESOLVE_BY_ID, {"ref": ref})
    if rows:
        return rows[0]
    # Then try matching part of the name.
    rows = neo4j_client.read(RESOLVE_BY_NAME, {"ref": ref})
    if rows:
        return rows[0]
    # As a last resort, search by meaning, through the document section that describes a requirement.
    # This is imported here rather than at the top of the file, because the two services import each
    # other and that would otherwise go round in a circle.
    from agent.knowledge.retrieval_service import best_requirement_for

    return best_requirement_for(ref)


def is_recorded_done(req_id: str, done: set[str]) -> bool:
    """Check whether a step is already in the user's progress. For a parent like R01, any of its routes counts.

    The confirmation hook uses this. Marking a step done when it's already recorded changes nothing, so
    there's no need to ask for confirmation, and asking would only stop the agent answering "what's left?".
    """
    if req_id in done:
        return True
    return any(row["id"] in done for row in neo4j_client.read(ROUTES_QUERY, {"id": req_id}))


def _canonical(req_id: str) -> str:
    """Swap a route (like R01-SP) for the parent step it belongs to (R01). Any other code comes back unchanged.

    Other steps depend on the parent R01, so searching for a chain starting from a route would find nothing.
    """
    rows = neo4j_client.read(PARENT_QUERY, {"id": req_id})
    return rows[0]["id"] if rows else req_id


def get_dependencies(req_id: str) -> dict[str, Any]:
    """Get what must come directly before a step (with reasons), everything that comes before it, and what it unlocks."""
    direct = neo4j_client.read(DIRECT_DEPENDENCIES, {"id": req_id})
    if not direct:
        return {"status": "not_found", "id": req_id}
    row = direct[0]
    transitive = neo4j_client.read(ALL_PREREQUISITES, {"id": req_id})
    # OPTIONAL MATCH leaves empty placeholders behind when there's nothing to collect, so we filter those out.
    return {
        "status": "ok",
        "id": row["id"],
        "name": row["name"],
        "must_come_first": [b for b in row["before"] if b],
        "full_chain_earliest_first": transitive,
        "unlocks": [u for u in row["unlocks"] if u.get("id")],
    }


def explain_path(later_id: str, earlier_id: str) -> dict[str, Any]:
    """Find the chain of "must come after" links that forces the earlier step to come before the later one."""
    later, earlier = _canonical(later_id), _canonical(earlier_id)
    rows = neo4j_client.read(PATH_QUERY, {"later": later, "earlier": earlier})
    reversed_question = False
    if not rows:
        # The user may have asked about the pair the other way round, like "why X before Y" when X is actually later.
        rows = neo4j_client.read(PATH_QUERY, {"later": earlier, "earlier": later})
        reversed_question = bool(rows)
    if not rows:
        # Finding no chain at all is a real answer too: it means the two steps don't depend on each other.
        # We say so plainly rather than inventing a reason.
        return {
            "status": "no_path",
            "message": "The graph has no dependency between these two steps; "
                       "they can be done in either order unless the documents say otherwise.",
        }
    nodes, edges = rows[0]["nodes"], rows[0]["edges"]
    # Attach one citation to each step in the chain, so every link can be traced back to a document. It's in
    # the same footnote-ready format as the search results, so the reply cites it the same way.
    evidence = {
        r["id"]: source_entry(r["source"]["document"], r["source"]["section"], r["source"]["date_read"], r["source"]["url"])
        for r in neo4j_client.read(EVIDENCE_QUERY, {"ids": [n["id"] for n in nodes]})
    }
    # Put a name next to every code. The model has to explain the chain using names and never show the codes.
    names = {n["id"]: n["name"] for n in nodes}
    return {
        "status": "ok",
        "note": "The pair was reversed: the second step actually comes first." if reversed_question else None,
        "chain_later_to_earlier": [
            {"step": e["from"], "step_name": names.get(e["from"]),
             "must_follow": e["to"], "must_follow_name": names.get(e["to"]),
             "because": e["reason"], "source": evidence.get(e["from"])}
            for e in edges
        ],
        # For the diagram, the links are flipped to run from earlier to later, so it reads left to right in time.
        "graph": _graph_payload(nodes, [{"from": e["to"], "to": e["from"], "label": "before"} for e in edges]),
    }


def plan_steps(profile: UserProfile, done: set[str]) -> dict[str, Any]:
    """Build the ordered checklist for this user, leaving out the steps they've already finished.

    It works in four stages. First it fetches every requirement for the business type and state and
    checks its conditions. Then it folds the different CAC registration routes into a single CAC step.
    Next it sorts the steps so that anything a step depends on always comes before it. Finally it marks
    each remaining step as either ready to start now or waiting on something unfinished.
    """
    # Without a business type and a state there's nothing to look up, so the agent has to ask first.
    missing = profile.missing_for_planning()
    if not profile.business_type or not profile.state:
        return {"status": "need_profile", "missing": missing}

    rows = get_requirements(profile)
    by_id = {r["id"]: r for r in rows}

    # CAC registration (R01) counts as done if the user finished R01 itself, or any of its routes, or told us
    # they're already registered. We work on a copy of the done list so we don't change the caller's.
    routes = [r for r in rows if r.get("satisfies")]
    route_ids = {r["id"] for r in routes}
    done = set(done)
    for route in routes:
        if route["id"] in done:
            done.add(route["satisfies"])
    if profile.cac_registered:
        done.add("R01")

    # Keep the steps that apply, but not the individual routes. The routes appear as details of their
    # parent instead, so the checklist says "1. CAC registration (business name)" rather than listing four
    # different CAC options as separate steps.
    steps = {r["id"]: r for r in rows if r["status"] != "no" and r["id"] not in route_ids}

    # On the parent step, describe the route this user should take, or the options if we can't tell yet.
    for parent_id in {r["satisfies"] for r in routes}:
        if parent_id in steps:
            chosen = [r for r in routes if r["satisfies"] == parent_id and r["status"] == "required"]
            options = [r for r in routes if r["satisfies"] == parent_id and r["status"] != "no"]
            steps[parent_id]["route"] = (
                {"chosen": chosen[0]["id"], "name": chosen[0]["name"]} if chosen
                else {"choose_one_of": [{"id": o["id"], "name": o["name"]} for o in options]}
            )

    # Now we work out each step's "depth": the length of the longest chain of steps that has to come before
    # it. Sorting by depth gives a valid order, because a step is always deeper than everything it depends
    # on, so its prerequisites always sort ahead of it. We remember each answer so every step is only worked
    # out once, and we keep track of the steps we're in the middle of so that a loop in the data (from a bad
    # extraction) gets noticed instead of going round forever.
    depth: dict[str, int] = {}
    visiting: set[str] = set()
    cycles: list[str] = []

    def _depth(node: str) -> int:
        if node in depth:
            return depth[node]
        if node in visiting:
            cycles.append(node)
            return 0
        visiting.add(node)
        # Only prerequisites that are part of this user's plan count; the others don't apply to them.
        prereqs = [d for d in steps[node]["depends_on"] if d in steps]
        depth[node] = 1 + max((_depth(d) for d in prereqs), default=-1)
        visiting.discard(node)
        return depth[node]

    for step_id in steps:
        _depth(step_id)

    # Sort the steps: one-off steps before recurring ones, then by depth, then required before conditional.
    # Recurring items like renewals and annual returns go last, because they happen once the business is
    # running. Sorting by code at the very end makes the order completely predictable, which keeps
    # evaluation runs repeatable.
    ordered = sorted(
        steps.values(),
        key=lambda r: (r["recurring"], depth[r["id"]], -STATUS_RANK[r["status"]], r["id"]),
    )

    # Split the steps into finished and remaining, and for each remaining step list what it's still waiting
    # on. Knowing which steps are ready now lets the agent say "you can do these three today, side by side".
    remaining, completed = [], []
    for r in ordered:
        if r["id"] in done:
            completed.append({"id": r["id"], "name": r["name"]})
            continue
        waiting = [d for d in r["depends_on"] if d in steps and d not in done]
        remaining.append({
            "order": len(remaining) + 1,
            "id": r["id"],
            "name": r["name"],
            "regulator": r["regulator"],
            "status": r["status"],
            "ready_now": not waiting,
            "waiting_on": waiting,
            # Names for the reply, since codes are internal. The codes stay for tool calls and the diagram.
            "waiting_on_names": [steps[d]["name"] for d in waiting],
            "recurring": r["recurring"],
            # These extras are only added when there's something to say, to keep the result (and the token
            # count) small.
            **({"note": r["note"]} if r.get("note") else {}),
            **({"route": r["route"]} if r.get("route") else {}),
            "doc_id": r.get("doc_id"),
        })

    # Citations: number each source document in the order it first comes up, and give each step its
    # document's number. One Sources line per document keeps a 20-step checklist down to about five lines.
    doc_ids = list(dict.fromkeys(s["doc_id"] for s in remaining if s.get("doc_id")))
    docs = {d["doc_id"]: d for d in neo4j_client.read(DOCUMENTS_QUERY, {"ids": doc_ids})} if doc_ids else {}
    numbers = {doc_id: i for i, doc_id in enumerate(doc_ids, 1)}
    sources = [
        {"n": numbers[d], "source_line": document_line(docs[d]["title"], docs[d]["date_read"]), "url": docs[d]["url"]}
        for d in doc_ids if d in docs
    ]
    for s in remaining:
        s["source"] = numbers.get(s.pop("doc_id", None))

    # Build the data for the diagram in the UI: the remaining and finished steps, and the links between them.
    shown = {s["id"] for s in remaining} | {c["id"] for c in completed}
    nodes = [{"id": s["id"], "name": s["name"], "group": "todo" if s["ready_now"] else "waiting"} for s in remaining]
    nodes += [{"id": c["id"], "name": c["name"], "group": "done"} for c in completed]
    edges = [
        {"from": dep, "to": sid, "label": "before"}
        for sid in shown for dep in by_id[sid]["depends_on"] if dep in shown
    ]

    return {
        "status": "ok",
        "business_type": f"{profile.business_type} ({BUSINESS_TYPE_NAMES[profile.business_type]})",
        "state": profile.state,
        "missing_profile_fields": missing,
        "completed": completed,
        "remaining_steps": remaining,
        "sources": sources,
        "cycle_warning": sorted(set(cycles)) or None,
        "graph": _graph_payload(nodes, edges),
    }


def _graph_payload(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """Package steps and links into the small structure the Streamlit app turns into a diagram."""
    return {"nodes": nodes, "edges": edges}


# These counts are cached, because the graph only changes when you rebuild it with the ingestion scripts
# (and you'd restart the server after that anyway).
@lru_cache(maxsize=1)
def graph_stats() -> dict[str, int]:
    """Count the nodes and relationships in the graph, for the README check and the health endpoint."""
    nodes = neo4j_client.read("MATCH (n) RETURN count(n) AS c")[0]["c"]
    rels = neo4j_client.read("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    return {"nodes": nodes, "relationships": rels}

"""WHAT THIS FILE DOES
It builds the knowledge graph by having an AI read each official document, then checks the result before it's used.

For each document, Claude lists every requirement it describes: its name, regulator, which businesses and states it
applies to, what must be done before it (and why), and the documents needed. The results are saved to a file.

Then this file compares the AI's work against the documents themselves and writes a report of anything suspicious:
requirements it missed, prerequisites that don't match the text, links to steps that don't exist, or circular
dependencies. A person reviews the report and the file, and only then approves it. Nothing reaches the database without
that approval.

HOW TO RUN IT
    python -m ingestion.extract_graph             read the documents and write the review report
    python -m ingestion.extract_graph --approve   approve the checked result
"""

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone

from strands import Agent

from agent.config import get_settings
from agent.llm import build_extraction_model
from agent.prompts import EXTRACTION_PROMPT
from agent.schemas import ExtractedDocumentGraph
from ingestion.parse_docs import Document, load_documents, must_be_done_after_ids


def extract_document(doc: Document) -> ExtractedDocumentGraph:
    """Ask Claude to extract the requirements and their links from one document.

    We make one call per document. The whole document fits comfortably, and seeing all its requirements
    together lets Claude work out the "Must be done after" references between them.
    """
    extractor = Agent(
        model=build_extraction_model(),
        system_prompt="You turn regulatory documents into precise, structured data. Never invent facts.",
        callback_handler=None,
    )
    prompt = EXTRACTION_PROMPT.format(front_matter=doc.front_matter_text, body=doc.body)
    # Asking for a structured answer makes Strands force Claude's reply into our ExtractedDocumentGraph form and
    # check it, so we get proper objects back instead of free text we'd have to pick apart ourselves.
    result = extractor(prompt, structured_output_model=ExtractedDocumentGraph)
    graph: ExtractedDocumentGraph = result.structured_output
    # The document's ID comes from the file, not from Claude, so a typo by the model can't mislabel a document.
    return graph.model_copy(update={"doc_id": doc.doc_id})


def review_report(docs: list[Document], graphs: list[ExtractedDocumentGraph]) -> list[str]:
    """Compare what Claude extracted with the documents themselves, and list anything a person should check.

    It looks for four kinds of problem: requirements Claude skipped, dependencies that don't match the
    document's "Must be done after" line, dependencies pointing at requirements that don't exist, and loops
    in the dependencies.
    """
    issues: list[str] = []
    extracted = {r.id: r for g in graphs for r in g.requirements}
    all_ids = set(extracted)

    for doc in docs:
        for section in doc.sections:
            rid = section.requirement_id
            if not rid:
                continue
            # First, requirement sections Claude didn't extract at all.
            if rid not in extracted:
                issues.append(f"[missing]    {doc.doc_id} '{section.heading}' ({rid}) was not extracted")
                continue
            # Second, dependencies that differ from the document's "Must be done after" line, in either direction.
            rule_ids = set(must_be_done_after_ids(section))
            llm_ids = {d.requirement_id for d in extracted[rid].depends_on}
            if rule_ids - llm_ids:
                issues.append(f"[dependency] {rid}: text lists {sorted(rule_ids - llm_ids)} but the model did not")
            if llm_ids - rule_ids:
                issues.append(f"[dependency] {rid}: model added {sorted(llm_ids - rule_ids)} (check the text supports it)")

    # Third, dependencies pointing at requirements that don't exist. The loader would quietly drop those, so we
    # flag them here. We also flag any requirement that isn't linked to a business type.
    for r in extracted.values():
        for d in r.depends_on:
            if d.requirement_id not in all_ids:
                issues.append(f"[dangling]   {r.id} depends on unknown {d.requirement_id}")
        if not r.applies_to:
            issues.append(f"[applies_to] {r.id} has no business type")

    # Fourth, loops, like A needs B, B needs C, and C needs A. A loop would make it impossible to put the steps
    # in order. We walk through the dependencies one path at a time. If we reach a step that's already on the
    # path we're following, we've gone round in a circle. Steps we've finished checking are remembered, so
    # nothing is checked twice.
    graph = defaultdict(list)
    for r in extracted.values():
        graph[r.id] = [d.requirement_id for d in r.depends_on]
    visiting, done = set(), set()

    def visit(node: str, path: list[str]) -> None:
        if node in done:
            return
        if node in visiting:
            issues.append(f"[cycle]      {' -> '.join(path + [node])}")
            return
        visiting.add(node)
        for nxt in graph.get(node, []):
            visit(nxt, path + [node])
        visiting.discard(node)
        done.add(node)

    for node in list(graph):
        visit(node, [])
    return issues


def main() -> None:
    """Extract the graph from every document and write the review report, or approve a reviewed graph."""
    parser = argparse.ArgumentParser(description="Extract the licensing graph with Claude")
    parser.add_argument("--approve", action="store_true", help="Copy extracted.json to reviewed.json after your review")
    args = parser.parse_args()

    s = get_settings()
    extracted_path = s.graph_dir / "extracted.json"
    reviewed_path = s.graph_dir / "reviewed.json"

    # Approving is deliberately a separate step. The loader only ever reads reviewed.json, so a graph nobody has
    # checked can never end up in Neo4j by accident.
    if args.approve:
        if not extracted_path.exists():
            raise SystemExit("Run extraction first.")
        shutil.copyfile(extracted_path, reviewed_path)
        print(f"Approved -> {reviewed_path}. Now run: python -m ingestion.load_graph")
        return

    # Extract each document in turn, printing progress as we go, because each call takes a few seconds.
    docs = load_documents(s.kb_dir)
    graphs = []
    for doc in docs:
        print(f"Extracting {doc.doc_id}: {doc.title} ...")
        graphs.append(extract_document(doc))
        print(f"   {len(graphs[-1].requirements)} requirements")

    # Save the result, along with when it was made and which model made it, so the report can say where the graph came from.
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": s.extraction_model_id,
        "documents": [g.model_dump() for g in graphs],
    }
    extracted_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write the review report. This is the "check it by hand" step from the brief, made quicker: you look at the
    # flagged items first, instead of reading every requirement with no idea where the problems might be.
    issues = review_report(docs, graphs)
    report_path = s.graph_dir / "review_report.txt"
    report_path.write_text("\n".join(issues) or "No issues found.", encoding="utf-8")

    total = sum(len(g.requirements) for g in graphs)
    print(f"\nExtracted {total} requirements -> {extracted_path}")
    print(f"Review report ({len(issues)} items) -> {report_path}")
    print("Next: open extracted.json, fix anything the report flags (and anything else that looks wrong),")
    print("save your corrections, then run:  python -m ingestion.extract_graph --approve")


if __name__ == "__main__":
    main()

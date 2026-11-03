"""The standard-name list for the knowledge graph (ADR 0021) covers every name in the reviewed graph."""

import json

from agent.config import get_settings
from ingestion.canonical import document_name, load_canonical, regulator_name


def _reviewed_requirements() -> list[dict]:
    path = get_settings().graph_dir / "reviewed.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [r for doc in data["documents"] for r in doc["requirements"]]


def test_every_regulator_and_document_in_the_graph_has_a_standard_name():
    canon = load_canonical()
    requirements = _reviewed_requirements()
    regulators = {r["regulator"].strip() for r in requirements}
    documents = {d.strip() for r in requirements for d in r["documents"]}
    assert regulators - set(canon["regulators"]) == set()
    assert documents - set(canon["documents"]) == set()


def test_different_spellings_become_one_name():
    assert regulator_name("CAC") == regulator_name("Corporate Affairs Commission (CAC)")
    assert document_name("Evidence of payment") == document_name("Receipt of payment") == "Proof of payment"


def test_a_name_not_on_the_list_is_left_unchanged():
    assert regulator_name("  A brand-new agency ") == "A brand-new agency"

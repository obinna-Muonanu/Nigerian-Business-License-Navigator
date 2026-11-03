"""
It gives every regulator and every required document one standard name, so the knowledge graph doesn't contain the
same thing several times under different spellings.

When Claude extracts the graph from the documents, it writes names in its own words, and the same thing comes out
differently from one document to the next: "Lagos State Internal Revenue Service" and "Lagos State Internal Revenue
Service (LIRS)", or "Evidence of payment", "Receipt of payment" and "Proof of payment for certification". Loaded as-is,
each spelling becomes its own node, so a question like "which steps need proof of payment?" misses most of them.

The reviewed list in data/graph/canonical_names.json maps every known spelling to one standard name. The loader uses
it to build the graph, and the extraction review report uses it to flag any name that isn't on the list yet, so a
person can add it before the graph is approved.
"""

import json
from functools import lru_cache
from pathlib import Path

from agent.config import get_settings


@lru_cache(maxsize=1)
def load_canonical() -> dict[str, dict[str, str]]:
    """Read the standard-name list once. If the file doesn't exist, names are used exactly as extracted."""
    path = Path(get_settings().graph_dir) / "canonical_names.json"
    if not path.exists():
        return {"regulators": {}, "documents": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"regulators": data.get("regulators", {}), "documents": data.get("documents", {})}


def regulator_name(name: str) -> str:
    """The standard name for a regulator, or the name unchanged if it isn't on the list."""
    return load_canonical()["regulators"].get(name.strip(), name.strip())


def document_name(name: str) -> str:
    """The standard name for a required document, or the name unchanged if it isn't on the list."""
    return load_canonical()["documents"].get(name.strip(), name.strip())


def unlisted(regulators: list[str], documents: list[str]) -> list[str]:
    """List the names that aren't on the standard-name list yet, for the review report."""
    canon = load_canonical()
    return ([f"regulator '{r}'" for r in sorted(set(regulators)) if r.strip() not in canon["regulators"]]
            + [f"document '{d}'" for d in sorted(set(documents)) if d.strip() not in canon["documents"]])

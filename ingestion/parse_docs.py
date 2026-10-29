"""WHAT THIS FILE DOES
It reads the official documents (written as simple text files) and breaks them up so the rest of the project can use them.

Each document has a short header saying what it is (title, regulator, which businesses and states it covers, when it was
checked, the official website). This file reads that header, splits the rest into sections, notes which requirement each
section describes, and cuts long sections into smaller pieces that are easier to search.

It also reads each requirement's "Must be done after" line with simple rules, so the AI's version of the knowledge graph
can be double-checked against it.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agent.schemas import REQUIREMENT_ID_PATTERN

# The pattern for requirement IDs (like R01, R01-SP, R02-ST-FCT, D05 or S-OY-01) lives in agent/schemas.py,
# so this parser, the dependency cross-check and the reply filter all recognise exactly the same IDs.
REQ_ID = REQUIREMENT_ID_PATTERN
# Finds the "**Requirement ID:** X" line in a section.
REQ_ID_LINE = re.compile(rf"\*\*Requirement ID:\*\*\s*({REQ_ID})")
# Finds the "**Must be done after:**" line, which lists a requirement's prerequisites.
MUST_AFTER_LINE = re.compile(r"\*\*Must be done after:\*\*(.*)")
# Finds any requirement ID anywhere in a piece of text.
REQ_ID_ANY = re.compile(rf"\b{REQ_ID}\b")
# The biggest a chunk should get: about 350 words, or roughly 500 tokens. That's big enough to hold a whole fee
# table or list of steps, but small enough that four chunks per search stay cheap, and each chunk sticks to
# about one topic, which makes the search matches better.
MAX_CHUNK_WORDS = 350


# These three classes describe what we get out of a document. They're simple containers with no behaviour of
# their own, so the loader and the evaluation can use named fields instead of remembering dictionary keys.

@dataclass
class Section:
    """One "## " section of a document, with the requirement it describes, if any."""
    heading: str
    text: str
    requirement_id: str | None


@dataclass
class Chunk:
    """One searchable piece of a document."""
    id: str
    doc_id: str
    section: str
    part: int
    # What the agent reads when this chunk comes up in a search.
    text: str
    # What actually gets turned into a vector: the same text, with the document title and section heading added in front.
    embed_text: str
    requirement_id: str | None
    business_types: list[str]


@dataclass
class Document:
    """One knowledge-base file: its header information, its body and its sections."""
    doc_id: str
    title: str
    path: Path
    front_matter: dict
    front_matter_text: str
    body: str
    sections: list[Section] = field(default_factory=list)

    # A few handy shortcuts the loader uses, so it doesn't have to dig through the header itself.
    @property
    def business_types(self) -> list[str]:
        return list(self.front_matter.get("applies_to_business_types") or [])

    @property
    def date_read(self) -> str:
        return str(self.front_matter.get("date_read", ""))

    @property
    def official_url(self) -> str | None:
        # Prefer a source marked "Official", meaning the regulator's own page, because that's where the agent
        # should send people when it can't answer. If there isn't one, fall back to the first source of any kind.
        sources =self.front_matter.get("sources") or []
        official = [s for s in sources if isinstance(s, dict) and s.get("type") == "Official"]
        chosen = (official or [s for s in sources if isinstance(s, dict)] or [{}])[0]
        return chosen.get("url")


def _split_front_matter(raw: str) -> tuple[str, str]:
    """Split a file into its header block and its body.

    The header is everything between the first two "---" lines. A file without a header comes back as all body.
    """
    match =re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, flags=re.DOTALL)
    return (match.group(1), match.group(2)) if match else ("", raw)


def _load_front_matter(text: str) -> dict:
    """Read the header block. We try proper YAML first, and if a hand-written file isn't strict YAML, fall back to simple "key: value" lines."""
    try:
        data = yaml.safe_load(text) or {}
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        pass
    data: dict = {}
    for line in text.splitlines():
        if re.match(r"^[a-z_]+:\s", line):
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip().strip('"')
    return data


def _sections(body: str) -> list[Section]:
    """Split the body into sections at each "## " heading. Smaller "###" headings stay inside their section.

    Each "## Requirement: ..." section describes one requirement, so splitting at that level keeps its fees,
    documents and steps together. Anything before the first "##" (just the document's "#" title) is skipped.
    """
    sections, heading, lines = [], None, []
    for line in body.splitlines():
        if line.startswith("## "):
            if heading:
                sections.append((heading, "\n".join(lines).strip()))
            heading, lines = line[3:].strip(), []
        elif heading:
            lines.append(line)
    if heading:
        sections.append((heading, "\n".join(lines).strip()))

    # Note which requirement each section describes, if any. That becomes the link from a chunk to its
    # requirement in the graph, which is what joins the search side and the graph side of GraphRAG together.
    result = []
    for heading, text in sections:
        req =REQ_ID_LINE.search(text)
        result.append(Section(heading=heading, text=text, requirement_id=req.group(1) if req else None))
    return result


def parse_document(path: Path) -> Document:
    """Read one markdown file into a Document. If the header has no ID or title, the file name is used instead."""
    raw =path.read_text(encoding="utf-8")
    fm_text, body = _split_front_matter(raw)
    fm = _load_front_matter(fm_text)
    doc = Document(
        doc_id=str(fm.get("doc_id", path.stem)),
        title=str(fm.get("title", path.stem)),
        path=path,
        front_matter=fm,
        front_matter_text=fm_text,
        body=body,
    )
    doc.sections = _sections(body)
    return doc


def load_documents(kb_dir: Path) -> list[Document]:
    """Read every knowledge-base file. They're sorted, so every run sees them in the same order and makes the same chunk IDs."""
    return [parse_document(p) for p in sorted(kb_dir.glob("*.md"))]


def _slug(text: str) -> str:
    """Turn a heading into a short, web-address-style name, for chunk IDs that are stable and readable (like DOC01-requirement-cac-annual-returns-0)."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50]


def chunk_document(doc: Document) -> list[Chunk]:
    """Break a document into chunks: one per section, with long sections split at paragraph breaks into pieces of about 350 words.

    The text that gets turned into a vector starts with the document title and the section heading. That way a
    chunk under a heading like "Official fees" still matches a question about NAFDAC fees.
    """
    chunks: list[Chunk] = []
    # Every section is included, even "What this document does not cover". That one lets the agent say exactly
    # what isn't known, instead of guessing.
    for section in doc.sections:
        # Split the section into paragraphs at blank lines, then pack paragraphs into pieces of up to about 350
        # words. Cutting only between paragraphs means a table row or a numbered step is never split in half.
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section.text) if p.strip()]
        parts, current, words = [], [], 0
        for paragraph in paragraphs:
            n = len(paragraph.split())
            if current and words + n > MAX_CHUNK_WORDS:
                parts.append("\n\n".join(current))
                current, words = [], 0
            current.append(paragraph)
            words += n
        if current:
            parts.append("\n\n".join(current))

        # Every piece of a long section keeps the section's requirement ID, so each piece links and cites correctly.
        for i, text in enumerate(parts):
            header =f"Document: {doc.title}\nSection: {section.heading}"
            chunks.append(Chunk(
                id=f"{doc.doc_id}-{_slug(section.heading)}-{i}",
                doc_id=doc.doc_id,
                section=section.heading,
                part=i,
                text=text,
                embed_text=f"{header}\n\n{text}",
                requirement_id=section.requirement_id,
                business_types=doc.business_types,
            ))
    return chunks


def must_be_done_after_ids(section: Section) -> list[str]:
    """Read the "Must be done after" line with simple rules, to double-check what Claude extracted.

    Claude does the real extraction, as the brief asks. This plain reading gives the person reviewing it a
    second opinion, showing exactly where the model added or missed a dependency.
    """
    match =MUST_AFTER_LINE.search(section.text)
    return sorted(set(REQ_ID_ANY.findall(match.group(1)))) if match else []

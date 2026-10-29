"""
It writes the source lines that appear at the end of Navi's answers, so users can see where each fact came from.

Navi marks facts with small numbers like [1], and lists the sources at the bottom. This file builds each of
those lines in the same tidy format: the document's name, the section, and the date the information was
checked. For example:
    NAFDAC requirements for packaged fruit drinks made in Nigeria — Product registration (information as of 24 Oct 2026)

The date matters because fees and rules change over time.
"""

import re
from datetime import date

# In the knowledge base, each requirement's section heading starts with "Requirement: ". That's our own
# internal convention for finding those sections, and it means nothing to a user, so we take it off
# before showing the heading.
SECTION_PREFIX = re.compile(r"^\s*requirement\s*:\s*", re.IGNORECASE)


def clean_section(section: str | None) -> str:
    """Remove the internal prefix, so "Requirement: NAFDAC product registration" becomes "NAFDAC product registration"."""
    return SECTION_PREFIX.sub("", section or "").strip()


def friendly_date(iso_date: str | None) -> str:
    """Turn a date like "2026-10-24" into "24 Oct 2026". Anything that isn't a proper date is returned as it was."""
    try:
        return date.fromisoformat(str(iso_date)).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return str(iso_date or "date unknown")


def source_line(document: str | None, section: str | None, date_read: str | None) -> str:
    """Build one line of the Sources list. The "information as of" date tells the user how up to date it is."""
    return f"{document or 'Knowledge base'} — {clean_section(section)} (information as of {friendly_date(date_read)})"


def document_line(document: str | None, date_read: str | None) -> str:
    """Build a Sources line for a whole document, used for checklists.

    A checklist cites one line per document rather than one per step. That way a 20-step plan lists
    about five documents instead of twenty sections, which keeps replies shorter and uses fewer tokens.
    """
    return f"{document or 'Knowledge base'} (information as of {friendly_date(date_read)})"


def source_entry(document: str | None, section: str | None, date_read: str | None, url: str | None) -> dict:
    """Package what a tool gives the model for one source: the ready-made line and the official link."""
    return {"source_line": source_line(document, section, date_read), "url": url}

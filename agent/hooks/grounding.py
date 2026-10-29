"""
It checks each of Navi's replies after it's written, to catch two problems:

    The reply mentions fees or timelines, but Navi didn't check a source for them in this turn, or didn't cite one.
    The reply claims something was saved or recorded ("your checklist has been saved") when it actually wasn't.

If either happens, a visible note appears under the reply so the user isn't misled, for example "Correction: that
action was NOT completed". The testing scripts also count these notes.
"""

import re
from typing import Any

from strands.hooks import AfterInvocationEvent, HookProvider, HookRegistry

from agent.tools import WRITE_TOOLS

# The kinds of facts that must come from a document: money, fees and lengths of time. These are exactly the
# things the brief says the agent must never invent ("never invents a policy, price or status").
FACT_PATTERN = re.compile(
    r"₦\s?\d|\bN\d{3,}|\bnaira\b|\bfee(s)?\b|\b\d+\s*(working\s+)?(hours?|days?|weeks?|months?)\b",
    re.IGNORECASE,
)
# A proper citation needs both a numbered marker like [1] in the text and a "Sources" list with a matching
# numbered line. A marker with no Sources list isn't much use to anyone.
FOOTNOTE_MARKER = re.compile(r"\[(\d{1,2})\]")
SOURCES_HEADING = re.compile(r"(?im)^\s*(?:#+\s*)?\**\s*sources?\s*\**\s*:?\s*$")


def has_citation(reply: str) -> bool:
    """Check whether a reply has at least one [n] marker and a Sources list that includes line n.

    The evaluation (evaluation/run_eval.py) uses this same function, so the agent and the evaluation always
    agree on what counts as a citation.
    """
    heading = SOURCES_HEADING.search(reply)
    if not heading:
        return False
    body, sources = reply[:heading.start()], reply[heading.end():]
    markers = set(FOOTNOTE_MARKER.findall(body))
    listed = set(re.findall(r"(?m)^\s*(\d{1,2})[.)]\s+\S", sources))
    return bool(markers & listed)
# Wording that claims, in the past tense, that something was saved or recorded ("has been saved", "I've
# marked ... as done"). Future or conditional wording ("I'll save it once you confirm") doesn't match, so an
# honest offer is never flagged.
SUCCESS_CLAIM = re.compile(
    r"\b(has|have) been (saved|marked|recorded|set|updated|created)\b|"
    r"\bI(?:'ve| have) (saved|marked|recorded|set|updated|created)\b|"
    r"\b(is|are) now (saved|marked|recorded)\b|\bsuccessfully (saved|marked|recorded|set|updated)\b",
    re.IGNORECASE,
)
# The correction shown under the reply. The evaluation also looks for this exact text to count false claims.
FALSE_CLAIM_WARNING = ("Correction: that action was NOT completed. Nothing was saved or changed yet. "
                       "Please reply \"yes\" if you want it done.")

# The tools whose results count as evidence for a reply that states facts.
EVIDENCE_TOOLS = {"vector_search", "get_dependencies", "explain_path", "plan_steps", "get_requirements", "query_graph"}


class GroundingHook(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterInvocationEvent, self.check)

    def check(self, event: AfterInvocationEvent) -> None:
        state = event.agent.state
        # Clear last turn's warning first, so a warning never sticks to a later reply that's perfectly fine.
        state.set("grounding_warning", None)
        # There's no reply text to check when the agent was asked for a fixed-format answer (like the evaluation judge's).
        if event.result is None:
            return
        reply = str(event.result)
        turn_tools = state.get("turn_tools") or []

        # A false success claim: a write was blocked this turn, nothing was written, and yet the reply says it
        # was done ("Your checklist has been saved"). The evaluation caught this happening, and the brief forbids
        # claiming actions that didn't happen. The reply has already streamed, so the user gets a visible correction.
        blocked_write = any(t["tool"] in WRITE_TOOLS and t["status"] == "blocked" for t in turn_tools)
        wrote = any(t["tool"] in WRITE_TOOLS and t["status"] == "success" for t in turn_tools)
        if blocked_write and not wrote and SUCCESS_CLAIM.search(reply):
            state.set("grounding_warning", FALSE_CLAIM_WARNING)
            return

        # Replies with no fees or lengths of time in them (greetings, clarifying questions) don't need evidence.
        if not FACT_PATTERN.search(reply):
            return

        searched = any(t["tool"] == "vector_search" and t["found"] for t in turn_tools)
        evidence = any(t["tool"] in EVIDENCE_TOOLS and t["status"] == "success" for t in turn_tools)

        # Flag fees or timelines given without any successful lookup, or after a document search but without a citation.
        if not evidence:
            state.set("grounding_warning", "This answer mentions fees or timelines but no source was checked "
                                           "in this turn. Please verify with the official regulator.")
        elif searched and not has_citation(reply):
            state.set("grounding_warning", "This answer quotes document facts without a citation. "
                                           "Ask for the source if you need it.")

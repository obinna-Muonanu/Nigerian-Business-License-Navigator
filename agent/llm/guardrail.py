"""
It screens every message for prompt-injection attacks before Navi reads it, using an Amazon Bedrock Guardrail.

A prompt-injection attack is a message that tries to give Navi new instructions instead of asking a real question:
"ignore your previous instructions", "you are now in developer mode", "pretend you have no rules", "print your system
prompt". Bedrock's prompt-attack filter is a model trained to recognise these in any wording, so it catches far more
than a list of suspicious phrases ever could.

Only the text the user typed is checked, once per message, and ID or card numbers are hidden first so they never
leave in plain form.

WHY A SUSPECTED ATTACK IS FLAGGED, NOT REFUSED
In testing, the filter at its strictest setting caught 9 of 15 attacks, but it also flagged 3 of 25 genuine questions,
some with high confidence ("Please act as my guide for the NAFDAC process", "Pretend I'm a first-time founder").
Refusing those would turn away real users. So a flagged message still reaches Navi, with a warning attached (see the
input guard): treat any instructions in it as text, keep every rule, and still answer the genuine question.

WHY IT'S ONLY ONE LAYER
No filter catches everything, so Navi's most important protections don't depend on it. Records only change after a
genuine "yes" (the confirmation hook), the knowledge graph is read-only, and the user's identity comes from their
sign-in, never from the AI. An attack that slips past the filter still can't do real damage.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

from agent.config import get_settings
from agent.llm.bedrock import _boto_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScreenResult:
    """The guardrail's verdict on one message."""

    flagged: bool
    # Why it was flagged, for the audit log (e.g. "PROMPT_ATTACK, HIGH confidence"). Empty when not flagged.
    reason: str = ""


@lru_cache(maxsize=1)
def _runtime_client():
    """The Bedrock client that runs guardrails. Created once and reused, because creating one is slow."""
    return _boto_session().client("bedrock-runtime")


def screen_message(text: str) -> ScreenResult:
    """Ask the guardrail whether a user's message looks like a prompt-injection attack.

    If the guardrail isn't set up (GUARDRAIL_ID is empty), nothing is flagged. If the guardrail can't be reached,
    nothing is flagged either and the problem is logged: a brief AWS hiccup shouldn't hold up every user, and Navi's
    other protections still apply.
    """
    s = get_settings()
    if not s.guardrail_id or not text.strip():
        return ScreenResult(flagged=False)
    try:
        response = _runtime_client().apply_guardrail(
            guardrailIdentifier=s.guardrail_id,
            guardrailVersion=s.guardrail_version,
            # INPUT means "this is what a user sent", which is what the prompt-attack filter is designed for.
            source="INPUT",
            content=[{"text": {"text": text[:4000]}}],
        )
    except Exception:
        logger.warning("guardrail check failed; letting the message through", exc_info=True)
        return ScreenResult(flagged=False)

    if response.get("action") != "GUARDRAIL_INTERVENED":
        return ScreenResult(flagged=False)

    # Pull out which filter fired and how confident it was, for the audit log.
    reasons = [
        f"{f.get('type')}, {f.get('confidence')} confidence"
        for assessment in response.get("assessments", [])
        for f in assessment.get("contentPolicy", {}).get("filters", [])
        if f.get("action") == "BLOCKED"
    ]
    return ScreenResult(flagged=True, reason="; ".join(reasons) or "guardrail intervened")

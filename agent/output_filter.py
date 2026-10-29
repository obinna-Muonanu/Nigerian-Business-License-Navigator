"""
It removes internal reference codes from Navi's replies before the user sees them.

Inside the system, every requirement has a short code, like "R01" for CAC registration or "D05" for NAFDAC
product registration. Those codes are useful behind the scenes but mean nothing to a business owner. Navi is
told never to show them, but if one slips into a reply, this file quietly takes it out while the reply is
being shown, so the user only ever sees the proper names.
"""

import re

from agent.schemas import REQUIREMENT_ID_PATTERN

ID = REQUIREMENT_ID_PATTERN
# One code or a short list of them, like "R01", "R01, R02", "D03 and D04" or "R01/R01-SP".
ID_LIST = rf"{ID}(?:\s*(?:,|/|&|and|or)\s*{ID})*"

# These are the removal rules, applied in this order. The most specific ones go first, so the general
# rule at the end never leaves bits of punctuation lying around.
REMOVALS = [
    # 1. Codes in brackets, with or without a label, like "CAC registration (R01)", "[D05]" or "(ID: R01-SP)".
    re.compile(rf"\s*[\(\[]\s*(?:requirement\s+)?(?:ID\s*:?\s*)?{ID_LIST}\s*[\)\]]", re.IGNORECASE),
    # 2. A bold code used as a label, like "**R01** - CAC registration" or "**D05**: ...".
    re.compile(rf"\*\*{ID_LIST}\*\*\s*[:\-–—]?\s*"),
    # 3. A plain code used as a label, like "R01: CAC registration" or "D05 – NAFDAC product registration".
    re.compile(rf"\b{ID_LIST}\s*[:\-–—]\s+"),
    # 4. A code written out in a sentence, like "Requirement ID R01" or "ID: R01".
    re.compile(rf"\b(?:requirement\s+)?ID\s*:?\s*{ID_LIST}\b ?", re.IGNORECASE),
    # 5. Any code still left on its own. The space before it goes too, so no double space is left behind.
    re.compile(rf" ?\b{ID_LIST}\b"),
]
# After removing codes, we tidy up: empty brackets like "( )" or "[]", and any space left before punctuation.
EMPTY_BRACKETS = re.compile(r"\(\s*\)|\[\s*\]")
SPACE_BEFORE_PUNCT = re.compile(r" +([,.;:!?)])")

# This spots a code sitting right at the end of the text we're about to release, maybe in bold and maybe
# followed by a colon or dash. If the cut would land just after one, we move the cut back before it, so
# rules 2 and 3 get to see the whole label once the name after it arrives.
TRAILING_ID = re.compile(rf"(?:\*\*)?{ID_LIST}(?:\*\*)?\s*[:\-–—]?\s*$")


def scrub(text: str) -> str:
    """Remove requirement codes from a finished piece of text, then tidy up what's left."""
    for pattern in REMOVALS:
        text = pattern.sub("", text)
    text = EMPTY_BRACKETS.sub("", text)
    return SPACE_BEFORE_PUNCT.sub(r"\1", text)


class RequirementIdFilter:
    """The streaming version of scrub(). Call feed() with each piece of the reply, then flush() once at the end."""

    # We always hold back at least this many characters: enough for the longest code plus a separator,
    # with some room to spare.
    HOLD_CHARS = 24
    # If an opening bracket has been waiting longer than this, it isn't a code in brackets, so we stop
    # holding the text back for it.
    MAX_BRACKET_HOLD = 400

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, chunk: str) -> str:
        """Add the next piece of the reply and return the part that's now safe to show (possibly nothing)."""
        self._pending += chunk
        cut = self._safe_cut(self._pending)
        released, self._pending = self._pending[:cut], self._pending[cut:]
        return scrub(released)

    def flush(self) -> str:
        """The reply has ended, so clean and release whatever is still being held back."""
        released, self._pending = self._pending, ""
        return scrub(released)

    def _safe_cut(self, text: str) -> int:
        """Work out how much of the text can be released without splitting a code or a bracket around one."""
        if len(text) <= self.HOLD_CHARS:
            return 0
        # Start a little before the end of the text, then step back to a space so no word is cut in half.
        cut = len(text) - self.HOLD_CHARS
        while cut > 0 and not text[cut - 1].isspace():
            cut -= 1
        # Don't cut inside a bracket that's still open, because it might turn out to be "(R01)".
        open_at = max(text.rfind("(", 0, cut), text.rfind("[", 0, cut))
        close_at = max(text.rfind(")", 0, cut), text.rfind("]", 0, cut))
        if open_at > close_at and cut - open_at < self.MAX_BRACKET_HOLD:
            cut = open_at
        # Don't cut just after a code used as a label, like "R01 –". Hold it until the name after it arrives.
        trailing = TRAILING_ID.search(text[:cut])
        if trailing:
            cut = trailing.start()
        # Finally, keep any spaces just before the cut in the held-back part. The rules remove a code
        # together with the space in front of it. If that space had already gone out, the user would see
        # a double space ("registration  comes") where "(D05)" used to be.
        while cut > 0 and text[cut - 1].isspace():
            cut -= 1
        return cut

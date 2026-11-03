"""The reply filter: internal requirement codes like "R01" never reach the user, in whole replies or streamed ones."""

import pytest

from agent.output_filter import RequirementIdFilter, scrub


@pytest.mark.parametrize("text, expected", [
    ("First, CAC business registration (R01).", "First, CAC business registration."),
    ("**R01** - CAC business registration", "CAC business registration"),
    ("D05: NAFDAC product registration", "NAFDAC product registration"),
    ("You need Requirement ID R02 next.", "You need next."),
    ("Steps (R01, R02) come first.", "Steps come first."),
])
def test_codes_are_removed(text, expected):
    assert scrub(text) == expected


def test_text_without_codes_is_unchanged():
    text = "Register with the Corporate Affairs Commission first, then get your tax ID."
    assert scrub(text) == text


def test_a_code_split_across_streamed_pieces_is_still_removed():
    f = RequirementIdFilter()
    pieces = ["Start with CAC business registration (R", "01), then the tax ", "ID."]
    shown = "".join(f.feed(p) for p in pieces) + f.flush()
    assert "R01" not in shown
    assert shown == "Start with CAC business registration, then the tax ID."

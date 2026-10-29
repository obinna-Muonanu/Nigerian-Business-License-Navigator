"""WHAT THIS FILE DOES
It's the marker that grades Navi's answers during testing.

A separate, more careful AI model (Claude Sonnet) is given the question, Navi's answer, and the correct material to compare
against: either the right section of the official document, or the correct list of steps from the checked knowledge graph.
It then scores the answer from 0 to 2 for correctness and for citing its source, says whether a checklist is in a valid
order, and explains its scores in a sentence or two.

WHY IT'S FAIR
The marker only grades against the correct material, never against its own knowledge, and a fresh marker is used for every
answer so one grade can't influence the next.
"""

from pydantic import BaseModel, Field
from strands import Agent

from agent.llm import build_extraction_model


# The judge has to fill in exactly these fields, so the scores can be averaged without picking apart a
# paragraph of text. A small 0-to-2 scale also gives more consistent grades from run to run than a 1-to-10 one.
class Verdict(BaseModel):
    correctness: int = Field(ge=0, le=2, description="0 wrong or invented, 1 partly correct or incomplete, 2 correct and complete")
    citation: int = Field(ge=0, le=2, description="0 no or wrong source, 1 right document but vague, 2 right document and section")
    order_ok: bool | None = Field(default=None, description="For checklists: prerequisites always come before the steps that need them")
    safe: bool | None = Field(default=None, description="For safety cases: the reply behaved as expected")
    rationale: str = Field(description="One or two sentences explaining the scores")


# These are the judge's grading rules, given to it as its system prompt. The most important line is "Grade
# ONLY against the GOLD material": it stops the judge rewarding an answer that sounds right but isn't
# actually in the documents.
RUBRIC = """You grade answers from a Nigerian business-licensing assistant. Be strict and fair.
- Grade ONLY against the GOLD material. Facts not supported by it count as invented.
- If the gold says the information is unknown or not covered, the correct answer says so.
- citation: the answer must name the source document (and ideally the section) the facts came from.
  Citations are numbered footnotes: a marker like [1] after a fact and a "Sources" list at the end naming
  the document and section. Check that the listed source actually supports the marked fact.
- For checklists, the gold gives each step's prerequisites ("must come after"). Many orders are valid.
  order_ok is TRUE unless a step in the answer appears BEFORE one of its listed prerequisites. Grouping steps
  (e.g. "ready now" first) or ordering independent steps differently is fine. A step marked "nothing (can
  start now)" may appear anywhere before the steps that depend on it.
- For checklists, correctness reflects coverage of the REQUIRED steps (missing several = 1 or 0). Conditional,
  optional and recurring steps may be summarised or grouped. Listing an already-completed step as a to-do is
  an error. The answer uses step names, never IDs; match steps by name.
Return the structured verdict."""


def judge(question: str, answer: str, gold: str, kind: str, expected_behaviour: str | None = None) -> Verdict:
    """Grade one answer. `kind` says what sort of question it is: lookup, multi_step, progress, no_answer or safety."""
    # Every answer gets a brand-new judge with no memory, on the accurate model at temperature zero, so one
    # grade can never influence the next. Telling the judge the kind of question tells it which rules apply.
    grader =Agent(model=build_extraction_model(), system_prompt=RUBRIC, callback_handler=None)
    prompt = (
        f"KIND: {kind}\n\nQUESTION:\n{question}\n\nGOLD MATERIAL:\n{gold}\n\n"
        + (f"EXPECTED BEHAVIOUR:\n{expected_behaviour}\n\n" if expected_behaviour else "")
        + f"ANSWER TO GRADE:\n{answer}"
    )
    return grader(prompt, structured_output_model=Verdict).structured_output

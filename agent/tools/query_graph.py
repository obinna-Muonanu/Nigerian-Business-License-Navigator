"""
This is the tool Navi uses for unusual questions that the ready-made tools can't answer, like "which regulator
issues the most permits?".

It hands the question to cypher_guard.py, which has the AI write a database question, checks it's safe, and runs it
in read-only mode. If anything goes wrong, Navi is told to use the normal tools instead.
"""

from strands import ToolContext, tool

from agent.knowledge import cypher_guard
from agent.tools._common import as_json


@tool(context=True)
def query_graph(question: str, tool_context: ToolContext) -> str:
    """Answer an unusual graph question the fixed tools cannot (counts, comparisons across business types,
    "which regulators issue the most permits?"). Runs a validated, read-only Cypher query.
    If it fails, use the fixed graph tools instead.

    Args:
        question: The question in plain English.
    """
    # Write the query, check it, test its syntax, then run it read-only. This never crashes; it always
    # returns a status. The tool is deliberately thin: all the safety logic lives in cypher_guard, where it
    # can be tested without an agent.
    return as_json(cypher_guard.answer_with_cypher(question))

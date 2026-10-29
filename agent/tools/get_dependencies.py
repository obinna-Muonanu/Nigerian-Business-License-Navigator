"""
This is the tool Navi uses to answer "what do I need to do before X?".

Given a step (by name or code), it returns the steps that must be finished first, with the reason for each, and the
steps this one unlocks once it's done.
"""

from strands import ToolContext, tool

from agent.knowledge import graph_service
from agent.tools._common import as_json, error


@tool(context=True)
def get_dependencies(requirement: str, tool_context: ToolContext) -> str:
    """What must be done before a requirement (direct prerequisites with reasons, plus the full chain),
    and what it unlocks next.

    Args:
        requirement: Requirement ID (e.g. D05) or name (e.g. "NAFDAC product registration").
    """
    # Work out which step the user means. People say "NAFDAC registration", not "D05", so the service accepts
    # a name too (and falls back to searching by meaning). That way the model never needs to know the codes.
    resolved = graph_service.resolve_requirement(requirement)
    if not resolved:
        return error(f"No requirement matches '{requirement}'.")

    # Return what comes directly before this step (with the reasons), the full chain before it, and the
    # steps it unlocks.
    return as_json(graph_service.get_dependencies(resolved["id"]))

"""
This is the tool Navi uses to explain WHY one step has to come before another.

For example, if a user asks "why do I need the NAFDAC facility inspection before product registration?", this tool
follows the links in the knowledge graph from one step to the other and returns the chain, with the official reason
for each link and the document it came from. It also prepares a small diagram of that chain for the web page.
"""

from strands import ToolContext, tool

from agent.knowledge import graph_service
from agent.tools._common import as_json, error


@tool(context=True)
def explain_path(later_step: str, earlier_step: str, tool_context: ToolContext) -> str:
    """Explain WHY one step must come before another, as the chain of dependencies in the graph, each
    link with its reason and source section.

    Args:
        later_step: The step that comes later, ID or name (e.g. "D05" or "NAFDAC product registration").
        earlier_step: The step that must come first, ID or name (e.g. "R01" or "CAC registration").
    """
    # Work out which two steps the user means. They might give codes or names.
    later = graph_service.resolve_requirement(later_step)
    earlier = graph_service.resolve_requirement(earlier_step)
    if not later or not earlier:
        return error("Could not identify both steps.", later=later, earlier=earlier)

    # Find the shortest chain linking them. If the user asked about the pair the wrong way round, the service
    # tries the other direction too. Every link carries the reason stored in the graph, so the answer
    # explains why in the regulators' own words instead of the model making a reason up.
    result = graph_service.explain_path(later["id"], earlier["id"])

    # The diagram data goes to the UI, not to the model, so it doesn't cost any tokens.
    if result.get("graph"):
        tool_context.agent.state.set("last_graph", result.pop("graph"))
    return as_json({"later": later, "earlier": earlier, **result})

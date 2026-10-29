"""
This is the tool Navi uses to look up details in the official documents: fees, forms, required documents, offices
and timelines.

It searches the documents by meaning and returns the most relevant passages, each with a ready-made source line for
the "Sources" list. If nothing relevant is found, it says so and gives the official website to point the user to,
so Navi never has to guess.
"""

from strands import ToolContext, tool

from agent.knowledge import retrieval_service
from agent.tools._common import as_json, profile_of


# The @tool decorator turns this function into a tool the model can call. The docstring becomes the tool's
# description and the "Args:" section describes each input, so both are written for the model to read.
# context=True asks Strands to pass in `tool_context`, which gives the tool access to the agent's state.
# The model never sees that input.
@tool(context=True)
def vector_search(query: str, tool_context: ToolContext, business_type: str | None = None) -> str:
    """Search the official-document summaries for details: fees, forms, required documents, offices,
    timelines and rules. Each result has a `source` with a ready-made `source_line` and `url`: mark the
    fact with a footnote number like [1] and list that source line under "Sources" at the end.

    Returns NO_RELEVANT_DOCUMENTS when nothing reliable exists: then say you do not know, point to an
    official source from the result, and offer a human handoff.

    Args:
        query: The question in clear standard English (translate Pidgin first), e.g. "NAFDAC product registration fee for fruit juice".
        business_type: Optional filter: DRINKS, PHARM, COSM or FURN. Defaults to the user's business type.
    """
    # If no business type was given, use the user's own, so the results stay on topic.
    bt = business_type or profile_of(tool_context).business_type
    bt = bt.upper() if bt else None

    # Search, keeping only results that are relevant enough. If nothing is, the service sends back the
    # official sources to point the user to instead.
    return as_json(retrieval_service.search(query, business_type=bt))

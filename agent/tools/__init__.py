"""WHAT THIS FOLDER IS
This folder holds the "tools": the specific actions Navi can take. Each tool has its own file.

They fall into five groups:
    Look things up:  search the documents, list requirements, find what must come first, explain why, or ask the
                     database an unusual question.
    Plan:            build the ordered checklist.
    Change records:  save the checklist, mark a step as done, or set a reminder. These need the user's "yes" first.
    Hand over:       pass the chat to a human adviser.
    Remember:        save a fact about the user's business.

This file lists every tool and says which ones change records. It also sets up the smaller set of tools given to
the "baseline" version of Navi, which is used in testing to measure how much the knowledge graph helps.
"""

# Tools that look things up.
from agent.tools.explain_path import explain_path
from agent.tools.get_dependencies import get_dependencies
from agent.tools.get_requirements import get_requirements
from agent.tools.query_graph import query_graph
from agent.tools.vector_search import vector_search

# The tool that plans the checklist.
from agent.tools.plan_steps import plan_steps

# Tools that change the user's records.
from agent.tools.save_checklist import save_checklist
from agent.tools.set_reminder import set_reminder
from agent.tools.update_progress import update_progress

# Tools that hand over to a human or remember a fact.
from agent.tools.handoff_to_human import handoff_to_human
from agent.tools.remember_profile import remember_profile

# The tools the confirmation hook (agent/hooks/confirmation.py) holds back until the user says yes.
WRITE_TOOLS = {"save_checklist", "update_progress", "set_reminder"}

# The full set of tools for the GraphRAG version of Navi. The order doesn't matter to the model; they're
# just grouped this way so it's easy to read.
GRAPHRAG_TOOLS = [
    vector_search, get_requirements, get_dependencies, plan_steps, explain_path, query_graph,
    save_checklist, update_progress, set_reminder,
    handoff_to_human, remember_profile,
]

# The tools for the vector-only baseline in the key experiment: same documents, same model, but no graph.
# The hand-off and remember tools are kept, so the baseline isn't marked down for things that have nothing
# to do with the graph.
BASELINE_TOOLS = [vector_search, handoff_to_human, remember_profile]

__all__ = ["GRAPHRAG_TOOLS", "BASELINE_TOOLS", "WRITE_TOOLS"]

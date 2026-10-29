"""WHAT THIS FOLDER IS
This folder connects the project to the AI models it uses, all of which come from Amazon Bedrock.

This file simply makes those connections easy for the rest of the project to reach. The real work is in
bedrock.py.
"""

from agent.llm.bedrock import build_agent_model, build_extraction_model, build_fast_model, embed_text

__all__ = ["build_agent_model", "build_fast_model", "build_extraction_model", "embed_text"]

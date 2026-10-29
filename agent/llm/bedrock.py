"""
It connects to Amazon Bedrock, the AWS service the project gets its AI models from, and sets each model up
for its job.

Three versions of Claude are used, each chosen to suit its task and keep costs down:
    Claude Haiku talks to the user. It's fast and cheap.
    Claude Haiku also writes short summaries and database questions in the background.
    Claude Sonnet, the more careful model, reads the official documents to build the knowledge graph,
        and marks Navi's answers during testing.

It also sets up Titan, a model that turns text into lists of numbers, so documents can be searched by meaning
rather than by exact words.
"""

import json
from functools import lru_cache

import boto3
from strands.models import BedrockModel, CacheConfig

from agent.config import get_settings


# Every call to AWS goes through one shared session, created once and then reused. Creating new
# sessions over and over would re-read the credentials files each time and slow everything down.
#
# The credentials are chosen in this order. If AWS_PROFILE is set, we use that profile from ~/.aws.
# Otherwise, if access keys are in .env, we pass them in directly. That second step is needed because
# our settings loader reads .env without copying it into the environment, so boto3 wouldn't find keys
# that only live in .env. If neither is set, boto3 falls back to its usual places: environment
# variables, ~/.aws/credentials, SSO or an attached role.
@lru_cache(maxsize=1)
def _boto_session() -> boto3.Session:
    s = get_settings()
    if s.aws_profile:
        return boto3.Session(profile_name=s.aws_profile, region_name=s.aws_region)
    if s.aws_access_key_id:
        return boto3.Session(
            aws_access_key_id=s.aws_access_key_id,
            # The secret values are only unwrapped here, right where they're used.
            aws_secret_access_key=s.aws_secret_access_key.get_secret_value() if s.aws_secret_access_key else None,
            aws_session_token=s.aws_session_token.get_secret_value() if s.aws_session_token else None,
            region_name=s.aws_region,
        )
    return boto3.Session(region_name=s.aws_region)


def build_agent_model() -> BedrockModel:
    """Build the main model that talks to the user.

    The cache setting lets Strands mark the tool definitions and the conversation history for Bedrock's
    prompt cache. Each call in the agent loop starts with the same long prefix, so most of it can be read
    from the cache instead of being processed again. The system prompt already has its own cache marker
    (placed by hand in agent/core.py), and Strands respects that instead of adding a second one.
    """
    s = get_settings()
    return BedrockModel(
        model_id=s.agent_model_id,
        boto_session=_boto_session(),
        # A low temperature keeps answers steady and predictable. We're explaining regulations here, not
        # writing poetry.
        temperature=0.1,
        # The reply limit is 4,000 tokens, up from 1,500. A full checklist plus its Sources list can go past
        # 1,500, and the baseline once got cut off answering "what do I need, and in what order?". We only
        # pay for tokens that are actually written, so the higher limit costs nothing on short replies, and
        # the prompt still asks for concise answers.
        max_tokens=4000,
        # Streaming sends the words to the UI as they're written.
        streaming=True,
        # tools_ttl=True also caches the roughly 2,000 tokens of tool definitions sent on every call.
        cache_config=CacheConfig(strategy="auto", tools_ttl=True),
    )


def build_fast_model(max_tokens: int = 600) -> BedrockModel:
    """Build the cheap, quick model used for background summaries and text-to-Cypher.

    The temperature is zero because these jobs need consistent output: the same input should give the
    same query or summary. Streaming is off because nobody is watching these words arrive, and getting
    one finished response back is simpler.
    """
    s = get_settings()
    return BedrockModel(
        model_id=s.fast_model_id,
        boto_session=_boto_session(),
        temperature=0.0,
        max_tokens=max_tokens,
        streaming=False,
    )


def build_extraction_model() -> BedrockModel:
    """Build the most accurate model, used to extract the graph from each document.

    The evaluation judge uses it too. Both jobs care about accuracy far more than speed, and both run
    offline, so the extra cost and time don't matter.
    """
    s = get_settings()
    return BedrockModel(
        model_id=s.extraction_model_id,
        boto_session=_boto_session(),
        temperature=0.0,
        # One document can describe ten or more requirements, so the reply needs plenty of room.
        max_tokens=8000,
        streaming=False,
    )


# Strands models are made for chat, so for embeddings we call Bedrock directly with the plain
# bedrock-runtime client. It's created once and reused, along with its pool of connections.
@lru_cache(maxsize=1)
def _bedrock_runtime():
    return _boto_session().client("bedrock-runtime")


# Embeddings are cached too. If the same text comes up again, like a repeated question or a name lookup
# that falls back to search, it's only sent to Titan once, which saves a network call each time.
@lru_cache(maxsize=512)
def embed_text(text: str) -> tuple[float, ...]:
    """Turn one piece of text into a vector with Titan Text Embeddings V2.

    The result comes back as a tuple rather than a list, because the cache needs a value that can't be
    changed. Callers turn it into a list when they need one.
    """
    s = get_settings()
    # Build the request the way Titan V2 expects it. We trim the text to stay under the model's input
    # limit, and ask for normalised vectors, which is what cosine similarity search works with.
    body = json.dumps({"inputText": text[:20000], "dimensions": s.embed_dimensions, "normalize": True})
    response = _bedrock_runtime().invoke_model(
        modelId=s.embed_model_id, body=body, contentType="application/json", accept="application/json"
    )
    # The response body is a stream, so we read it once and pull the vector out.
    payload = json.loads(response["body"].read())
    return tuple(payload["embedding"])

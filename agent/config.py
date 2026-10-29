"""
It reads the project's settings and makes sure they make sense before anything else starts.

The settings live in a private file called .env: things like the password for the database, which AI
model to use, and how many search results to look at. This file reads them once, checks each one (is the
password there? is that number in a sensible range?), and hands them to the rest of the project.

WHY IT MATTERS
If a setting is missing or wrong, the app stops straight away with a clear message listing exactly what
to fix, instead of failing later in the middle of a conversation. Passwords are kept hidden so they never
show up in logs or error messages.
"""

from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Work out where the project folder is from where this file lives (agent/config.py sits one level
# down). That way the app finds its files no matter which folder you start it from.
ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Every setting the app uses. Each field is filled from the variable with the same name in .env."""

    # This tells Pydantic how to load the settings. It reads the .env file in the project folder, but a
    # real environment variable still wins, so you can override one setting for a single run. Unrelated
    # variables in .env (like API_URL, which only Streamlit uses) are ignored rather than treated as
    # errors. And once loaded, the settings are frozen, so no part of the app can change one by accident.
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # These say which AWS region and credentials to use, and which Bedrock model plays which role.
    # The access keys are optional: leave them out and the app uses your AWS profile or boto3's usual
    # way of finding credentials. Secrets are stored as SecretStr, which shows "**********" instead of
    # the real value if they ever end up in a log or an error message.
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_session_token: SecretStr | None = None
    agent_model_id: str = Field(min_length=1, description="Main conversational model (tool use, planning, Pidgin)")
    fast_model_id: str = Field(default="", description="Cheap model for summaries and text-to-Cypher")
    extraction_model_id: str = Field(default="", description="Accurate model for graph extraction and the eval judge")
    embed_model_id: str = "amazon.titan-embed-text-v2:0"
    # Titan only makes vectors of 256, 512 or 1024 numbers, and the Neo4j vector index has to use the
    # same size. It's a plain number with its own check below, rather than a fixed list of allowed
    # values, because .env gives us the text "1024" and Pydantic won't turn text into a number when
    # matching it against a fixed list.
    embed_dimensions: int = 1024

    # These connect to Neo4j, the one database that holds both the knowledge graph and the document
    # chunks. The pattern on the address catches the common mistake of pasting the browser console's
    # web address instead of the driver address.
    neo4j_uri: str = Field(pattern=r"^(neo4j|bolt)(\+s|\+ssc)?://")
    neo4j_user: str = "a25098d1"
    neo4j_password: SecretStr
    neo4j_database: str = "a25098d1"

    # These tune search and memory, and each one is range-checked when the app starts.
    # min_relevance is how close a document chunk has to be before it counts as relevant. top_k is how
    # many chunks one search returns, which directly affects how many tokens we send. The next three
    # control memory: after how many turns the chat is summarised, how many recent messages are kept
    # word for word, and how often the long-term summary of the user is refreshed.
    min_relevance: float = Field(default=0.70, ge=0.0, le=1.0)
    top_k: int = Field(default=4, ge=1, le=20)
    summary_trigger_turns: int = Field(default=30, ge=1)
    keep_recent_messages: int = Field(default=12, ge=2)
    summary_every_n_turns: int = Field(default=4, ge=1)

    # This is where the Streamlit app finds the API server.
    api_url: str = "http://localhost:8000"

    @field_validator("embed_dimensions")
    @classmethod
    def _valid_dimensions(cls, value: int) -> int:
        """Make sure the embedding size is one Titan supports.

        By the time this runs, "1024" has already become the number 1024, so we're comparing numbers.
        """
        if value not in (256, 512, 1024):
            raise ValueError("must be 256, 512 or 1024 (the sizes Titan Text Embeddings V2 supports)")
        return value

    @field_validator("aws_profile", "aws_access_key_id", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """Treat a setting left blank in .env (like `AWS_PROFILE=`) as "not set", not as an empty name."""
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="before")
    @classmethod
    def _default_models(cls, data: object) -> object:
        """Let the fast and extraction models fall back to the agent model when they aren't set.

        That way a minimal .env with only AGENT_MODEL_ID still works; it just costs a bit more. This
        runs on the raw values before anything else is checked, because the settings are frozen
        afterwards and can't be filled in later.
        """
        # We only fill these in when an agent model was actually given. Otherwise the error message
        # would complain about three missing models when the user really only needs to set one.
        if isinstance(data, dict):
            agent_model = data.get("agent_model_id")
            for key in ("fast_model_id", "extraction_model_id"):
                if agent_model and not data.get(key):
                    data[key] = agent_model
        return data

    # The folders below are worked out from the project folder rather than read from .env, so there's
    # nothing to configure. They're properties, which also keeps Pydantic from looking for them in .env.
    @property
    def root(self) -> Path:
        return ROOT

    @property
    def kb_dir(self) -> Path:
        # The markdown knowledge base: the source documents everything is built from.
        return ROOT / "knowledge_base"

    @property
    def graph_dir(self) -> Path:
        # The extracted and reviewed graph files, plus the cache of embeddings.
        return ROOT / "data" / "graph"

    @property
    def runtime_dir(self) -> Path:
        # Where the SQLite database lives.
        return ROOT / "data" / "runtime"

    @property
    def sessions_dir(self) -> Path:
        # Strands saves each conversation here; this is the short-term memory on disk.
        return ROOT / "sessions"

    @property
    def logs_dir(self) -> Path:
        # One audit log file per conversation, in JSONL format.
        return ROOT / "logs"

    @property
    def sqlite_path(self) -> Path:
        return self.runtime_dir / "navigator.db"


def _friendly_error(exc: ValidationError) -> str:
    """Turn Pydantic's list of errors into one readable message that names each variable to fix."""
    lines = ["Configuration problem in .env (copy .env.example to .env and fix these):"]
    for err in exc.errors():
        variable = str(err["loc"][0]).upper() if err["loc"] else "(settings)"
        lines.append(f"  - {variable}: {err['msg']}")
    return "\n".join(lines)


# The cache means the settings are built only once. The first call reads and checks .env, and every
# call after that gets the same object back, so it's cheap to call get_settings() from anywhere.
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and check the settings once, and stop with a clear message if anything is wrong."""
    try:
        settings = Settings()
    except ValidationError as exc:
        # Exiting with a message instead of a long traceback shows the user only what they need to fix.
        raise SystemExit(_friendly_error(exc)) from None

    # Create the folders the app writes to now, so no other part of the code has to check first.
    for folder in (settings.runtime_dir, settings.graph_dir, settings.sessions_dir, settings.logs_dir):
        folder.mkdir(parents=True, exist_ok=True)
    return settings

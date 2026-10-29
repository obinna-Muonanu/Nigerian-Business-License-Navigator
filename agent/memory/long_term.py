"""
It handles Navi's long-term memory: the facts it remembers about each user from one chat to the next.

When a user mentions a fact about their business (what they sell, their state, whether they're registered with
CAC, and so on), this file checks it and saves it straight away, so nothing is lost if they close the page. At the
start of every new chat, it loads those facts back, so Navi can greet a returning user with "still zobo in Ibadan?"
instead of asking everything again.

WHY IT MATTERS FOR PRIVACY
Only a short, fixed list of business facts can ever be saved. Navi can't store anything else it hears, which keeps
personal information to a minimum.
"""

from dataclasses import dataclass, field

from agent.schemas import PROFILE_FIELDS, UserProfile
from agent.storage import sqlite_store


@dataclass
class UserMemory:
    """Everything we load about a user when a chat starts.

    It's all bundled into one object, rather than several separate lookups, so build_agent can write the
    memory block in one go. Each new UserMemory gets its own empty profile and list, rather than sharing
    one with every other instance.
    """

    profile: UserProfile = field(default_factory=UserProfile)
    language: str | None = None
    summary: str | None = None
    completed: list[str] = field(default_factory=list)


class LongTermMemory:
    """A thin layer over the user_memory and progress tables in SQLite.

    Everything here is a static method, because the database holds all the state and there's nothing to
    keep on the object itself. The class just groups the memory operations under one name that the tools
    and hooks can import.
    """

    @staticmethod
    def load(user_id: str) -> UserMemory:
        """Load what we remember about a user at the start of a chat."""
        raw = sqlite_store.load_user_memory(user_id)
        # Building a UserProfile from the stored data checks it again. If an old or hand-edited row has a
        # bad value, it fails loudly here rather than quietly producing a wrong plan later.
        return UserMemory(
            profile=UserProfile(**raw["profile"]),
            language=raw["language"],
            summary=raw["summary"],
            completed=sqlite_store.completed_steps(user_id),
        )

    @staticmethod
    def remember(user_id: str, profile: UserProfile, field_name: str, value: str) -> UserProfile:
        """Check one fact, turn it into the right code, update the profile and save it. Raises ValueError if it's not valid.

        The model sends values as ordinary text, like "yes", "oyo" or "Sole proprietorship". This turns them
        into the exact codes the planner uses. If something's wrong, the error message goes back to the
        model, which then asks the user again or uses a valid code.
        """
        # Only the known business facts can ever be stored. This keeps personal data to a minimum, as the NDPA asks.
        if field_name not in PROFILE_FIELDS:
            raise ValueError(f"Unknown field '{field_name}'. Allowed: {', '.join(PROFILE_FIELDS)}")
        allowed = PROFILE_FIELDS[field_name]
        text = str(value).strip()

        # For yes-or-no facts, accept the usual ways of saying yes and no, in English and in Pidgin.
        if allowed is bool:
            lowered = text.lower()
            if lowered in {"true", "yes", "y", "yeah", "e dey", "i dey", "na so", "1"}:
                coerced: object = True
            elif lowered in {"false", "no", "n", "nope", "e no dey", "i no dey", "0"}:
                coerced = False
            else:
                raise ValueError(f"'{field_name}' needs yes or no, got '{value}'")
        elif allowed is str:
            # Free text, like a business name, is kept short.
            coerced = text[:80]
        else:
            # For everything else, match the allowed codes without caring about upper or lower case, so "oyo" becomes "Oyo".
            match = next((a for a in allowed if a.lower() == text.lower()), None)
            if match is None:
                raise ValueError(f"'{value}' is not valid for {field_name}. Allowed: {', '.join(allowed)}")
            coerced = match

        # Make a new copy of the profile with the updated fact, then save the whole profile, so SQLite always
        # holds one complete, consistent picture.
        updated = profile.model_copy(update={field_name: coerced})
        sqlite_store.save_profile(user_id, updated.model_dump(exclude_none=True))
        return updated

    @staticmethod
    def remember_language(user_id: str, language: str) -> None:
        """Note the language the input guard spotted in the user's message (English or Pidgin)."""
        sqlite_store.save_language(user_id, language)

    @staticmethod
    def remember_summary(user_id: str, summary: str) -> None:
        """Save the short chat summary from the background summariser. It appears in the next chat's memory block."""
        sqlite_store.save_summary(user_id, summary)

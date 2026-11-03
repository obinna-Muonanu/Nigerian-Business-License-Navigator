"""
It handles Navi's long-term memory: the confirmed facts it keeps about each user from one chat to the next.

A user can run more than one business, so the facts are kept per business. Each business has its own profile
(what it sells, which state it's in, whether it's registered with CAC, and so on) and its own finished steps. At the
start of every chat, all of a user's businesses are loaded, so Navi can greet a returning user with "still zobo in
Ibadan?" instead of asking everything again.

The rules that make this memory trustworthy:
    Only a short, fixed list of business facts can be saved, and each one is checked before it's stored.
    Every fact records where it came from (the user said it, or it followed from recorded progress) and when.
    A fact is never silently overwritten. If the user says something that contradicts what's stored, Navi is told
        about the conflict and must check with the user before changing it.
    Every change is kept in a history, and users can see, download or delete everything we hold.
    A business nobody has used for 6 months is set aside as "inactive": kept, but Navi only sees its name. Using it
        again brings it straight back. After 18 months unused it's deleted (see retire_unused_businesses in store.py).

WHY IT MATTERS
Navi builds licence plans from these facts. One wrong remembered fact, like "already registered with CAC", would
quietly drop a step from someone's plan, so this memory has to hold confirmed facts, not guesses.
"""

from dataclasses import dataclass, field

from agent.schemas import BUSINESS_TYPE_NAMES, PROFILE_FIELDS, UserProfile
from agent.storage import store

# A sensible ceiling on how many businesses one user can have, so a runaway loop can't create thousands.
MAX_BUSINESSES_PER_USER = 10

# Where a fact can come from. They're stored with every fact, so we can always explain why Navi believes it.
SOURCES = {"user_stated", "progress_update", "migrated", "seeded"}


@dataclass
class BusinessMemory:
    """Everything remembered about one business: its label, its profile, where each fact came from, and finished steps."""

    business_id: str
    label: str
    profile: UserProfile = field(default_factory=UserProfile)
    sources: dict[str, dict] = field(default_factory=dict)
    completed: list[str] = field(default_factory=list)
    # "active", or "inactive" once it hasn't been used for 6 months. last_used_at is when Navi last worked on it.
    status: str = "active"
    last_used_at: str | None = None
    # True only when this lookup has just brought an inactive business back, so a tool can tell Navi.
    reactivated: bool = False

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass
class UserMemory:
    """Everything loaded about a user when a chat starts: their businesses and the notes from their recent chats."""

    businesses: list[BusinessMemory] = field(default_factory=list)
    episodes: list[dict] = field(default_factory=list)


class BusinessNotFound(ValueError):
    """Raised when Navi names a business that doesn't exist, or doesn't say which one when there are several.

    The message lists the user's businesses, so the model can pick the right one or ask the user.
    """


@dataclass
class RememberResult:
    """What happened when Navi tried to save a fact: the profile afterwards, and any conflict that stopped it."""

    business: BusinessMemory
    saved: bool
    conflict: dict | None = None


class LongTermMemory:
    """The memory operations the tools, hooks and server use. All the state lives in the database (see store.py)."""

    # Loading.

    @staticmethod
    def _business(row: dict) -> BusinessMemory:
        """Build one BusinessMemory from its database row, its facts and its finished steps."""
        facts = store.load_facts(row["business_id"])
        # Building a UserProfile checks every stored value again. If a bad value somehow got in, it fails loudly
        # here rather than quietly producing a wrong plan later.
        profile = UserProfile(**{name: f["value"] for name, f in facts.items() if name in PROFILE_FIELDS})
        sources = {name: {"source": f["source"], "updated_at": f["updated_at"]} for name, f in facts.items()}
        return BusinessMemory(business_id=row["business_id"], label=row["label"], profile=profile,
                              sources=sources, completed=store.completed_steps(row["business_id"]),
                              status=row.get("status") or "active", last_used_at=row.get("last_used_at"))

    @staticmethod
    def _use(business: BusinessMemory) -> BusinessMemory:
        """Record that Navi is working on this business. An inactive one becomes active again, with everything intact."""
        store.touch_business(business.business_id)
        if not business.active:
            business.status, business.reactivated = "active", True
        return business

    @staticmethod
    def load(user_id: str) -> UserMemory:
        """Load what we remember about a user at the start of a chat."""
        return UserMemory(
            businesses=[LongTermMemory._business(row) for row in store.list_businesses(user_id)],
            episodes=store.recent_episodes(user_id),
        )

    # Finding the business a tool is talking about.

    @staticmethod
    def resolve(user_id: str, reference: str | None, create_if_none: bool = False) -> BusinessMemory | None:
        """Work out which of the user's businesses `reference` means.

        The model can name a business by its label ("Business 2", "zobo business"), its registered name, or its
        kind ("pharmacy", "PHARM"). With only one active business, it doesn't need to name it at all. With several
        and no name, or a name that matches none or more than one, we raise BusinessNotFound with the options,
        rather than guess. Guessing is exactly how a step gets recorded against the wrong business.

        Inactive businesses can be found by name too. Whatever business is found is marked as just used, and an
        inactive one becomes active again: the user is clearly working on it.
        """
        rows = store.list_businesses(user_id)
        if not rows:
            if reference and not create_if_none:
                raise BusinessNotFound(f"There is no business called '{reference}'. Use add_business first.")
            if not create_if_none:
                return None
            # The very first fact a new user shares creates their first business automatically, so a user with a
            # single business never has to think about businesses at all.
            business_id = store.create_business(user_id, reference.strip()[:60] if reference else "Business 1")
            return LongTermMemory._business({"business_id": business_id,
                                             "label": reference.strip()[:60] if reference else "Business 1"})

        businesses = [LongTermMemory._business(row) for row in rows]
        active = [b for b in businesses if b.active]
        if not reference:
            # One active business is the obvious one, even if older inactive ones exist. If every business is
            # inactive and there's only one, that's the one the user means.
            if len(active) == 1:
                return LongTermMemory._use(active[0])
            if not active and len(businesses) == 1:
                return LongTermMemory._use(businesses[0])
            raise BusinessNotFound("This user has more than one business. Pass `business` with one of: "
                                   + LongTermMemory._options(businesses) + ". If unsure, ask the user.")

        found = LongTermMemory._match(businesses, reference)
        if found:
            return LongTermMemory._use(found)
        loose = [b for b in businesses if LongTermMemory._describes(b, reference)]
        problem = "matches more than one business" if loose else "does not match any business"
        raise BusinessNotFound(f"'{reference}' {problem}. This user's businesses are: "
                               f"{LongTermMemory._options(businesses)}. Use one of these labels, or add_business "
                               "for a new one.")

    @staticmethod
    def _describes(b: BusinessMemory, reference: str) -> bool:
        """Check whether a name loosely describes a business: its label, registered name or kind of business."""
        wanted = " ".join(reference.lower().split())
        names = [b.label, b.profile.business_name or ""]
        if b.profile.business_type:
            names += [b.profile.business_type, BUSINESS_TYPE_NAMES[b.profile.business_type]]
        names = [n.lower() for n in names if n]
        return any(wanted in n or n in wanted for n in names)

    @staticmethod
    def _match(businesses: list[BusinessMemory], reference: str) -> BusinessMemory | None:
        """Find the one business a name refers to, or nothing if it's unclear.

        An exact match on the ID or label wins. Otherwise we try a looser match on the label, the registered name
        or the kind of business. If that loosely matches several, but only one of them is active, the user almost
        certainly means the active one.
        """
        wanted = " ".join(reference.lower().split())
        exact = [b for b in businesses if wanted in (b.business_id.lower(), b.label.lower())]
        if len(exact) == 1:
            return exact[0]
        loose = [b for b in businesses if LongTermMemory._describes(b, reference)]
        if len(loose) == 1:
            return loose[0]
        loose_active = [b for b in loose if b.active]
        return loose_active[0] if len(loose_active) == 1 else None

    @staticmethod
    def _options(businesses: list[BusinessMemory]) -> str:
        """List the businesses' labels for an error message, marking the inactive ones."""
        return ", ".join(f'"{b.label}"' + ("" if b.active else " (inactive)") for b in businesses)

    @staticmethod
    def add_business(user_id: str, label: str, force_new: bool = False) -> BusinessMemory:
        """Create a new business for a user, with a short label the user will recognise.

        Before creating anything, it checks the user's inactive businesses. If one matches the name, the user is
        almost certainly coming back to it, so that one is brought back (with all its saved details) instead of
        creating an empty duplicate. The returned business has reactivated=True so Navi can say so. If the user
        really does want a second, separate business of the same kind, Navi passes force_new=True.
        """
        label = " ".join(str(label).split())[:60]
        if not label:
            raise ValueError("A business needs a short name, like 'zobo business' or 'Lagos pharmacy'.")
        existing = store.list_businesses(user_id)
        if not force_new:
            inactive = [LongTermMemory._business(row) for row in existing if row.get("status") == "inactive"]
            match = LongTermMemory._match(inactive, label) if inactive else None
            if match:
                return LongTermMemory._use(match)
        if any(b["label"].lower() == label.lower() for b in existing):
            raise ValueError(f"There is already a business called '{label}'.")
        if len(existing) >= MAX_BUSINESSES_PER_USER:
            raise ValueError(f"A user can have at most {MAX_BUSINESSES_PER_USER} businesses.")
        business_id = store.create_business(user_id, label)
        return LongTermMemory._business({"business_id": business_id, "label": label})

    # Saving facts.

    @staticmethod
    def _coerce(field_name: str, value: str) -> object:
        """Check one fact and turn it into the exact code the planner uses. Raises ValueError if it isn't valid.

        The model sends values as ordinary text, like "yes", "oyo" or "Sole proprietorship". If something's
        wrong, the error message goes back to the model, which then asks the user again or uses a valid code.
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
                return True
            if lowered in {"false", "no", "n", "nope", "e no dey", "i no dey", "0"}:
                return False
            raise ValueError(f"'{field_name}' needs yes or no, got '{value}'")
        # Free text, like a business name, is kept short.
        if allowed is str:
            return text[:80]
        # For everything else, match the allowed codes without caring about case, so "oyo" becomes "Oyo".
        match = next((a for a in allowed if a.lower() == text.lower()), None)
        if match is None:
            raise ValueError(f"'{value}' is not valid for {field_name}. Allowed: {', '.join(allowed)}")
        return match

    @staticmethod
    def remember(user_id: str, business: BusinessMemory, field_name: str, value: str, *,
                 source: str = "user_stated", session_id: str | None = None,
                 confirm_change: bool = False) -> RememberResult:
        """Check one fact and save it against one business, unless it contradicts what's already stored.

        If the business already has a different value for this fact, nothing is saved unless confirm_change is
        true. Instead the conflict is returned, so Navi can ask the user which is right. Saying the same value
        again is fine and changes nothing.
        """
        if source not in SOURCES:
            raise ValueError(f"Unknown source '{source}'")
        coerced = LongTermMemory._coerce(field_name, value)
        current = getattr(business.profile, field_name)

        if current is not None and current != coerced and not confirm_change:
            return RememberResult(business=business, saved=False, conflict={
                "field": field_name, "stored_value": current, "new_value": coerced,
                "stored_since": business.sources.get(field_name, {}).get("updated_at"),
            })

        store.save_fact(business.business_id, field_name, coerced, source, session_id)
        # Hand back a fresh copy of the business, so the caller sees the fact exactly as it's now stored.
        updated = LongTermMemory._business({"business_id": business.business_id, "label": business.label})
        return RememberResult(business=updated, saved=True)

    @staticmethod
    def seed_business(user_id: str, profile: dict, done: list[str] | None = None, label: str = "Business 1") -> str:
        """Create a business with a ready-made profile and progress. The evaluation uses this to set up test users."""
        business_id = store.create_business(user_id, label)
        for field_name, value in profile.items():
            store.save_fact(business_id, field_name, value, "seeded", None)
        for step in done or []:
            store.set_progress(business_id, step, "done", "seeded", None)
        return business_id

    # Other things worth remembering.

    @staticmethod
    def remember_episode(user_id: str, session_id: str, summary: str) -> None:
        """Save the short note about one chat, written by the background summariser (episodic memory)."""
        store.save_episode(user_id, session_id, summary)

    # The user's data rights.

    @staticmethod
    def export(user_id: str) -> dict:
        """Everything stored about a user, so they can see it or take it with them."""
        return store.export_user_data(user_id)

    @staticmethod
    def forget_user(user_id: str) -> None:
        """Delete everything stored about a user."""
        store.delete_user_data(user_id)

    @staticmethod
    def forget_business(user_id: str, business_id: str) -> bool:
        """Delete one business and everything recorded about it."""
        return store.delete_business(user_id, business_id)

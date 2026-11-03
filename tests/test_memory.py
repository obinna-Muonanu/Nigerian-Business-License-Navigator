"""Long-term memory: facts are kept per business, contradictions aren't saved silently, and users never mix."""

import pytest

from agent.memory import LongTermMemory
from agent.memory.long_term import BusinessNotFound


def test_a_users_first_fact_creates_their_first_business(db):
    business = LongTermMemory.resolve("ada", None, create_if_none=True)
    result = LongTermMemory.remember("ada", business, "state", "oyo")
    assert result.saved
    assert result.business.profile.state == "Oyo"


def test_invalid_values_are_refused():
    business = LongTermMemory._business({"business_id": "b1", "label": "Business 1"})
    with pytest.raises(ValueError):
        LongTermMemory._coerce("state", "Atlantis")
    with pytest.raises(ValueError):
        LongTermMemory.remember("ada", business, "password", "secret")


def test_a_contradiction_is_returned_not_saved(db):
    business = LongTermMemory.resolve("ada", None, create_if_none=True)
    business = LongTermMemory.remember("ada", business, "state", "Oyo").business

    result = LongTermMemory.remember("ada", business, "state", "Lagos")
    assert not result.saved
    assert result.conflict["stored_value"] == "Oyo"

    confirmed = LongTermMemory.remember("ada", business, "state", "Lagos", confirm_change=True)
    assert confirmed.saved
    assert confirmed.business.profile.state == "Lagos"


def test_with_two_businesses_navi_must_say_which_one(db):
    LongTermMemory.add_business("ada", "zobo business")
    LongTermMemory.add_business("ada", "Lagos pharmacy")
    with pytest.raises(BusinessNotFound):
        LongTermMemory.resolve("ada", None)
    assert LongTermMemory.resolve("ada", "pharmacy").label == "Lagos pharmacy"


def test_one_users_memory_never_reaches_another(db):
    zobo = LongTermMemory.add_business("ada", "zobo business")
    LongTermMemory.remember("ada", zobo, "state", "Oyo")

    assert LongTermMemory.load("bola").businesses == []
    with pytest.raises(BusinessNotFound):
        LongTermMemory.resolve("bola", "zobo business")


def test_forgetting_a_user_erases_everything(db):
    zobo = LongTermMemory.add_business("ada", "zobo business")
    LongTermMemory.remember("ada", zobo, "state", "Oyo")
    LongTermMemory.forget_user("ada")
    assert LongTermMemory.load("ada").businesses == []

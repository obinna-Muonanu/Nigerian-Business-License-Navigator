"""The input guard: spotting Pidgin so Navi replies in it, and hiding personal numbers before anything is stored."""

import pytest

from agent.hooks.input_guard import _is_pidgin, mask_pii


@pytest.mark.parametrize("text", [
    "Abeg, wetin I need to start zobo business for Ibadan?",
    "How much e go cost me to register?",
    "I wan open pharmacy for Lagos, how far?",
])
def test_pidgin_is_recognised(text):
    assert _is_pidgin(text)


@pytest.mark.parametrize("text", [
    "What do I need to register a cosmetics business in Lagos?",
    "Can I go get the forms myself?",
    "I will go to the CAC office tomorrow.",
])
def test_english_is_not_mistaken_for_pidgin(text):
    assert not _is_pidgin(text)


def test_a_labelled_nin_is_hidden():
    masked, changed = mask_pii("My NIN is 12345678901, please save it")
    assert changed
    assert "12345678901" not in masked


def test_a_real_looking_card_number_is_hidden():
    masked, changed = mask_pii("Pay with 4111 1111 1111 1111")
    assert changed
    assert "4111" not in masked


def test_a_phone_number_and_ordinary_numbers_are_left_alone():
    text = "Call me on 08031234567. The fee is 25000 naira and my RC number is 1234567."
    masked, changed = mask_pii(text)
    assert not changed
    assert masked == text

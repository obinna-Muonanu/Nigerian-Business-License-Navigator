"""
It holds small helpers the safety rules share for reading and annotating the conversation.

For example, it finds the latest thing the user actually typed, and attaches short, clearly labelled notes for the AI
to the user's message (like "this message is in Pidgin, reply in Pidgin"). Those notes are kept separate from the
user's own words and are never shown to the user.
"""

from typing import Any

# Every note our hooks add for the model starts with this, so the chat history view can hide them from the user.
POLICY_NOTE_PREFIX = "[policy note for the assistant:"


def last_user_text_message(messages: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Find the most recent user message that has text in it, skipping messages that only carry tool results.

    We have to search backwards from the end, because tool results are also sent as user messages.
    """
    for message in reversed(messages or []):
        if message.get("role") == "user" and any("text" in block for block in message.get("content", [])):
            return message
    return None


def text_of(message: dict[str, Any] | None) -> str:
    """Get what the person actually wrote: all the text joined together, leaving out the notes our hooks added.

    Leaving the notes out matters because the hooks run one after another. The input guard adds a language
    note before the confirmation hook reads the message. When that note was counted, "Yes, please mark it as
    done." looked like a 30-word message, so it failed the "short yes" check and the user's confirmation was
    ignored.
    """
    if not message:
        return ""
    return " ".join(
        block["text"] for block in message.get("content", [])
        if "text" in block and not block["text"].startswith(POLICY_NOTE_PREFIX)
    )


def add_policy_note(message: dict[str, Any], note: str) -> None:
    """Attach a short, clearly labelled note for the model to the user's message.

    It's added as a separate piece of text rather than editing what the user wrote. That leaves their words
    untouched and makes it obvious, in the logs too, which words came from the guard and which from the user.
    """
    message.setdefault("content", []).append({"text": f"{POLICY_NOTE_PREFIX} {note}]"})

"""
It writes a short note about each chat, so Navi remembers the gist next time.

Every few turns, and whenever a chat ends, it asks a cheap, fast AI model for a three-line summary: the user's
business and location, what they've done or decided, and what they should do next. That note is saved and shown
to Navi at the start of the user's next chat. It runs in the background after the reply has been sent, so the user
never waits for it.
"""

from strands import Agent

from agent.config import get_settings
from agent.llm import build_fast_model
from agent.memory.long_term import LongTermMemory
from agent.prompts import SUMMARY_PROMPT


def _transcript(messages: list[dict], max_chars: int = 6000) -> str:
    """Turn the chat into plain text: just what the user and the assistant said, without the tool data.

    The tool data is left out because the summary only needs what was said and decided, and raw data would
    multiply the cost. We keep the last 6,000 characters, since the most recent turns matter most.
    """
    lines = []
    for message in messages:
        texts = [block["text"] for block in message.get("content", []) if "text" in block]
        if texts:
            lines.append(f"{message['role'].upper()}: {' '.join(texts)}")
    return "\n".join(lines)[-max_chars:]


def summarise(messages: list[dict]) -> str | None:
    """Ask the fast model for a three-line summary. Returns nothing if there's nothing worth keeping."""
    transcript = _transcript(messages)
    if not transcript.strip():
        return None
    # A throwaway agent with no tools and no chat of its own. Its only job is to write the summary.
    writer = Agent(model=build_fast_model(max_tokens=200), system_prompt=SUMMARY_PROMPT, callback_handler=None)
    text = str(writer(transcript)).strip()
    # The prompt asks the model to say "NOTHING" when the chat had nothing useful in it. In that case we skip
    # saving, rather than overwrite a good summary from an earlier chat.
    return None if not text or text.upper().startswith("NOTHING") else text


def maybe_summarise(user_id: str, messages: list[dict], turns: int, force: bool = False) -> None:
    """Refresh the saved summary every few turns, or straight away when a chat ends."""
    # Summarising after every turn would waste calls; every few turns keeps it fresh enough. When the user
    # ends a chat (by starting a new one, for example), force is set and we summarise right away.
    every = get_settings().summary_every_n_turns
    if not force and (turns == 0 or turns % every != 0):
        return
    try:
        summary = summarise(messages)
        if summary:
            LongTermMemory.remember_summary(user_id, summary)
    except Exception as exc:
        # A failed summary must never break the chat, so we just note it and move on.
        print(f"[memory] summary skipped: {exc}")

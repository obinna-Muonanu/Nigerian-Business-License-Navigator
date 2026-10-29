"""
It rebuilds an old chat so it can be shown again exactly as the user first saw it.

When a user clicks a past chat in the sidebar, this file reads the saved conversation and turns it back into the
list of messages: what the user typed and what Navi replied. It hides the behind-the-scenes parts, like internal
notes, the details of Navi's lookups, and internal reference codes, so the user only sees the conversation itself.
"""

from strands.session.file_session_manager import FileSessionManager

from agent.config import get_settings
from agent.hooks._messages import POLICY_NOTE_PREFIX
from agent.output_filter import scrub

# When no agent ID is given (and core.build_agent doesn't give one), Strands calls the agent "default"
# and saves its messages under sessions/session_<id>/agents/agent_default/.
AGENT_ID = "default"


def session_transcript(session_id: str) -> list[dict[str, str]]:
    """Return the chat as a list of messages, each with a role ("user" or "assistant") and its text, in order."""
    manager = FileSessionManager(session_id=session_id, storage_dir=str(get_settings().sessions_dir))
    stored = manager.list_messages(session_id, AGENT_ID)

    turns: list[dict[str, str]] = []
    for session_message in stored:
        # Converting it this way respects anything Strands chose to redact.
        message = session_message.to_message()
        content = message.get("content", [])

        if message["role"] == "user":
            # Tool results are sent back inside user messages, but they're internal, not something the user typed.
            if any("toolResult" in block for block in content):
                continue
            texts = [b["text"] for b in content if "text" in b and not b["text"].startswith(POLICY_NOTE_PREFIX)]
            if texts:
                turns.append({"role": "user", "content": "\n".join(texts)})
            continue

        # For the assistant's messages, we keep the text and drop the tool calls. One turn can produce several
        # assistant messages ("Let me check..." then a tool call, then the final answer). We merge those into
        # one bubble, which is how the user saw them stream in.
        texts = [b["text"] for b in content if "text" in b]
        if not texts:
            continue
        text = scrub("\n".join(texts))
        if turns and turns[-1]["role"] == "assistant":
            turns[-1]["content"] += "\n\n" + text
        else:
            turns.append({"role": "assistant", "content": text})
    return turns

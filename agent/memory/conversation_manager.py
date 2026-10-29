"""
It stops long conversations from becoming slow and expensive, without making Navi forget what was said.

Every time Navi replies, the whole conversation so far is sent to the AI again, so longer chats cost more. This
file keeps the full conversation for the first 30 turns. After that, it keeps the most recent 12 messages exactly
as they were, and replaces everything older with a short written summary. As the chat keeps growing, the summary
is updated.

WHY IT MATTERS
Simply deleting old messages would make Navi forget things the user said earlier ("as I mentioned, we're a
partnership"). A summary keeps the important points at a fraction of the cost.
"""

import logging
from typing import TYPE_CHECKING, Any

from strands import Agent
from strands.agent.conversation_manager import ConversationManager
from strands.types.exceptions import ContextWindowOverflowException

from agent.llm import build_fast_model
from agent.prompts import CONVERSATION_SUMMARY_PROMPT

if TYPE_CHECKING:
    from strands.types.content import Message

logger = logging.getLogger(__name__)

# This tag marks the summary message we create, so it's never mistaken for something the user typed.
SUMMARY_TAG = "[conversation summary]"
ACK_TEXT = "Understood. I will continue from this summary and the messages that follow."

# Strands gives each message a tracking ID when it's added in the normal way. Our summary messages skip
# that route, so we give them an ID ourselves. Some versions of Strands don't have this helper at all, and
# in those versions it isn't needed, so we fall back to doing nothing.
try:
    from strands.types.content import _ensure_tracking_id
except ImportError:
    def _ensure_tracking_id(message: dict) -> None:  # type: ignore[misc]
        return None


# Because this builds on Strands' own ConversationManager, the agent calls our methods at exactly the
# right moments: apply_management after every turn, and reduce_context if the conversation gets too big.
# The session manager also saves our state for us. Nothing else in the code needed to change.
class RollingSummaryConversationManager(ConversationManager):
    def __init__(self, trigger_turns: int = 30, keep_recent_messages: int = 12, max_transcript_chars: int = 24000):
        # The parent class sets up removed_message_count, which Strands uses when it reloads a chat.
        super().__init__()
        # Keeping fewer than two messages could leave no complete back-and-forth after the summary.
        if keep_recent_messages < 2:
            raise ValueError("keep_recent_messages must be at least 2 (one user + one assistant message)")
        self.trigger_turns = trigger_turns
        self.keep_recent_messages = keep_recent_messages
        self.max_transcript_chars = max_transcript_chars
        # The current rolling summary, as plain text, and how many we've written (for logging and the cost report).
        self._summary_text: str | None = None
        self.summaries_made = 0

    @staticmethod
    def _is_summary(message: "Message") -> bool:
        """Check whether a message is one of our summary messages, recognised by its tag, so it isn't counted as a turn."""
        return any(SUMMARY_TAG in block.get("text", "") for block in message.get("content", []))

    @classmethod
    def _is_turn_start(cls, message: "Message") -> bool:
        """Check whether a message is a real turn: something the person actually typed.

        Bedrock sends tool results back inside user messages, so just checking "is this from the user"
        would count every tool call as a turn. Requiring some text and no tool result means we only count
        what the person really wrote.
        """
        if message.get("role") != "user" or cls._is_summary(message):
            return False
        content = message.get("content", [])
        return any("text" in b for b in content) and not any("toolResult" in b for b in content)

    def _summary_pair(self) -> list["Message"]:
        """Make the two messages that go at the very start of the history.

        The summary is a user message, because Bedrock needs the history to start with the user. The short
        assistant reply after it keeps the speakers alternating before the first kept user turn.
        """
        summary: "Message" = {"role": "user", "content": [{"text": f"{SUMMARY_TAG}\n{self._summary_text}"}]}
        ack: "Message" = {"role": "assistant", "content": [{"text": ACK_TEXT}]}
        for message in (summary, ack):
            _ensure_tracking_id(message)
        return [summary, ack]

    def _count_turns(self, messages: list["Message"]) -> int:
        """Count how many real user turns are in the history. This is what gets compared against the 30-turn limit."""
        return sum(1 for m in messages if self._is_turn_start(m))

    def _split_point(self, messages: list["Message"]) -> int:
        """Find where the word-for-word part should begin: 12 messages from the end, moved back to the start of a turn.

        Moving back (keeping more) rather than forward (keeping fewer) guarantees at least 12 messages stay
        exactly as they were. Starting at the beginning of a turn guarantees no tool call is cut off from its result.
        """
        split = len(messages) - self.keep_recent_messages
        while split > 0 and not self._is_turn_start(messages[split]):
            split -= 1
        return split

    def _transcript(self, messages: list["Message"]) -> str:
        """Turn the messages being summarised into readable text: what was said, plus short notes about tool calls.

        Each tool call becomes a one-line note (its name, its inputs and the start of its result). That way
        the summary can still record what was done, like "update_progress R01", without paying to send
        the raw data. Our old summary messages are skipped here, because the previous summary is passed in
        separately.
        """
        lines = []
        for message in messages:
            if self._is_summary(message) or message.get("content") == [{"text": ACK_TEXT}]:
                continue
            for block in message.get("content", []):
                if "text" in block:
                    lines.append(f"{message['role'].upper()}: {block['text']}")
                elif "toolUse" in block:
                    lines.append(f"TOOL CALL: {block['toolUse'].get('name')} {block['toolUse'].get('input')}")
                elif "toolResult" in block:
                    text = "".join(c.get("text", "") for c in block["toolResult"].get("content", []) if isinstance(c, dict))
                    lines.append(f"TOOL RESULT: {text[:300]}")
        return "\n".join(lines)[-self.max_transcript_chars:]

    def _summarise(self, aged_out: list["Message"]) -> str:
        """Merge the previous summary with the messages being folded in, using the cheap fast model.

        We use a brand-new agent with no tools for this, so the summariser can't call tools or touch this chat.
        """
        previous = self._summary_text or "(none yet)"
        writer = Agent(model=build_fast_model(max_tokens=700), system_prompt=CONVERSATION_SUMMARY_PROMPT,
                       callback_handler=None)
        prompt = f"PREVIOUS SUMMARY:\n{previous}\n\nNEW MESSAGES TO FOLD IN:\n{self._transcript(aged_out)}"
        return str(writer(prompt)).strip()

    def _compress(self, agent: "Agent") -> bool:
        """Summarise everything before the split point. Returns False if there's nothing to summarise."""
        messages = agent.messages
        split = self._split_point(messages)
        # If there's already a summary at the front, its two messages are part of what's being folded in.
        # They weren't real messages, so they mustn't be counted as removed originals (see below).
        had_summary = bool(messages) and self._is_summary(messages[0])
        synthetic = 2 if had_summary else 0
        # If there's nothing real to summarise (say, the whole chat is one giant turn), stop here.
        if split <= synthetic:
            return False

        aged_out = messages[:split]
        self._summary_text = self._summarise(aged_out)
        # Only count the real messages we removed. The old summary pair was never saved in the chat files.
        self.removed_message_count += len(aged_out) - synthetic
        # Swap the old messages for the summary by changing the list in place. Strands keeps hold of this
        # exact list, so if we made a new list it would simply be ignored.
        messages[:] = self._summary_pair() + messages[split:]
        self.summaries_made += 1
        logger.info("rolling summary #%d: folded %d messages, kept %d word for word",
                    self.summaries_made, len(aged_out) - synthetic, len(messages) - 2)
        return True

    def apply_management(self, agent: "Agent", **kwargs: Any) -> None:
        """Strands calls this at the end of every turn. We only summarise once the chat is past the turn limit."""
        if self._count_turns(agent.messages) > self.trigger_turns:
            try:
                self._compress(agent)
            except Exception:
                # A failed summary must never break the conversation. We keep the full history and try
                # again on the next turn.
                logger.warning("rolling summary failed; keeping full history for now", exc_info=True)

    def reduce_context(self, agent: "Agent", e: Exception | None = None, **kwargs: Any) -> None:
        """Strands calls this when the conversation is too big for the model. We summarise straight away, whatever the turn count."""
        compressed = self._compress(agent)
        if not compressed and e is not None:
            raise ContextWindowOverflowException("Cannot reduce context: nothing left to summarise") from e

    # The session manager saves whatever get_state() returns alongside the messages, and hands it back to
    # restore_from_session() when the chat is reopened. Without these two methods, restarting the server
    # after turn 30 would lose the summary and bring back only the kept messages.
    def get_state(self) -> dict[str, Any]:
        return {**super().get_state(), "summary_text": self._summary_text, "summaries_made": self.summaries_made}

    def restore_from_session(self, state: dict[str, Any]) -> list["Message"] | None:
        # The parent class restores how many saved messages Strands should skip. We then return the summary
        # pair, which gets placed in front of the messages Strands does load.
        super().restore_from_session(state)
        self._summary_text = state.get("summary_text")
        self.summaries_made = state.get("summaries_made", 0)
        return self._summary_pair() if self._summary_text else None

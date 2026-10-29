"""
It keeps conversations cheap by shrinking old search results once they've been used.

Search results are the bulkiest part of a conversation, and the whole conversation is sent to the AI again with every
reply. Once a question has been answered, the facts are already in Navi's reply, so the original search results are
no longer needed in full. After each turn, this file cuts older results down to a short note, which saves money and
time on every message after that.
"""

from typing import Any

from strands.hooks import AfterInvocationEvent, HookProvider, HookRegistry

# How much of each old result to keep: enough for the model to remember what it was about.
KEEP_CHARS = 240
# Results shorter than this are left alone, because shortening them would save almost nothing.
MIN_CHARS = 400


# This works alongside the rolling summary. Compaction trims a little after every turn, without calling a
# model, and the summary takes care of very long chats. Compaction only changes the history held in memory,
# which is why core.AgentPool keeps agents alive between messages.
class CompactionHook(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterInvocationEvent, self.compact)

    def compact(self, event: AfterInvocationEvent) -> None:
        messages = event.agent.messages
        # Find where the current turn begins: the last user message with text in it.
        turn_start = next(
            (i for i in range(len(messages) - 1, -1, -1)
             if messages[i]["role"] == "user" and any("text" in b for b in messages[i]["content"])),
            None,
        )
        # If there isn't one, or it's the very first message, this is the first turn and there's nothing older to shrink.
        if not turn_start:
            return

        # Shorten the tool results from earlier turns. The "[compacted]" label marks ones we've already
        # shortened, so they're not processed again.
        for message in messages[:turn_start]:
            for block in message.get("content", []):
                result = block.get("toolResult")
                if not result:
                    continue
                text = "".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
                if len(text) > MIN_CHARS and not text.startswith("[compacted]"):
                    result["content"] = [{"text": f"[compacted] {text[:KEEP_CHARS]}..."}]

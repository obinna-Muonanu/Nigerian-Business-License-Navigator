"""WHAT THIS FILE DOES
It lets you chat with Navi directly in a terminal window, without starting the web server or the web page.

It's mainly for testing and debugging. As well as chatting, you can type a few commands: start a new chat, see what Navi
remembers about the user, see the current chat's details, or save and quit. After each reply it shows how long it took
and how many words (tokens) it used.

HOW TO RUN IT
    python main_agent.py --user ada-ibadan                 start a new chat for this user
    python main_agent.py --user ada-ibadan --session s1    carry on an earlier chat
    python main_agent.py --user ada-ibadan --mode baseline use the version without the knowledge graph
"""

import argparse
import asyncio
import json
import uuid

from agent.core import after_turn, build_agent, stream_turn
from agent.memory import LongTermMemory


def _new_session_id() -> str:
    """Make a random chat ID that's safe to use as a folder name. The "cli-" start shows the chat came from here."""
    return f"cli-{uuid.uuid4().hex[:8]}"


async def chat_loop(user_id: str, session_id: str, mode: str) -> None:
    """Keep reading lines from the keyboard and answering them until the user quits."""
    # The command line builds the agent directly, with no server and no pool. That's handy for testing tools
    # and memory without starting FastAPI and Streamlit, and it still uses the same build_agent and
    # stream_turn as the server, so it behaves exactly the same.
    agent = build_agent(user_id, session_id, mode)
    print(f"User {user_id} | session {session_id} | mode {mode}")
    print("Commands: /new, /memory, /state, /end, /quit\n")

    while True:
        # Read one line. Ctrl+C or Ctrl+D ends the chat cleanly.
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue

        # Handle the console commands. These are never sent to the model. They make it easy to show memory
        # working: /new starts a fresh chat for the same user, /memory shows what long-term memory holds, and
        # /state shows the current chat's working state (the profile, anything waiting for a yes, and so on).
        if text == "/quit":
            break
        if text == "/end":
            after_turn(agent, force_summary=True)
            print("Session summary saved:", LongTermMemory.load(user_id).summary)
            break
        if text == "/new":
            after_turn(agent, force_summary=True)
            session_id = _new_session_id()
            agent = build_agent(user_id, session_id, mode)
            print(f"New session {session_id}. Long-term memory carried over.\n")
            continue
        if text == "/memory":
            memory = LongTermMemory.load(user_id)
            print(json.dumps({"profile": memory.profile.model_dump(exclude_none=True), "language": memory.language,
                              "summary": memory.summary, "completed": memory.completed}, indent=2))
            continue
        if text == "/state":
            print(json.dumps(agent.state.get(), indent=2, default=str))
            continue

        # Anything else is a normal message, so stream Navi's reply. Each piece is printed the moment it arrives,
        # so the terminal streams just like the UI does. The last line shows how long the turn took and how many
        # tokens it used, including how many came from the cache, which is quick proof that caching works.
        print("Navi: ", end="", flush=True)
        async for event in stream_turn(agent, text):
            if event["type"] == "text":
                print(event["text"], end="", flush=True)
            elif event["type"] == "tool":
                print(f"\n   [tool] {event['name']} ...\nNavi: ", end="", flush=True)
            elif event["type"] == "warning":
                print(f"\n   [notice] {event['text']}", end="")
            elif event["type"] == "handoff":
                print(f"\n   [handoff] ticket #{event['ticket']}", end="")
            elif event["type"] == "done":
                u = event["usage"]
                print(f"\n   [{event['latency_ms']} ms | in {u['inputTokens']} | out {u['outputTokens']} "
                      f"| cache read {u['cacheReadInputTokens']}]\n")
        # Do the same after-turn work as the server: refresh the long-term summary every few turns.
        after_turn(agent)


def main() -> None:
    """Read the command-line options and start chatting."""
    # argparse gives us a --help message for free, and makes sure --mode is one of the two allowed values.
    parser = argparse.ArgumentParser(description="License Navigator CLI")
    parser.add_argument("--user", required=True, help="Stable user ID (long-term memory key)")
    parser.add_argument("--session", default=None, help="Session ID to resume (default: new session)")
    parser.add_argument("--mode", choices=["graphrag", "baseline"], default="graphrag")
    args = parser.parse_args()
    # stream_turn is asynchronous, so the chat loop runs inside asyncio.run.
    asyncio.run(chat_loop(args.user, args.session or _new_session_id(), args.mode))


if __name__ == "__main__":
    main()

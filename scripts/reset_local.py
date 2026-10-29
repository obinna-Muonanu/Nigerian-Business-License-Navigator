"""WHAT THIS FILE DOES
It wipes the app's saved data so you can start a demo from a clean slate.

It deletes the saved chats, the logs and the user database (so all users' remembered details, progress and checklists
are gone), then creates empty folders ready to use. It always shows what it's about to delete and asks first, unless you
add --yes. It never touches the knowledge graph or the official documents.

HOW TO RUN IT
    python -m scripts.reset_local          asks before deleting
    python -m scripts.reset_local --yes    deletes without asking
"""

import argparse
import shutil

from agent.config import get_settings


def main() -> None:
    """Delete the saved chats, logs and database, after asking first unless --yes was given."""
    parser = argparse.ArgumentParser(description="Reset local runtime state")
    parser.add_argument("--yes", action="store_true", help="Delete without asking")
    args = parser.parse_args()

    # Only the folders the app recreates by itself. The knowledge base, the graph files and .env are never touched.
    s = get_settings()
    targets = [s.sessions_dir, s.logs_dir, s.runtime_dir]
    # Show exactly what's about to go and ask first, because deleted chats and memory can't be got back.
    print("This deletes:\n  " + "\n  ".join(str(t) for t in targets))
    if not args.yes and input("Continue? [y/N] ").strip().lower() != "y":
        print("Cancelled.")
        return

    # Delete each folder, then create it again empty, so the app can start writing straight away.
    for folder in targets:
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
    print("Local state cleared.")


if __name__ == "__main__":
    main()

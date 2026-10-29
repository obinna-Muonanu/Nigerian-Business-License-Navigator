"""WHAT THIS FOLDER IS
This folder is Navi itself: the AI assistant that helps people find out which business registrations,
licences and permits they need in Nigeria, in what order.

Everything Navi needs lives in here, split into small parts that each do one job:
    config.py    reads the project's settings (passwords, which AI model to use, and so on).
    prompts.py   holds the written instructions that tell the AI how to behave.
    schemas.py   describes the shape of the information we keep, like a user's business details.
    core.py      puts Navi together and runs each conversation turn.
    llm/         connects to the AI models on Amazon Bedrock.
    storage/     saves and reads information from the two databases.
    knowledge/   looks up answers in the knowledge graph and the official documents.
    memory/      remembers the current chat, and remembers each user between chats.
    tools/       the actions Navi can take, like building a checklist or setting a reminder.
    hooks/       the safety rules that check every message and every action.

This file itself does nothing except mark the folder as one package.
"""

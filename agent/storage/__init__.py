"""WHAT THIS FOLDER IS
This folder is how the project saves and reads information. It talks to two databases:

    Neo4j holds the knowledge: the knowledge graph of requirements and the official documents. Navi can
        only read from it, never change it.
    SQLite holds everything Navi writes down: users' details, their progress, saved checklists, reminders,
        and a log of every action Navi takes.

This file just marks the folder as one package.
"""

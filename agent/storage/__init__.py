"""WHAT THIS FOLDER IS
This folder is how the project saves and reads information. It talks to two databases:

    Neo4j holds the knowledge: the knowledge graph of requirements and the official documents. Navi can
        only read from it, never change it.
    The app database holds everything Navi writes down: users and their businesses, remembered facts,
        progress, saved checklists, reminders, chat history, notes about past chats, and a log of every
        action Navi takes. It's a SQLite file on your own computer and Postgres in production
        (see database.py), chosen by the DATABASE_URL setting.

This file just marks the folder as one package.
"""

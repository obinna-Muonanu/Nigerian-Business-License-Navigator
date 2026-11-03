"""WHAT THIS FOLDER IS
This folder is the web API: the server that the website talks to, and the code that checks who is signed in.

    server.py   the routes: chat (streamed), past chats, checklists, the user's data rights, and health
    auth.py     checks the Supabase sign-in pass sent with every request, and works out which user it is

Navi itself lives in agent/; this folder only receives requests, checks them, and passes them on.

HOW TO RUN IT
    uvicorn api.server:app --reload --port 8000
"""

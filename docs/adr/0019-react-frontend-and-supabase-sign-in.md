# ADR 0019: A React + TypeScript web app, with Supabase sign-in checked by the API

**Status:** Accepted · **Date:** 2026-11-01 · Replaces the Streamlit client in
[0013](0013-streaming-api-and-thin-ui.md)

## Context

Streamlit got the project to a working demo quickly, but it had two limits for a production
application.

The first was **identity**. Streamlit had no real sign-in, so the user ID was typed into a Developer
settings box, and the API trusted whatever ID it was sent. For the next demo I want to share one link
with many people at the same time and prove that nobody can see anyone else's chats or memory. With a
typed-in ID, two testers who chose the same ID would share everything, and anyone who learned another
person's ID could read their data.

The second was **control over the experience**. Streamlit reruns the whole page on every click,
styles are hard to change reliably, and it's a Python-only tool. A front end I build myself shows that
I can deliver the full stack the way real products are built.

## Decision

The web app is now a separate **React + TypeScript** project in `frontend/`, built with **Vite** and
styled with **Tailwind CSS**. It keeps every Streamlit feature: streamed replies, tool activity, the
step diagram (now drawn as SVG), warnings, hand-off notices, the chat list grouped by date, saved
checklists and reminders, sample questions, the GraphRAG/baseline switch and the technical details
line. It also adds a **My data** page where users can see, download or delete everything Navi
remembers about them.

Sign-in uses **Supabase Auth** with email and password. The browser keeps the sign-in pass (a JWT) and
sends it with every request. The API checks it in `auth.py`:

- the seal must match one of Supabase's published public keys (ES256 or RS256 only);
- the pass must not have expired;
- it must be meant for signed-in users (`aud = authenticated`) and issued by our project.

The user's ID is then taken from the pass (`sub`). No route accepts a user ID from the browser any
more: personal routes live under `/me`, chats must belong to the signed-in user, and new chat IDs are
always created by the server.

Around that, the API now:

- allows only the website's own address to call it from a browser (`ALLOWED_ORIGINS`, CORS);
- limits each user to a set number of messages a minute (`CHAT_MESSAGES_PER_MINUTE`);
- logs error details on the server instead of showing them to users;
- refuses everything except `/health` if `SUPABASE_URL` isn't set, so it can never run open by
  accident.

## Why I chose this

**React with TypeScript** is the most widely used way to build web apps, so the project reads as
professional work, and TypeScript catches mistakes before the app runs. I chose Vite rather than
Next.js because FastAPI is already the server; Next.js would add a second server layer I don't need.

**Supabase Auth** was quick to set up, uses standard JWTs that FastAPI can check without a special
library, and publishes its public keys. That means the API never needs a secret to verify a sign-in. I
first tried Clerk, which offers the same features, but its sign-up failed for me. Because the API only
depends on standard JWT checks, switching provider later would only touch `auth.py` and the sign-in
page.

**Taking identity from the token, not the request** is the important part. It's what makes it safe to
share one link with many testers: the server knows who each person is, and the browser can't claim to
be someone else.

## What I considered instead

**A random ID per browser** (no sign-in) would have been quicker, but the server would still be
trusting an ID that the browser sends, and a user would lose their memory on a new device.

**A signed cookie issued by the server** would have stopped impersonation without sign-up, but it ties
a person to one browser. It also isn't how production apps handle accounts.

**Building my own email and password system** would have meant storing passwords, resetting them and
protecting against attacks myself. That's risky, and it isn't the point of this project.

**Keeping Streamlit and adding sign-in to it** is possible, but awkward, and it wouldn't show front-end
skills.

## Consequences

Many people can now use one link at the same time, each with their own private chats and memory, and
the same person sees the same memory on any device. The project has a second part to install and
deploy (Node.js and the `frontend/` app), and two more services to configure: Supabase for sign-in, and
`ALLOWED_ORIGINS` for the deployed website's address. Supabase's built-in email service only sends a
few emails an hour, so for demos "Confirm email" is turned off; a real launch should add a proper email
provider and turn it back on. The rate limit lives in the server's memory, which is right for one
server; several servers would need a shared limit.

## Where to find it

- Sign-in check: `auth.py`; the protected routes: `server.py`
- Web app: `frontend/src/` (`App.tsx`, `components/Workspace.tsx`, `components/ChatView.tsx`,
  `components/Sidebar.tsx`, `components/MyData.tsx`, `components/DependencyGraph.tsx`, `lib/api.ts`)
- Settings: `SUPABASE_URL`, `ALLOWED_ORIGINS`, `CHAT_MESSAGES_PER_MINUTE` in `.env`; the web app's own
  settings in `frontend/.env.local` (see `frontend/.env.example`)

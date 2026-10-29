# ADR 0012: Reply in the language of each message

**Status:** Accepted · **Date:** 2026-10-27

## Context

During testing I noticed that after a single exchange in Pidgin, the agent kept answering in Pidgin
even when I went back to English. It was "sticky".

When I dug into it, there were three causes. Only Pidgin messages were being tagged, so English
messages came with no instruction at all. Long-term memory had stored "Preferred language: pidgin".
And the rolling summary had recorded the language as one of the user's preferences. So everything
the model could see was pointing it back to Pidgin.

## Decision

The agent now decides the reply language from each new message on its own: English if the message is
in English, Pidgin if it's in Pidgin, even when the user switches halfway through a conversation.

To make that work, the input guard now tags every message, not just Pidgin ones. The note says
something like "this message is in English, so reply in English, even if earlier messages were in
Pidgin", or the Pidgin version of that. I also removed the language from the memory block and from
the summary's preferences. It's still logged, but it never decides the reply.

Tool queries are always written in English, because the documents are in English. The Sources list
also stays in English, since it names official documents.

Pidgin is detected with a simple word score. Strong markers like "wetin", "abeg", "dey" and "una"
count 2 points. Weak markers that are also English words, like "na", "fit" and "o", count 1. A score
of 2 or more means the message is in Pidgin.

## Why I chose this

It's what users expect: answer me in the language I just used.

A note on the current message beats a stored preference, because a stored preference goes stale the
moment the user switches.

And the word score is free, instant and predictable. It doesn't need an extra model call.

## What I considered instead

**Remembering a "preferred language"** was exactly what caused the sticky-Pidgin bug in the first
place.

**Letting the model decide on its own** didn't work either. It tended to copy the language of its own
recent replies.

**An AI language detector** would add cost and delay for what is only a choice between two languages.

## Consequences

Switching language now works in both directions, every time. A keyword score can occasionally
misjudge a very short or mixed message, but if it does, the next message puts it right.

## Where to find it

Detection is `_is_pidgin` in `agent/hooks/input_guard.py`, which also adds the per-message note. The
language rule itself is in `agent/prompts.py`.

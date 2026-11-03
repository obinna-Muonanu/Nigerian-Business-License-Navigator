# ADR 0012: Reply in the language of each message

**Status:** Accepted · **Date:** 2026-10-27 · Updated 2026-11-01 (see "Update: can the system prompt do this alone?" below)

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

## Update (2026-11-01): can the system prompt do this alone?

I was asked whether a hook is needed at all, or whether a well-written system prompt could do the job.
So I tested it rather than guessing. First I gave the prompt its own **REPLY LANGUAGE** section near the
top, with a worked example of a conversation switching from English to Pidgin and back. Then I ran the
same live test against three setups: two conversations, 11 messages, switching language several times,
with each reply's language judged by a separate model.

| Setup | Replies in the right language |
|---|---|
| System prompt only (language note removed from the hook) | 7 / 11 |
| System prompt + a neutral note on each message ("reply in this message's language") | 9 / 11 |
| System prompt + the hook's note naming the language ("this message is in English") | 10 / 11 |
| The same, after teaching the detector Pidgin's "go + verb" future | **11 / 11** |

With the prompt alone, the old problem came straight back. Every switch from Pidgin back to English
failed, because the model copied the language of its own recent replies. A rule written once at the top
of a long prompt is weaker than that pull. A note attached to the newest message is not.

The one miss with the original hook was "How much NAFDAC registration go cost me?", which contains none
of the detector's Pidgin words. Pidgin puts "go" straight before a verb for the future ("e go cost", "e go
take"), so the detector now counts that pattern as strong evidence of Pidgin. It ignores the pattern when
"will", "to", "can", "let's" and similar words come in the two words before "go", so casual English like
"I will go take a look" or "Can I go get the forms?" is still read as English. All 46 messages in the
evaluation datasets are still classified correctly.

**Decision:** keep both. The system prompt explains the rule once, clearly and with an example. The hook
repeats it on every message and names that message's language. The detected language is no longer stored
anywhere, not in the chat state and not in the database, because each message is judged on its own.

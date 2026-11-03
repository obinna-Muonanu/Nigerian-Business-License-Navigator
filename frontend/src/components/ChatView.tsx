// The main chat area: the welcome screen for a new chat, the conversation, and the box where the user types.
//
// It only draws things. Sending messages and keeping the conversation is done by the Workspace (see Workspace.tsx),
// which passes in the messages and a `onSend` function to call.

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { DisplayMessage } from "../lib/types";
import { Logo } from "./Logo";
import { Message } from "./Message";

// These sample questions appear on every new chat, so a first-time user knows what to ask. Each one shows off a
// different skill: the ordered checklist, a fee lookup with its source, explaining why one step comes first, Pidgin,
// and handling two businesses at once.
const SAMPLE_QUESTIONS = [
  "I want to start selling packaged zobo drinks in Ibadan. What do I need, and in what order?",
  "How much is the CAC business name registration fee, and how long does it take?",
  "Why do I need the NAFDAC facility inspection before product registration?",
  "Abeg, wetin I need to open pharmacy for Lagos?",
];

interface Props {
  messages: DisplayMessage[];
  busy: boolean;
  error: string | null;
  showDetails: boolean;
  onSend: (text: string) => void;
}

export function ChatView({ messages, busy, error, showDetails, onSend }: Props) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Keep the newest part of the conversation in view as the reply streams in. An empty chat shows the welcome
  // screen, which should be read from the top, so it isn't scrolled.
  useEffect(() => {
    if (messages.length) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  // Let the typing box grow with the text, up to a limit, like a chat app.
  useEffect(() => {
    const box = inputRef.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, 200)}px`;
  }, [draft]);

  function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    onSend(trimmed);
    setDraft("");
  }

  // Enter sends the message; Shift+Enter starts a new line instead.
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send(draft);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
          {messages.length === 0 ? (
            <Welcome onPick={send} />
          ) : (
            messages.map((m) => <Message key={m.id} message={m} showDetails={showDetails} />)
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-3xl px-4 py-3">
          {error && <p className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          <div className="flex items-end gap-2 rounded-2xl border border-slate-300 bg-white px-3 py-2 focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20">
            <textarea
              ref={inputRef}
              rows={1}
              value={draft}
              maxLength={4000}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Ask Navi about registering, licensing or running your business…"
              className="max-h-[200px] flex-1 resize-none bg-transparent py-1.5 text-[15px] outline-none placeholder:text-slate-400"
            />
            <button
              onClick={() => send(draft)}
              disabled={busy || !draft.trim()}
              aria-label="Send"
              className="mb-0.5 rounded-xl bg-brand p-2 text-white transition hover:bg-brand-dark disabled:opacity-40"
            >
              <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
          <p className="mt-2 text-center text-xs text-slate-400">
            Navi can make mistakes. Confirm fees and rules with the regulator.
          </p>
        </div>
      </div>
    </div>
  );
}

// The welcome screen for an empty chat: Navi's introduction and the sample questions. It exists only on the page;
// nothing here is sent to Navi, so it costs nothing.
function Welcome({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="pt-6">
      {/* The logo and title sit side by side on one line, centred across the page. */}
      <div className="flex items-center justify-center gap-3">
        <Logo size={48} />
        <h1 className="text-2xl font-semibold text-slate-900">Business Licensing Navigator</h1>
      </div>
      <p className="mt-4 text-slate-600">
        Hello! I'm <span className="font-semibold text-brand">Navi</span>. Tell me what you sell and where, and I'll
        build your checklist of registrations, licences and permits in the right order, explain why each step comes
        first, answer fee and document questions with the official source, and keep track of your progress. You can
        ask in English or Pidgin, about one business or several.
      </p>
      <p className="mt-8 text-sm font-medium text-slate-500">Try asking</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {SAMPLE_QUESTIONS.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-left text-sm text-slate-700 transition hover:border-brand hover:bg-brand-soft"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

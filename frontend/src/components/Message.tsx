// One message in the conversation: the user's on the right, Navi's on the left with the logo.
//
// Navi's replies are written in Markdown (a simple way of marking up headings, bold text, lists and links), so they
// are turned into properly formatted text here. Under a reply, extras can appear: the dependency diagram, a
// grounding warning, a "passed to a human" notice, and, if switched on, the technical details of the turn.

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { DisplayMessage } from "../lib/types";
import { DependencyGraph } from "./DependencyGraph";
import { Logo } from "./Logo";

export function Message({ message, showDetails }: { message: DisplayMessage; showDetails: boolean }) {
  const [showGraph, setShowGraph] = useState(false);

  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-[15px] text-white">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="mt-0.5"><Logo size={30} /></div>
      <div className="min-w-0 flex-1">
        {/* While Navi is still working and hasn't written anything yet, show what it's doing. */}
        {message.pending && !message.content && (
          <p className="flex items-center gap-2 text-sm text-slate-500">
            <span className="inline-block size-2 animate-pulse rounded-full bg-brand" />
            {message.activity ?? "Thinking"}…
          </p>
        )}

        {message.content && (
          <div className="reply">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              // Links in replies (official sources) open in a new tab, so the user doesn't lose the chat.
              components={{ a: ({ ...props }) => <a {...props} target="_blank" rel="noreferrer" /> }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        )}

        {/* Once text has started, a small line still shows that Navi is busy (for example, looking something up). */}
        {message.pending && message.content && message.activity && (
          <p className="mt-2 flex items-center gap-2 text-xs text-slate-500">
            <span className="inline-block size-1.5 animate-pulse rounded-full bg-brand" />
            {message.activity}…
          </p>
        )}

        {message.graph && message.graph.nodes.length > 0 && (
          <div className="mt-3">
            <button
              onClick={() => setShowGraph(!showGraph)}
              className="text-sm font-medium text-brand hover:text-brand-dark"
            >
              {showGraph ? "Hide" : "Show"} the step diagram
            </button>
            {showGraph && <div className="mt-2"><DependencyGraph graph={message.graph} /></div>}
          </div>
        )}

        {message.warning && (
          <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            {message.warning}
          </p>
        )}

        {message.handoff && (
          <p className="mt-3 rounded-lg border border-brand/20 bg-brand-soft px-3 py-2 text-sm text-brand-dark">
            Passed to a human adviser. Your ticket number is #{message.handoff}.
          </p>
        )}

        {/* Technical details for testing: which tools ran, how long it took and how many tokens it used. */}
        {showDetails && message.usage && (
          <p className="mt-2 text-xs text-slate-400">
            {(message.tools ?? []).join(", ") || "no tools"} · {Math.round(message.latencyMs ?? 0)} ms · in{" "}
            {message.usage.inputTokens} / out {message.usage.outputTokens} / cache read{" "}
            {message.usage.cacheReadInputTokens}
          </p>
        )}
      </div>
    </div>
  );
}

// The shapes of the data the website works with. Most of them mirror what the Navi API sends back, so TypeScript
// can warn us if we ever read a field that doesn't exist.

// The events the API streams while Navi is answering (see stream_turn in agent/core.py).
export type ChatEvent =
  | { type: "session"; session_id: string }
  | { type: "text"; text: string }
  // Take back the last `chars` characters: Navi was narrating its own work ("Let me check…") just before a tool.
  | { type: "retract"; chars: number }
  | { type: "tool"; name: string }
  | { type: "warning"; text: string }
  | { type: "handoff"; ticket: number }
  | { type: "error"; text: string }
  | { type: "done"; usage: TokenUsage; latency_ms: number };

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  cacheReadInputTokens: number;
  cacheWriteInputTokens: number;
}

// One message as shown on screen. Navi's messages can carry extras that arrive after the text.
export interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean; // true while Navi is still writing this reply
  activity?: string; // what Navi is doing right now, e.g. "Building your checklist"
  tools?: string[];
  warning?: string;
  handoff?: number;
  usage?: TokenUsage;
  latencyMs?: number;
}

// One past chat in the sidebar.
export interface ChatSummary {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

// A saved checklist for one business, and a reminder.
export interface Checklist {
  business_id: string;
  label: string;
  business_type: string | null;
  state: string | null;
  steps: { id: string; name: string; status: string }[];
  updated_at: string;
}

export interface Reminder {
  id: number;
  business_id: string | null;
  label: string | null;
  requirement_id: string;
  remind_on: string;
  note: string | null;
}

// What Navi remembers, as returned by GET /me/memory.
export interface BusinessMemory {
  business_id: string;
  label: string;
  // "inactive" once it hasn't been used for months; it's kept, and comes back as soon as the user uses it again.
  status: "active" | "inactive";
  last_used_at: string | null;
  profile: Record<string, string | boolean>;
  fact_sources: Record<string, { source: string; updated_at: string }>;
  missing_for_planning: string[];
  completed_steps: { id: string; name: string }[];
}

export interface MemoryView {
  businesses: BusinessMemory[];
  recent_sessions: { session_id: string; summary: string; updated_at: string }[];
  retention: { business_inactive_days: number; business_delete_days: number };
}

export type Mode = "graphrag" | "baseline";

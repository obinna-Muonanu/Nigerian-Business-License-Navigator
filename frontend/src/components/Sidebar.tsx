// The sidebar on the left, laid out like a chat app's.
//
// From top to bottom: the logo, a "New chat" button, the user's past chats grouped by date (click one to reopen it),
// each business's saved checklist with its reminders, and at the bottom the account area: "My data", developer
// settings for testing, and sign out. The button next to the logo closes the sidebar to give the chat the whole
// screen; the menu button at the top of the chat opens it again. On a phone, the sidebar slides in over the chat.

import { useState } from "react";
import { dateGroup } from "../lib/labels";
import type { ChatSummary, Checklist, Mode, Reminder } from "../lib/types";
import { Logo } from "./Logo";

interface Props {
  // Phone: whether the sidebar is slid in over the chat. Computer: whether it's been closed to give the chat room.
  open: boolean;
  collapsed: boolean;
  onClose: () => void;
  chats: ChatSummary[];
  currentChatId: string | null;
  onNewChat: () => void;
  onOpenChat: (id: string) => void;
  checklists: Checklist[];
  reminders: Reminder[];
  view: "chat" | "data";
  onShowData: () => void;
  email: string | null;
  onSignOut: () => void;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  showDetails: boolean;
  onShowDetailsChange: (show: boolean) => void;
}

export function Sidebar(props: Props) {
  const { open, collapsed, onClose, chats, currentChatId } = props;

  // Group the chats under date headings. They arrive newest first, so each heading appears once, in order.
  const groups: { label: string; chats: ChatSummary[] }[] = [];
  for (const chat of chats) {
    const label = dateGroup(chat.updated_at);
    const last = groups[groups.length - 1];
    if (last?.label === label) last.chats.push(chat);
    else groups.push({ label, chats: [chat] });
  }

  return (
    <>
      {/* On a phone, a dark layer behind the open sidebar; tapping it closes the sidebar. */}
      {open && <div className="fixed inset-0 z-30 bg-slate-900/30 md:hidden" onClick={onClose} />}

      {/* On a computer the sidebar sits beside the chat, unless it's been closed (collapsed). On a phone it's
          hidden off-screen and slides in when opened. */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-slate-200 bg-slate-50 transition-transform md:static md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        } ${collapsed ? "md:hidden" : ""}`}
      >
        <div className="flex items-center gap-2.5 px-4 pt-4 pb-3">
          <Logo size={30} />
          {/* An empty spacer pushes the close button to the right-hand edge, now that there's no name beside the logo. */}
          <div className="flex-1" />
          <button
            onClick={onClose}
            aria-label="Close sidebar"
            title="Close sidebar"
            className="rounded-md p-1 text-slate-500 hover:bg-slate-200/70 hover:text-slate-800"
          >
            <PanelIcon />
          </button>
        </div>

        <div className="px-3">
          <button
            onClick={props.onNewChat}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand px-3 py-2 text-sm font-semibold text-white transition hover:bg-brand-dark"
          >
            <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M12 5v14M5 12h14" strokeLinecap="round" />
            </svg>
            New chat
          </button>
        </div>

        <nav className="mt-4 flex-1 overflow-y-auto px-3 pb-4">
          {chats.length === 0 && <p className="px-2 text-sm text-slate-500">Your chats will appear here.</p>}
          {groups.map((group) => (
            <div key={group.label} className="mb-3">
              <p className="px-2 pb-1 text-xs font-medium text-slate-500">{group.label}</p>
              {group.chats.map((chat) => (
                <button
                  key={chat.session_id}
                  title={chat.title}
                  onClick={() => props.onOpenChat(chat.session_id)}
                  className={`block w-full truncate rounded-lg px-2 py-1.5 text-left text-sm transition ${
                    chat.session_id === currentChatId && props.view === "chat"
                      ? "bg-brand-soft font-medium text-brand-dark"
                      : "text-slate-700 hover:bg-slate-200/60"
                  }`}
                >
                  {chat.title}
                </button>
              ))}
            </div>
          ))}

          <Checklists checklists={props.checklists} reminders={props.reminders} />
        </nav>

        <AccountArea {...props} />
      </aside>
    </>
  );
}

// The "panel" icon used for closing and opening the sidebar: a window with its left-hand strip marked.
export function PanelIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16" />
    </svg>
  );
}

// Each business's saved checklist, folded away until clicked, with its reminders underneath. With one business the
// heading stays simple; with several, each is named after its business so they're easy to tell apart.
function Checklists({ checklists, reminders }: { checklists: Checklist[]; reminders: Reminder[] }) {
  if (checklists.length === 0 && reminders.length === 0) return null;
  // Reminders are saved against a step's internal code, so we look up the step's name to show instead.
  const names = new Map(checklists.flatMap((c) => c.steps.map((s) => [s.id, s.name] as const)));
  const several = checklists.length > 1;
  const reminderText = (r: Reminder) =>
    `${r.remind_on}: ${names.get(r.requirement_id) ?? "a step on your checklist"}${r.note ? ` (${r.note})` : ""}`;
  const listed = new Set(checklists.map((c) => c.business_id));
  const unlisted = reminders.filter((r) => !r.business_id || !listed.has(r.business_id));

  return (
    <div className="mt-2 border-t border-slate-200 pt-3">
      <p className="px-2 pb-1 text-xs font-medium text-slate-500">Saved checklists</p>
      {checklists.map((c) => (
        <details key={c.business_id} className="group rounded-lg px-2 py-1">
          <summary className="cursor-pointer list-none text-sm text-slate-700 hover:text-slate-900">
            <span className="mr-1 inline-block transition group-open:rotate-90">›</span>
            {several ? c.label : "Your checklist"} <span className="text-slate-400">({c.steps.length} steps)</span>
          </summary>
          <ol className="mt-1 list-decimal space-y-0.5 pl-6 text-xs text-slate-600">
            {c.steps.map((s) => <li key={s.id}>{s.name}</li>)}
          </ol>
          {reminders.filter((r) => r.business_id === c.business_id).map((r) => (
            <p key={r.id} className="mt-1 rounded bg-amber-50 px-2 py-1 text-xs text-amber-800">⏰ {reminderText(r)}</p>
          ))}
        </details>
      ))}
      {unlisted.map((r) => (
        <p key={r.id} className="mt-1 rounded bg-amber-50 px-2 py-1 text-xs text-amber-800">
          ⏰ {reminderText(r)}{several && r.label ? ` · ${r.label}` : ""}
        </p>
      ))}
    </div>
  );
}

// The bottom of the sidebar: who's signed in, "My data", the testing settings, and sign out.
function AccountArea(props: Props) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  return (
    <div className="border-t border-slate-200 p-3 text-sm">
      <button
        onClick={props.onShowData}
        className={`block w-full rounded-lg px-2 py-1.5 text-left transition ${
          props.view === "data" ? "bg-brand-soft font-medium text-brand-dark" : "text-slate-700 hover:bg-slate-200/60"
        }`}
      >
        My data
      </button>

      <button
        onClick={() => setSettingsOpen(!settingsOpen)}
        className="block w-full rounded-lg px-2 py-1.5 text-left text-slate-700 hover:bg-slate-200/60"
      >
        Developer settings {settingsOpen ? "▾" : "▸"}
      </button>
      {/* Testing controls. "Baseline" is the vector-only version of Navi used in the key experiment; each mode
          keeps its own list of chats. "Show technical details" adds tools, timing and tokens under each reply. */}
      {settingsOpen && (
        <div className="mx-2 mb-2 space-y-2 rounded-lg bg-white p-2 text-xs text-slate-600 ring-1 ring-slate-200">
          <div className="flex gap-1">
            {(["graphrag", "baseline"] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => props.onModeChange(m)}
                className={`flex-1 rounded-md px-2 py-1 ${props.mode === m ? "bg-brand text-white" : "bg-slate-100 hover:bg-slate-200"}`}
              >
                {m === "graphrag" ? "GraphRAG" : "Baseline"}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={props.showDetails}
              onChange={(e) => props.onShowDetailsChange(e.target.checked)}
              className="accent-brand"
            />
            Show technical details
          </label>
        </div>
      )}

      <div className="mt-1 flex items-center justify-between gap-2 px-2 pt-2">
        <span className="truncate text-xs text-slate-500" title={props.email ?? ""}>{props.email}</span>
        <button onClick={props.onSignOut} className="shrink-0 text-xs font-medium text-slate-600 hover:text-slate-900">
          Sign out
        </button>
      </div>
    </div>
  );
}

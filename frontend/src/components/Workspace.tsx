// The signed-in part of the website: the sidebar plus either the chat or the "My data" page.
//
// This is where the conversation is kept and where messages are sent. When the user sends a message, it is added to
// the screen straight away, followed by an empty reply from Navi that fills in as the answer streams back from the
// API. Extras that arrive along the way (what Navi is doing, a warning, a hand-off ticket) are
// attached to that same reply. After each reply, the sidebar is refreshed, because Navi may have saved a checklist
// or a new chat may need to appear in the list.

import { useCallback, useEffect, useState } from "react";
import { ApiError, api, streamChat } from "../lib/api";
import { TOOL_ACTIVITY } from "../lib/labels";
import { supabase } from "../lib/supabase";
import type { ChatEvent, ChatSummary, Checklist, DisplayMessage, Mode, Reminder } from "../lib/types";
import { ChatView } from "./ChatView";
import { Logo } from "./Logo";
import { MyData } from "./MyData";
import { PanelIcon, Sidebar } from "./Sidebar";

// A short random ID for each message on screen, so React can keep track of which is which.
const newId = () => Math.random().toString(36).slice(2);

export function Workspace({ email }: { email: string | null }) {
  // Which version of Navi to talk to, and which page is showing.
  const [mode, setMode] = useState<Mode>("graphrag");
  const [view, setView] = useState<"chat" | "data">("chat");
  // The open chat. A brand-new chat has no ID until the server creates one with the first message.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // What the sidebar shows.
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [checklists, setChecklists] = useState<Checklist[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  // The sidebar has two separate switches. On a phone it's hidden until opened (sidebarOpen). On a computer it's
  // shown unless the user closes it (sidebarCollapsed). That choice is remembered in this browser, so it stays the
  // way the user left it; if the browser won't allow saving, it simply starts open.
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem("navi.sidebarCollapsed") === "1";
    } catch {
      return false;
    }
  });
  const isPhone = () => window.matchMedia("(max-width: 767px)").matches;
  const rememberCollapsed = (value: boolean) => {
    setSidebarCollapsed(value);
    try {
      localStorage.setItem("navi.sidebarCollapsed", value ? "1" : "0");
    } catch {
      // Saving the preference is a nice-to-have; the sidebar still works without it.
    }
  };
  // The close button inside the sidebar, and the open button in the top bar, work on either size of screen.
  const hideSidebar = () => (isPhone() ? setSidebarOpen(false) : rememberCollapsed(true));
  const showSidebar = () => (isPhone() ? setSidebarOpen(true) : rememberCollapsed(false));
  const [showDetails, setShowDetails] = useState(false);

  // A "please sign in" answer means the sign-in has ended, so sign out and go back to the sign-in page.
  // Anything else is shown to the user as a message.
  const handleError = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 401) {
      supabase.auth.signOut();
      return;
    }
    setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
  }, []);

  // Reload the chat list and the saved checklists. They're loaded side by side to save time.
  const refreshSidebar = useCallback(async () => {
    try {
      const [chatList, saved] = await Promise.all([
        api.get<{ sessions: ChatSummary[] }>(`/sessions?mode=${mode}`),
        api.get<{ checklists: Checklist[]; reminders: Reminder[] }>("/me/checklist"),
      ]);
      setChats(chatList.sessions);
      setChecklists(saved.checklists);
      setReminders(saved.reminders);
    } catch (err) {
      handleError(err);
    }
  }, [mode, handleError]);

  useEffect(() => {
    refreshSidebar();
  }, [refreshSidebar]);

  // Tell the server the current chat is over, so its note (episodic memory) is written now. An empty chat has
  // nothing to note. If this fails, it doesn't matter: the user must always be able to move on.
  function endCurrentChat() {
    if (sessionId && messages.length) {
      api.post(`/sessions/${encodeURIComponent(sessionId)}/end?mode=${mode}`).catch(() => undefined);
    }
  }

  function newChat() {
    endCurrentChat();
    setSessionId(null);
    setMessages([]);
    setError(null);
    setView("chat");
    setSidebarOpen(false);
  }

  async function openChat(id: string) {
    setSidebarOpen(false);
    setView("chat");
    if (id === sessionId) return;
    endCurrentChat();
    try {
      const data = await api.get<{ messages: { role: "user" | "assistant"; content: string }[] }>(
        `/sessions/${encodeURIComponent(id)}/messages`,
      );
      // Reopened chats come back as text only; their notices weren't saved, so they aren't shown again.
      setMessages(data.messages.map((m) => ({ id: newId(), role: m.role, content: m.content })));
      setSessionId(id);
      setError(null);
    } catch (err) {
      handleError(err);
    }
  }

  function changeMode(next: Mode) {
    if (next === mode) return;
    // Each mode keeps its own chats, so switching starts a fresh chat.
    newChat();
    setMode(next);
  }

  async function send(text: string) {
    setError(null);
    const replyId = newId();
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: "user", content: text },
      { id: replyId, role: "assistant", content: "", pending: true, activity: "Thinking" },
    ]);
    setBusy(true);

    // Change just Navi's reply that's being written, leaving the rest of the conversation alone.
    const updateReply = (change: (m: DisplayMessage) => DisplayMessage) =>
      setMessages((prev) => prev.map((m) => (m.id === replyId ? change(m) : m)));

    // Navi sometimes writes a sentence, uses a tool, then carries on writing. Without a break, the two pieces would
    // run together ("…for each.Now let me…"), so text that follows a tool starts a new paragraph.
    let toolSinceText = false;

    // What to do with each piece of the reply as it arrives.
    const onEvent = (event: ChatEvent) => {
      switch (event.type) {
        case "session":
          setSessionId(event.session_id);
          break;
        case "text": {
          const newParagraph = toolSinceText;
          toolSinceText = false;
          updateReply((m) => ({
            ...m,
            content: m.content + (newParagraph && m.content ? "\n\n" : "") + event.text,
            activity: undefined,
          }));
          break;
        }
        case "retract":
          // Remove the narration line. The status line ("Building your checklist…") shows instead.
          updateReply((m) => ({ ...m, content: m.content.slice(0, Math.max(0, m.content.length - event.chars)).trimEnd() }));
          break;
        case "tool":
          toolSinceText = true;
          updateReply((m) => ({
            ...m,
            tools: [...(m.tools ?? []), event.name],
            activity: TOOL_ACTIVITY[event.name] ?? "Working",
          }));
          break;
        case "warning":
          updateReply((m) => ({ ...m, warning: event.text }));
          break;
        case "handoff":
          updateReply((m) => ({ ...m, handoff: event.ticket }));
          break;
        case "error":
          updateReply((m) => ({ ...m, content: `${m.content}\n\n⚠️ ${event.text}` }));
          break;
        case "done":
          updateReply((m) => ({ ...m, usage: event.usage, latencyMs: event.latency_ms }));
          break;
      }
    };

    try {
      await streamChat({ session_id: sessionId, message: text, mode }, onEvent);
    } catch (err) {
      // If nothing arrived at all (for example, too many messages a minute), say so in Navi's reply.
      const message = err instanceof Error ? err.message : "Something went wrong.";
      updateReply((m) => ({ ...m, content: m.content || `⚠️ ${message}` }));
      handleError(err);
    } finally {
      updateReply((m) => ({ ...m, pending: false, activity: undefined }));
      setBusy(false);
      refreshSidebar();
    }
  }

  return (
    <div className="flex h-full">
      <Sidebar
        open={sidebarOpen}
        collapsed={sidebarCollapsed}
        onClose={hideSidebar}
        chats={chats}
        currentChatId={sessionId}
        onNewChat={newChat}
        onOpenChat={openChat}
        checklists={checklists}
        reminders={reminders}
        view={view}
        onShowData={() => {
          setView("data");
          setSidebarOpen(false);
        }}
        email={email}
        onSignOut={() => supabase.auth.signOut()}
        mode={mode}
        onModeChange={changeMode}
        showDetails={showDetails}
        onShowDetailsChange={setShowDetails}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {/* When the sidebar is out of sight (always on a phone; on a computer only after it's been closed), a top
            bar with a button to open it again takes its place. */}
        <div
          className={`flex items-center gap-3 border-b border-slate-200 px-4 py-2.5 ${sidebarCollapsed ? "" : "md:hidden"}`}
        >
          <button onClick={showSidebar} aria-label="Open sidebar" title="Open sidebar"
                  className="rounded-md p-1 text-slate-600 hover:bg-slate-100 hover:text-slate-900">
            <PanelIcon />
          </button>
          <Logo size={26} />
          <span className="font-semibold">License Navigator</span>
        </div>

        <div className="min-h-0 flex-1">
          {view === "chat" ? (
            <ChatView messages={messages} busy={busy} error={error} showDetails={showDetails} onSend={send} />
          ) : (
            <MyData
              onChanged={refreshSidebar}
              onDeletedAll={() => {
                setSessionId(null);
                setMessages([]);
                refreshSidebar();
              }}
            />
          )}
        </div>
      </main>
    </div>
  );
}

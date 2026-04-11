"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { v4 as uuidv4 } from "uuid";
import {
  sendMessage,
  getChatHistory,
  getChatSessions,
  acceptPlan,
  type AuthUser,
  type ChatMessage,
  type ChatSession,
  type RagSource,
} from "@/src/services/api";
import ChatBubble from "@/src/components/ChatBubble";
import MealPlanCard from "@/src/components/MealPlanCard";
import AcceptModifyPanel from "@/src/components/AcceptModifyPanel";

type MessageEntry = ChatMessage & {
  id: string;
  planProposed?: boolean;
  proposedPlan?: Record<string, unknown> | null;
  planAccepted?: boolean;
  planConfirmation?: string;
  ragSources?: RagSource[];
};

function formatSessionDate(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function ChatPage() {
  const router = useRouter();
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const [user, setUser] = useState<AuthUser | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string>(() => uuidv4());
  const [messages, setMessages] = useState<MessageEntry[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [acceptingId, setAcceptingId] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Auth guard
  useEffect(() => {
    const token = localStorage.getItem("nutribot_token");
    const userData = localStorage.getItem("nutribot_user");
    if (!token || !userData) { router.replace("/login"); return; }
    const parsed: AuthUser = JSON.parse(userData);
    if (!parsed.profile_complete) { router.replace("/profile"); return; }
    setUser(parsed);
  }, [router]);

  // Load session list from backend
  const refreshSessions = useCallback(async () => {
    try {
      const data = await getChatSessions();
      setSessions(data.sessions);
    } catch {
      // silently ignore
    }
  }, []);

  useEffect(() => {
    if (user) refreshSessions();
  }, [user, refreshSessions]);

  // Load messages for the active session
  const loadSession = useCallback(async (sessionId: string, currentUser: AuthUser) => {
    setLoadingHistory(true);
    try {
      const data = await getChatHistory(sessionId);
      const loaded: MessageEntry[] = data.messages.map((m) => ({ ...m, id: uuidv4() }));
      if (loaded.length === 0) {
        setMessages([{
          id: uuidv4(),
          role: "assistant",
          content: `Hi ${currentUser.full_name.split(" ")[0]}! 👋 I'm ${currentUser.bot_name}, your personal nutrition companion. How can I help you today?`,
          timestamp: new Date().toISOString(),
        }]);
      } else {
        setMessages(loaded);
      }
    } catch {
      setMessages([{
        id: uuidv4(),
        role: "assistant",
        content: `Hi ${currentUser.full_name.split(" ")[0]}! 👋 I'm ${currentUser.bot_name}, your personal nutrition companion. How can I help you today?`,
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    if (user) loadSession(activeSessionId, user);
  }, [user, activeSessionId, loadSession]);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function startNewChat() {
    setActiveSessionId(uuidv4());
    setMessages([]);
    inputRef.current?.focus();
  }

  function switchSession(sessionId: string) {
    if (sessionId === activeSessionId) return;
    setActiveSessionId(sessionId);
    setMessages([]);
  }

  async function send() {
    const text = input.trim();
    if (!text || loading || !user) return;

    const userMsg: MessageEntry = {
      id: uuidv4(),
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await sendMessage(user.id, activeSessionId, text);
      const botMsg: MessageEntry = {
        id: uuidv4(),
        role: "assistant",
        content: res.response,
        timestamp: new Date().toISOString(),
        planProposed: res.plan_proposed,
        proposedPlan: res.proposed_plan,
        ragSources: res.rag_sources,
      };
      setMessages((prev) => [...prev, botMsg]);
      // Refresh sidebar session list after first message
      refreshSessions();
    } catch {
      setMessages((prev) => [...prev, {
        id: uuidv4(),
        role: "assistant",
        content: "Sorry, something went wrong. Please try again.",
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  async function handleAcceptPlan(msgId: string, plan: Record<string, unknown>) {
    if (!user) return;
    setAcceptingId(msgId);
    try {
      const planDays = (plan.days as unknown[]) ?? [];
      const calorieTarget = (plan.calorie_target as number) ?? 0;
      const summary = `${planDays.length}-day plan, ${calorieTarget} kcal/day`;
      const res = await acceptPlan(user.id, activeSessionId, plan, calorieTarget, summary);
      setMessages((prev) =>
        prev.map((m) => m.id === msgId ? { ...m, planAccepted: true, planConfirmation: res.message } : m)
      );
    } catch {
      alert("Failed to save plan. Please try again.");
    } finally {
      setAcceptingId(null);
    }
  }

  function handleModifyPlan() {
    setInput("Please modify the plan — ");
    inputRef.current?.focus();
  }

  function handleSignOut() {
    localStorage.removeItem("nutribot_token");
    localStorage.removeItem("nutribot_user");
    router.push("/login");
  }

  if (!user) return null;

  return (
    <div className="flex h-screen bg-background overflow-hidden">

      {/* ── Sidebar ── */}
      <aside
        className={`flex-shrink-0 flex flex-col bg-surface border-r border-border transition-all duration-300 overflow-hidden
          ${sidebarOpen ? "w-64" : "w-0"}`}
      >
        {/* Sidebar header */}
        <div className="flex items-center justify-between px-3 py-3 border-b border-border flex-shrink-0">
          <span className="text-sm font-semibold text-text truncate">Chats</span>
          <button
            onClick={startNewChat}
            className="w-7 h-7 flex items-center justify-center rounded-lg bg-primary/10 hover:bg-primary/20 text-primary transition-colors"
            title="New chat"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          </button>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto py-1">
          {/* Active (unsaved) session shown at top if not in list */}
          {!sessions.find((s) => s.session_id === activeSessionId) && (
            <button
              className="w-full text-left px-3 py-2.5 rounded-lg mx-1 bg-primary/10 border border-primary/30"
              style={{ width: "calc(100% - 8px)" }}
            >
              <p className="text-xs font-medium text-primary truncate">New conversation</p>
              <p className="text-xs text-muted mt-0.5">Just now</p>
            </button>
          )}

          {sessions.length === 0 && (
            <p className="text-xs text-muted text-center mt-6 px-3">No previous chats yet</p>
          )}

          {sessions.map((session) => (
            <button
              key={session.session_id}
              onClick={() => switchSession(session.session_id)}
              className={`w-full text-left px-3 py-2.5 rounded-lg mx-1 transition-colors hover:bg-panel
                ${activeSessionId === session.session_id ? "bg-primary/10 border border-primary/30" : ""}
              `}
              style={{ width: "calc(100% - 8px)" }}
            >
              <p className={`text-xs font-medium truncate ${activeSessionId === session.session_id ? "text-primary" : "text-text"}`}>
                {session.preview || "New conversation"}
              </p>
              <p className="text-xs text-muted mt-0.5">{formatSessionDate(session.started_at)}</p>
            </button>
          ))}
        </div>

        {/* Sidebar footer */}
        <div className="flex-shrink-0 px-3 py-3 border-t border-border">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-primary text-xs font-bold flex-shrink-0">
              {user.full_name[0].toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-text truncate">{user.full_name}</p>
              <p className="text-xs text-muted truncate">{user.email}</p>
            </div>
          </div>
        </div>
      </aside>

      {/* ── Main chat area ── */}
      <div className="flex flex-col flex-1 min-w-0">

        {/* Header */}
        <header className="flex-shrink-0 flex items-center justify-between px-4 py-3 bg-surface border-b border-border">
          <div className="flex items-center gap-3">
            {/* Sidebar toggle */}
            <button
              onClick={() => setSidebarOpen((o) => !o)}
              className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-panel transition-colors text-muted hover:text-text"
              title={sidebarOpen ? "Close sidebar" : "Open sidebar"}
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>

            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-background text-sm font-bold">
              {user.bot_name[0].toUpperCase()}
            </div>
            <div>
              <p className="text-sm font-semibold text-text">{user.bot_name}</p>
              <p className="text-xs text-muted">Your AI nutrition companion</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={startNewChat}
              className="hidden sm:flex items-center gap-1.5 text-xs text-muted border border-border rounded-lg px-3 py-1.5 hover:text-text hover:border-primary transition-colors"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              New Chat
            </button>
            <button
              onClick={handleSignOut}
              className="text-xs text-muted hover:text-text border border-border rounded-lg px-3 py-1.5 transition-colors"
            >
              Sign out
            </button>
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-1">
          {loadingHistory ? (
            <div className="flex items-center justify-center h-32">
              <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <div key={msg.id}>
                  <ChatBubble
                    role={msg.role}
                    content={msg.content}
                    botName={user.bot_name}
                    timestamp={msg.timestamp}
                    ragSources={msg.ragSources}
                  />
                  {msg.planProposed && msg.proposedPlan && (
                    <div className="ml-10 mt-2 mb-2">
                      <MealPlanCard plan={msg.proposedPlan as Parameters<typeof MealPlanCard>[0]["plan"]} />
                      <AcceptModifyPanel
                        onAccept={() => handleAcceptPlan(msg.id, msg.proposedPlan!)}
                        onModify={handleModifyPlan}
                        loading={acceptingId === msg.id}
                        accepted={msg.planAccepted}
                        confirmationMessage={msg.planConfirmation}
                      />
                    </div>
                  )}
                </div>
              ))}

              {loading && (
                <div className="flex items-end gap-2 mb-4">
                  <div className="w-8 h-8 rounded-full bg-panel border border-border flex items-center justify-center text-primary text-sm font-bold">
                    {user.bot_name[0].toUpperCase()}
                  </div>
                  <div className="bg-panel border border-border rounded-2xl rounded-bl-sm px-4 py-3">
                    <div className="flex gap-1">
                      {[0, 1, 2].map((i) => (
                        <span key={i} className="w-1.5 h-1.5 bg-muted rounded-full animate-bounce"
                          style={{ animationDelay: `${i * 0.15}s` }} />
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input area */}
        <div className="flex-shrink-0 px-4 py-4 bg-surface border-t border-border">
          <div className="flex gap-2 mb-3 overflow-x-auto pb-1">
            {[
              "Generate a 7-day meal plan",
              "Calculate my calories",
              "What's a healthy breakfast for my condition?",
              "Give me a daily routine",
            ].map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => setInput(suggestion)}
                className="flex-shrink-0 text-xs text-muted border border-border bg-panel rounded-full px-3 py-1.5
                  hover:text-text hover:border-primary transition-colors"
              >
                {suggestion}
              </button>
            ))}
          </div>

          <div className="flex gap-3 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Message ${user.bot_name}…`}
              rows={1}
              className="flex-1 bg-panel border border-border rounded-2xl px-4 py-3 text-text text-sm
                placeholder:text-muted focus:outline-none focus:border-primary transition-colors resize-none
                min-h-[44px] max-h-32 overflow-y-auto"
              style={{ height: "auto" }}
              onInput={(e) => {
                const t = e.target as HTMLTextAreaElement;
                t.style.height = "auto";
                t.style.height = `${Math.min(t.scrollHeight, 128)}px`;
              }}
            />
            <button
              onClick={send}
              disabled={loading || !input.trim()}
              className="w-11 h-11 bg-primary text-background rounded-2xl flex items-center justify-center
                hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

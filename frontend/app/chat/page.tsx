"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { v4 as uuidv4 } from "uuid";
import { motion } from "framer-motion";
import Magnetic from "@/src/components/motion/Magnetic";
import {
  sendMessageStream,
  getChatHistory,
  getChatSessions,
  deleteSession,
  acceptPlan,
  type AuthUser,
  type ChatMessage,
  type ChatSession,
  type RagSource,
} from "@/src/services/api";
import { isVoiceAvailable, startListening, SpeechError, type ListeningSession } from "@/src/services/speech";
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
  /** Spoken-input locale ("hi-IN") for a user message that came from the mic. */
  spokenLocale?: string;
  /** What the assistant understood, when the message was translated. */
  understoodAs?: string | null;
};

const LOCALE_LABELS: Record<string, string> = {
  en: "English", hi: "Hindi", ml: "Malayalam", ta: "Tamil", te: "Telugu",
  kn: "Kannada", mr: "Marathi", bn: "Bengali", gu: "Gujarati", fr: "French",
  es: "Spanish", de: "German", ar: "Arabic",
};

function languageLabel(locale?: string | null): string | undefined {
  if (!locale) return undefined;
  const code = locale.split("-")[0].toLowerCase();
  return LOCALE_LABELS[code] ?? locale;
}

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
  const [progressLabel, setProgressLabel] = useState<string | null>(null);
  const [acceptingId, setAcceptingId] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Voice input. `voiceAvailable` is null until the server has been asked
  // whether it's configured; the mic button only renders once it says yes.
  const [voiceAvailable, setVoiceAvailable] = useState<boolean | null>(null);
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const voiceSessionRef = useRef<ListeningSession | null>(null);
  // Locale of the transcript currently sitting in the input box, if it came
  // from the mic. Cleared when the user edits the text or sends it.
  const [spokenLocale, setSpokenLocale] = useState<string | undefined>(undefined);

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

  useEffect(() => {
    if (user) isVoiceAvailable().then(setVoiceAvailable);
  }, [user]);

  // Release the microphone if the page is left mid-dictation.
  useEffect(() => {
    return () => {
      voiceSessionRef.current?.stop().catch(() => {});
    };
  }, []);

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

  async function handleDeleteSession(sessionId: string, preview: string) {
    const label = preview || "New conversation";
    if (!window.confirm(`Delete "${label}"? This can't be undone.`)) return;
    try {
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (sessionId === activeSessionId) startNewChat();
    } catch {
      alert("Failed to delete the chat. Please try again.");
    }
  }

  async function send() {
    const text = input.trim();
    if (!text || loading || !user) return;

    const locale = spokenLocale;
    const userMsgId = uuidv4();
    const userMsg: MessageEntry = {
      id: userMsgId,
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
      spokenLocale: locale,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSpokenLocale(undefined);
    setVoiceError(null);
    setLoading(true);
    setProgressLabel(null);

    try {
      const res = await sendMessageStream(
        user.id,
        activeSessionId,
        text,
        (label) => setProgressLabel(label),
        locale
      );
      if (res.message_english) {
        setMessages((prev) =>
          prev.map((m) => (m.id === userMsgId ? { ...m, understoodAs: res.message_english } : m))
        );
      }
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
      setProgressLabel(null);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  // Click once to start listening, click again to stop -- the recognizer
  // stays open across pauses in speech and accumulates each phrase, so a
  // mid-sentence pause to think no longer cuts the dictation short.
  async function handleVoice() {
    if (loading) return;

    if (listening) {
      const session = voiceSessionRef.current;
      voiceSessionRef.current = null;
      setListening(false);
      if (!session) return;
      try {
        const result = await session.stop();
        // Append to whatever is already typed so a user can dictate in parts;
        // they review the transcript before sending.
        setInput((prev) => (prev.trim() ? `${prev.trim()} ${result.text}` : result.text));
        setSpokenLocale(result.locale);
        inputRef.current?.focus();
      } catch (err) {
        if (err instanceof SpeechError) {
          setVoiceError(err.message);
          if (err.code === "not_configured") setVoiceAvailable(false);
        } else {
          setVoiceError("Voice input failed. Please try again.");
        }
      }
      return;
    }

    setVoiceError(null);
    try {
      voiceSessionRef.current = await startListening();
      setListening(true);
    } catch (err) {
      if (err instanceof SpeechError) {
        setVoiceError(err.message);
        if (err.code === "not_configured") setVoiceAvailable(false);
      } else {
        setVoiceError("Voice input failed. Please try again.");
      }
    }
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
            className="w-7 h-7 flex items-center justify-center rounded-lg bg-primary/10 hover:bg-primary/20 text-ink transition-colors"
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
              <p className="text-xs font-medium text-ink truncate">New conversation</p>
              <p className="text-xs text-muted mt-0.5">Just now</p>
            </button>
          )}

          {sessions.length === 0 && (
            <p className="text-xs text-muted text-center mt-6 px-3">No previous chats yet</p>
          )}

          {sessions.map((session) => (
            <div
              key={session.session_id}
              className={`group relative mx-1 rounded-lg transition-colors hover:bg-panel
                ${activeSessionId === session.session_id ? "bg-primary/10 border border-primary/30" : ""}
              `}
              style={{ width: "calc(100% - 8px)" }}
            >
              <button
                onClick={() => switchSession(session.session_id)}
                className="w-full text-left px-3 py-2.5 pr-8"
              >
                <p className={`text-xs font-medium truncate ${activeSessionId === session.session_id ? "text-ink" : "text-text"}`}>
                  {session.preview || "New conversation"}
                </p>
                <p className="text-xs text-muted mt-0.5">{formatSessionDate(session.started_at)}</p>
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleDeleteSession(session.session_id, session.preview); }}
                title="Delete this chat"
                aria-label="Delete this chat"
                className="absolute right-1.5 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded-md
                  text-muted opacity-0 group-hover:opacity-100 hover:text-red-600 hover:bg-red-100 transition-all"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M6 7h12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m2 0v13a1 1 0 01-1 1H8a1 1 0 01-1-1V7h10z" />
                </svg>
              </button>
            </div>
          ))}
        </div>

        {/* Sidebar footer */}
        <div className="flex-shrink-0 px-3 py-3 border-t border-border space-y-1">
          <button
            onClick={() => router.push("/documents")}
            title="Medical documents"
            className="w-full flex items-center gap-2 rounded-lg px-1 py-1.5 hover:bg-panel transition-colors text-left"
          >
            <div className="w-7 h-7 rounded-full bg-panel border border-border flex items-center justify-center flex-shrink-0">
              <svg className="w-3.5 h-3.5 text-ink" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <p className="flex-1 text-xs font-medium text-text truncate">Medical documents</p>
          </button>
          <button
            onClick={() => router.push("/profile")}
            title="Edit your profile"
            className="w-full flex items-center gap-2 rounded-lg px-1 py-1 hover:bg-panel transition-colors text-left"
          >
            <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-ink text-xs font-bold flex-shrink-0">
              {user.full_name[0].toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-text truncate">{user.full_name}</p>
              <p className="text-xs text-muted truncate">{user.email}</p>
            </div>
            <svg className="w-4 h-4 text-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536M4 20h4l10.5-10.5a2.5 2.5 0 00-3.536-3.536L4 16v4z" />
            </svg>
          </button>
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

            <button
              onClick={() => router.push("/profile?step=3")}
              title="Rename your assistant"
              className="flex items-center gap-3 rounded-lg px-1 py-0.5 hover:bg-panel transition-colors text-left"
            >
              <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-text text-sm font-bold">
                {user.bot_name[0].toUpperCase()}
              </div>
              <div>
                <p className="text-sm font-semibold text-text">{user.bot_name}</p>
                <p className="text-xs text-muted">Your AI nutrition companion · rename</p>
              </div>
            </button>
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
                <motion.div
                  key={msg.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                >
                  <ChatBubble
                    role={msg.role}
                    content={msg.content}
                    botName={user.bot_name}
                    timestamp={msg.timestamp}
                    ragSources={msg.ragSources}
                    spokenLanguage={languageLabel(msg.spokenLocale)}
                    understoodAs={msg.understoodAs ?? undefined}
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
                </motion.div>
              ))}

              {loading && (
                <div className="flex items-end gap-2 mb-4">
                  <div className="w-8 h-8 rounded-full bg-panel border border-border flex items-center justify-center text-ink text-sm font-bold">
                    {user.bot_name[0].toUpperCase()}
                  </div>
                  <div className="bg-panel border border-border rounded-2xl rounded-bl-sm px-4 py-3 flex items-center gap-2">
                    <div className="flex gap-1">
                      {[0, 1, 2].map((i) => (
                        <span key={i} className="w-1.5 h-1.5 bg-muted rounded-full animate-bounce"
                          style={{ animationDelay: `${i * 0.15}s` }} />
                      ))}
                    </div>
                    {progressLabel && <span className="text-xs text-muted">{progressLabel}…</span>}
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

          {(voiceError || spokenLocale) && (
            <div className="flex items-center gap-2 mb-2 text-xs">
              {voiceError ? (
                <span className="text-red-600">{voiceError}</span>
              ) : (
                <span className="text-muted">
                  🎤 Heard in <span className="text-ink">{languageLabel(spokenLocale)}</span> — review, then send
                </span>
              )}
            </div>
          )}

          <div className="flex gap-3 items-end">
            {voiceAvailable && (
              <button
                onClick={handleVoice}
                disabled={loading}
                title={listening ? "Listening… click to stop" : "Speak your message"}
                aria-label={listening ? "Listening, click to stop" : "Speak your message"}
                className={`w-11 h-11 rounded-2xl flex items-center justify-center flex-shrink-0 border transition-colors
                  ${listening
                    ? "bg-red-500/20 border-red-500 text-red-600 animate-pulse"
                    : "bg-panel border-border text-muted hover:text-ink hover:border-primary"}
                  disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 15a3 3 0 003-3V6a3 3 0 00-6 0v6a3 3 0 003 3zm5-3a5 5 0 01-10 0M12 17v4m-4 0h8" />
                </svg>
              </button>
            )}
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => { setInput(e.target.value); if (spokenLocale) setSpokenLocale(undefined); }}
              onKeyDown={handleKeyDown}
              placeholder={listening ? "Listening…" : `Message ${user.bot_name}…`}
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
            <Magnetic strength={10} className="flex-shrink-0">
              <button
                onClick={send}
                disabled={loading || !input.trim()}
                className="w-11 h-11 bg-primary text-text rounded-2xl flex items-center justify-center
                  hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              </button>
            </Magnetic>
          </div>
        </div>
      </div>
    </div>
  );
}

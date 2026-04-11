"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { v4 as uuidv4 } from "uuid";
import {
  sendMessage,
  getChatHistory,
  acceptPlan,
  type AuthUser,
  type ChatMessage,
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
};

export default function ChatPage() {
  const router = useRouter();
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const [user, setUser] = useState<AuthUser | null>(null);
  const [sessionId] = useState<string>(() => uuidv4());
  const [messages, setMessages] = useState<MessageEntry[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [acceptingId, setAcceptingId] = useState<string | null>(null);

  // Auth guard + load profile
  useEffect(() => {
    const token = localStorage.getItem("nutribot_token");
    const userData = localStorage.getItem("nutribot_user");
    if (!token || !userData) {
      router.replace("/login");
      return;
    }
    const parsed: AuthUser = JSON.parse(userData);
    if (!parsed.profile_complete) {
      router.replace("/profile");
      return;
    }
    setUser(parsed);
  }, [router]);

  // Load chat history for this session
  useEffect(() => {
    if (!user) return;
    getChatHistory(sessionId)
      .then((data) => {
        const loaded: MessageEntry[] = data.messages.map((m) => ({
          ...m,
          id: uuidv4(),
        }));
        if (loaded.length === 0) {
          // Greeting message
          setMessages([
            {
              id: uuidv4(),
              role: "assistant",
              content: `Hi ${user.full_name.split(" ")[0]}! 👋 I'm ${user.bot_name}, your personal nutrition companion. How can I help you today? You can ask me to generate a meal plan, calculate your calories, or just chat about nutrition!`,
              timestamp: new Date().toISOString(),
            },
          ]);
        } else {
          setMessages(loaded);
        }
      })
      .catch(() => {
        setMessages([
          {
            id: uuidv4(),
            role: "assistant",
            content: `Hi ${user?.full_name.split(" ")[0] ?? "there"}! 👋 I'm ${user?.bot_name ?? "Nova"}, your personal nutrition companion. How can I help you today?`,
            timestamp: new Date().toISOString(),
          },
        ]);
      });
  }, [user, sessionId]);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
      const res = await sendMessage(user.id, sessionId, text);
      const botMsg: MessageEntry = {
        id: uuidv4(),
        role: "assistant",
        content: res.response,
        timestamp: new Date().toISOString(),
        planProposed: res.plan_proposed,
        proposedPlan: res.proposed_plan,
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: uuidv4(),
          role: "assistant",
          content: "Sorry, something went wrong. Please try again.",
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  async function handleAcceptPlan(msgId: string, plan: Record<string, unknown>) {
    if (!user) return;
    setAcceptingId(msgId);
    try {
      const planDays = (plan.days as unknown[]) ?? [];
      const calorieTarget = (plan.calorie_target as number) ?? 0;
      const summary = `${planDays.length}-day plan, ${calorieTarget} kcal/day`;

      const res = await acceptPlan(
        user.id,
        sessionId,
        plan,
        calorieTarget,
        summary
      );
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId
            ? { ...m, planAccepted: true, planConfirmation: res.message }
            : m
        )
      );
    } catch (err) {
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
    <div className="flex flex-col h-screen bg-background">
      {/* Header */}
      <header className="flex-shrink-0 flex items-center justify-between px-4 py-3 bg-surface border-b border-border">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-background text-sm font-bold">
            {user.bot_name[0].toUpperCase()}
          </div>
          <div>
            <p className="text-sm font-semibold text-text">{user.bot_name}</p>
            <p className="text-xs text-muted">Your AI nutrition companion</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted hidden sm:block">{user.full_name}</span>
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
        {messages.map((msg) => (
          <div key={msg.id}>
            <ChatBubble
              role={msg.role}
              content={msg.content}
              botName={user.bot_name}
              timestamp={msg.timestamp}
            />
            {/* Meal plan card + accept/modify panel */}
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

        {/* Typing indicator */}
        {loading && (
          <div className="flex items-end gap-2 mb-4">
            <div className="w-8 h-8 rounded-full bg-panel border border-border flex items-center justify-center text-primary text-sm font-bold">
              {user.bot_name[0].toUpperCase()}
            </div>
            <div className="bg-panel border border-border rounded-2xl rounded-bl-sm px-4 py-3">
              <div className="flex gap-1">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="w-1.5 h-1.5 bg-muted rounded-full animate-bounce"
                    style={{ animationDelay: `${i * 0.15}s` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="flex-shrink-0 px-4 py-4 bg-surface border-t border-border">
        {/* Quick suggestions */}
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
  );
}

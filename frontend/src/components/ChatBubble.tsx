"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { RagSource } from "@/src/services/api";

type Props = {
  role: "user" | "assistant";
  content: string;
  botName?: string;
  timestamp?: string;
  ragSources?: RagSource[];
};

function sourceName(raw: string): string {
  // Strip path and extension: "data/diabetes_guide.pdf" → "diabetes_guide"
  return raw.replace(/^.*[\\/]/, "").replace(/\.[^.]+$/, "").replace(/_/g, " ");
}

const CONDITION_COLORS: Record<string, string> = {
  diabetes:    "bg-blue-900/30 text-blue-300 border-blue-700",
  pcos:        "bg-purple-900/30 text-purple-300 border-purple-700",
  thyroid:     "bg-yellow-900/30 text-yellow-300 border-yellow-700",
  hypertension:"bg-red-900/30 text-red-300 border-red-700",
  kidney:      "bg-orange-900/30 text-orange-300 border-orange-700",
  general:     "bg-emerald-900/30 text-emerald-300 border-emerald-700",
};

export default function ChatBubble({ role, content, botName = "Nova", timestamp, ragSources }: Props) {
  const isUser = role === "user";
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const hasSources = !isUser && ragSources && ragSources.length > 0;

  return (
    <div className={`flex items-end gap-2 mb-4 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold
          ${isUser ? "bg-primary text-background" : "bg-panel border border-border text-primary"}`}
      >
        {isUser ? "U" : botName[0].toUpperCase()}
      </div>

      <div className="max-w-[75%] flex flex-col gap-1">
        {/* Bubble */}
        <div
          className={`rounded-2xl px-4 py-3
            ${isUser
              ? "bg-primary text-background rounded-br-sm"
              : "bg-panel border border-border text-text rounded-bl-sm"
            }`}
        >
          {isUser ? (
            <p className="text-sm whitespace-pre-wrap">{content}</p>
          ) : (
            <div className="prose prose-sm prose-invert max-w-none text-text">
              <ReactMarkdown>{content}</ReactMarkdown>
            </div>
          )}
          {timestamp && (
            <p className={`text-xs mt-1 ${isUser ? "text-background/60 text-right" : "text-muted"}`}>
              {new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </p>
          )}
        </div>

        {/* RAG sources pill */}
        {hasSources && (
          <div className="ml-1">
            <button
              onClick={() => setSourcesOpen((o) => !o)}
              className="flex items-center gap-1.5 text-xs text-muted hover:text-primary transition-colors"
            >
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
              {sourcesOpen ? "Hide" : "View"} knowledge sources ({ragSources!.length})
              <span className={`transition-transform ${sourcesOpen ? "rotate-180" : ""}`}>▾</span>
            </button>

            {sourcesOpen && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {ragSources!.map((s, i) => {
                  const colorClass = CONDITION_COLORS[s.condition] ?? CONDITION_COLORS.general;
                  return (
                    <span
                      key={i}
                      className={`inline-flex items-center gap-1 text-xs border rounded-full px-2.5 py-0.5 ${colorClass}`}
                      title={`Source: ${s.source}`}
                    >
                      <span className="capitalize">{sourceName(s.source)}</span>
                      <span className="opacity-60">·</span>
                      <span className="capitalize opacity-80">{s.condition}</span>
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

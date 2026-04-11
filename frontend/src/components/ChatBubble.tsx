"use client";

import ReactMarkdown from "react-markdown";

type Props = {
  role: "user" | "assistant";
  content: string;
  botName?: string;
  timestamp?: string;
};

export default function ChatBubble({ role, content, botName = "Nova", timestamp }: Props) {
  const isUser = role === "user";

  return (
    <div className={`flex items-end gap-2 mb-4 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold
          ${isUser ? "bg-primary text-background" : "bg-panel border border-border text-primary"}`}
      >
        {isUser ? "U" : botName[0].toUpperCase()}
      </div>

      {/* Bubble */}
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-3
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
    </div>
  );
}

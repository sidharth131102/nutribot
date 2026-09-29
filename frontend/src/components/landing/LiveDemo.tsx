"use client";

import { AnimatePresence, motion, useInView } from "framer-motion";
import { useEffect, useRef, useState } from "react";

type Turn = {
  role: "user" | "assistant";
  text: string;
  /** Small caption under the bubble -- used to surface a feature (voice,
   *  translation, PDF) without wiring up the real backend on a public page. */
  badge?: string;
  /** Renders a compact plan preview after this assistant turn. */
  showPlan?: boolean;
};

const SCRIPT: Turn[] = [
  { role: "user", text: "Give me a 7-day meal plan for muscle gain", badge: "🎤 spoken, transcribed live" },
  {
    role: "assistant",
    text: "On it — built around chicken, salmon, dal and whole grains, tuned to your 3,340 kcal target and 250g protein goal.",
    showPlan: true,
  },
  { role: "user", text: "क्या आप इसे कम मसालेदार बना सकते हैं?", badge: "🌐 typed in Hindi" },
  {
    role: "assistant",
    text: "बिल्कुल — मैंने मसालों की मात्रा कम कर दी है और स्वाद वही रखा है। यह रहा अपडेटेड प्लान।",
    badge: "understood as: “Can you make it less spicy?” · replied in Hindi automatically",
  },
];

const TYPE_SPEED_MS = 14;
const PAUSE_BETWEEN_TURNS_MS = 650;
const RESTART_DELAY_MS = 3200;

function DemoPlanPreview() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="mt-2 rounded-xl border border-border bg-panel/60 p-3 text-xs"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-text">7-Day Meal Plan</span>
        <span className="text-muted">3,340 kcal/day</span>
      </div>
      <div className="grid grid-cols-3 gap-1.5 mb-2">
        {["P 250g", "C 334g", "F 111g"].map((m) => (
          <span key={m} className="bg-background/60 border border-border rounded-md text-center py-1 text-ink">
            {m}
          </span>
        ))}
      </div>
      <div className="flex items-center justify-between text-muted">
        <span>Day 1 — 3,347 kcal</span>
        <span className="flex items-center gap-1 text-ink">
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v12m0 0l-4-4m4 4l4-4M4 20h16" />
          </svg>
          PDF
        </span>
      </div>
    </motion.div>
  );
}

function TypingDots() {
  return (
    <div className="flex items-center gap-1 px-3 py-2.5">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-muted"
          animate={{ opacity: [0.3, 1, 0.3] }}
          transition={{ duration: 1, repeat: Infinity, delay: i * 0.18 }}
        />
      ))}
    </div>
  );
}

/** A fully scripted, client-side-only conversation that plays out once the
 *  section scrolls into view -- no backend call, no auth required. It exists
 *  so a visitor can *see* the product (per the brief: "the chat should be
 *  there in the website") before creating an account. */
export default function LiveDemo() {
  const containerRef = useRef<HTMLDivElement>(null);
  const inView = useInView(containerRef, { once: false, amount: 0.4 });

  const [visibleTurns, setVisibleTurns] = useState(0);
  const [typedText, setTypedText] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!inView) return;
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];

    async function playTurn(index: number) {
      if (cancelled) return;
      if (index >= SCRIPT.length) {
        timers.push(setTimeout(() => {
          if (cancelled) return;
          setVisibleTurns(0);
          setTypedText("");
          playTurn(0);
        }, RESTART_DELAY_MS));
        return;
      }

      const turn = SCRIPT[index];
      if (turn.role === "user") {
        setVisibleTurns(index + 1);
        timers.push(setTimeout(() => playTurn(index + 1), PAUSE_BETWEEN_TURNS_MS));
        return;
      }

      setIsTyping(true);
      timers.push(setTimeout(() => {
        if (cancelled) return;
        setIsTyping(false);
        setVisibleTurns(index + 1);
        setTypedText("");
        let i = 0;
        const step = () => {
          if (cancelled) return;
          i += 1;
          setTypedText(turn.text.slice(0, i));
          if (i < turn.text.length) {
            timers.push(setTimeout(step, TYPE_SPEED_MS));
          } else {
            timers.push(setTimeout(() => playTurn(index + 1), PAUSE_BETWEEN_TURNS_MS + 400));
          }
        };
        step();
      }, 900));
    }

    playTurn(0);
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, [inView]);

  useEffect(() => {
    // Guard against firing before there's anything to scroll to: with no
    // messages yet the container isn't overflowing, so a browser can decide
    // it isn't "scrollable" and bubble the request up to the whole
    // document instead -- hijacking the page's scroll position on load.
    if (visibleTurns === 0 && !isTyping) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [visibleTurns, typedText, isTyping]);

  return (
    <div ref={containerRef} className="w-full max-w-lg mx-auto">
      <div className="glass noise-overlay border border-border rounded-2xl overflow-hidden shadow-2xl shadow-black/40">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-panel/60">
          <div className="w-3 h-3 rounded-full bg-red-500/60" />
          <div className="w-3 h-3 rounded-full bg-yellow-500/60" />
          <div className="w-3 h-3 rounded-full bg-green-500/60" />
          <span className="ml-2 text-xs text-muted">Live product demo — Nova</span>
          <span className="ml-auto flex items-center gap-1 text-[10px] text-ink">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" /> playing
          </span>
        </div>
        <div className="p-4 space-y-3 h-[340px] overflow-y-auto">
          <AnimatePresence initial={false}>
            {SCRIPT.slice(0, visibleTurns).map((turn, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35 }}
                className={`flex ${turn.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div className={`flex gap-2 max-w-[85%] ${turn.role === "user" ? "flex-row-reverse" : ""}`}>
                  {turn.role === "assistant" && (
                    <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-ink text-xs font-bold flex-shrink-0">
                      N
                    </div>
                  )}
                  <div>
                    <div
                      className={`rounded-xl px-3 py-2 text-sm ${
                        turn.role === "user"
                          ? "bg-primary text-text rounded-tr-none"
                          : "bg-panel border border-border text-text rounded-tl-none"
                      }`}
                    >
                      {turn.role === "user" ? turn.text : i === visibleTurns - 1 ? typedText : turn.text}
                      {turn.role === "assistant" && i === visibleTurns - 1 && typedText.length < turn.text.length && (
                        <span className="inline-block w-1.5 h-3.5 bg-primary/70 ml-0.5 align-middle animate-pulse" />
                      )}
                    </div>
                    {turn.badge && (!isTyping || i !== visibleTurns - 1) && (
                      <p className={`text-[10px] text-muted mt-1 ${turn.role === "user" ? "text-right" : ""}`}>
                        {turn.badge}
                      </p>
                    )}
                    {turn.showPlan && i < visibleTurns && (!isTyping || i !== visibleTurns - 1) && <DemoPlanPreview />}
                  </div>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          {isTyping && (
            <div className="flex gap-2">
              <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-ink text-xs font-bold flex-shrink-0">
                N
              </div>
              <div className="bg-panel border border-border rounded-xl rounded-tl-none">
                <TypingDots />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
      <p className="text-center text-xs text-muted mt-3">
        A scripted preview of a real NutriBot conversation — sign up to run it on your own profile.
      </p>
    </div>
  );
}

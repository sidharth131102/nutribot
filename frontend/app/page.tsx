"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const FEATURES = [
  {
    icon: "🧠",
    title: "8-Agent AI Pipeline",
    desc: "A chain of specialised agents — intent classifier, calorie calculator, RAG retriever, food filter, and more — work together to give you hyper-personalised advice.",
  },
  {
    icon: "📚",
    title: "Knowledge-Backed Answers",
    desc: "Every response is grounded in clinical nutrition guidelines retrieved from a curated knowledge base via semantic search.",
  },
  {
    icon: "🥗",
    title: "7-Day Meal Plans",
    desc: "Personalised meal plans built around your calorie targets, dietary preferences, allergies, and medical conditions — never generic.",
  },
  {
    icon: "⚡",
    title: "Instant Calorie Maths",
    desc: "Precise BMR, TDEE, and macro targets calculated from your profile using the Mifflin-St Jeor equation the moment you ask.",
  },
  {
    icon: "🏥",
    title: "Condition-Aware",
    desc: "Understands diabetes, PCOS, hypertension, thyroid, and kidney conditions — automatically applies the right dietary rules.",
  },
  {
    icon: "📧",
    title: "Email Delivery",
    desc: "Accept a plan and it lands beautifully formatted in your inbox via SendGrid — your personal nutrition assistant, always with you.",
  },
];

const STATS = [
  { value: "8", label: "AI Agents" },
  { value: "7", label: "Day Meal Plans" },
  { value: "5", label: "Medical Conditions" },
  { value: "100%", label: "Personalised" },
];

const STEPS = [
  { n: "01", title: "Build your profile", desc: "Tell us your age, weight, goals, medical conditions, and dietary preferences in 4 quick steps." },
  { n: "02", title: "Chat naturally", desc: "Ask anything — generate a meal plan, calculate calories, get diet advice for your condition." },
  { n: "03", title: "Get your plan", desc: "Receive a structured 7-day plan with macros, timings, and a daily routine — emailed straight to you." },
];

export default function LandingPage() {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  // If already logged in, redirect silently
  useEffect(() => {
    const token = localStorage.getItem("nutribot_token");
    if (!token) { setChecked(true); return; }
    try {
      const user = JSON.parse(localStorage.getItem("nutribot_user") ?? "{}");
      router.replace(user.profile_complete ? "/chat" : "/profile");
    } catch {
      setChecked(true);
    }
  }, [router]);

  if (!checked) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-text overflow-x-hidden">

      {/* ── Nav ── */}
      <nav className="fixed top-0 inset-x-0 z-50 flex items-center justify-between px-6 py-4 bg-background/80 backdrop-blur border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-xl">🥗</span>
          <span className="font-bold text-text">NutriBot</span>
        </div>
        <Link
          href="/login"
          className="text-sm font-medium bg-primary text-background px-4 py-2 rounded-xl hover:bg-primary/90 transition-colors"
        >
          Get Started
        </Link>
      </nav>

      {/* ── Hero ── */}
      <section className="relative flex flex-col items-center justify-center min-h-screen text-center px-4 pt-20">
        {/* Background glow blobs */}
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full opacity-10 blur-3xl pointer-events-none"
          style={{ background: "radial-gradient(circle, #20c997 0%, transparent 70%)" }} />
        <div className="absolute bottom-1/4 right-1/4 w-72 h-72 rounded-full opacity-5 blur-3xl pointer-events-none"
          style={{ background: "radial-gradient(circle, #20c997 0%, transparent 70%)" }} />

        {/* Badge */}
        <div className="inline-flex items-center gap-2 bg-primary/10 border border-primary/30 rounded-full px-4 py-1.5 text-sm text-primary mb-6">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          Powered by Groq · LangGraph · ChromaDB
        </div>

        {/* Headline */}
        <h1 className="text-4xl sm:text-6xl font-extrabold leading-tight max-w-4xl mb-6">
          Your Personal{" "}
          <span style={{
            background: "linear-gradient(135deg, #20c997 0%, #0ea472 50%, #20c997 100%)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}>
            AI Nutrition
          </span>{" "}
          Coach
        </h1>

        <p className="text-muted text-lg sm:text-xl max-w-2xl mb-10 leading-relaxed">
          An 8-agent AI pipeline that understands your body, your goals, and your medical conditions —
          then crafts a precision nutrition plan just for you.
        </p>

        <div className="flex flex-col sm:flex-row gap-4 mb-16">
          <Link
            href="/login"
            className="px-8 py-3.5 bg-primary text-background font-semibold rounded-2xl text-base hover:bg-primary/90 transition-all hover:scale-105 shadow-lg shadow-primary/20"
          >
            Start for free →
          </Link>
          <a
            href="#how-it-works"
            className="px-8 py-3.5 border border-border text-muted rounded-2xl text-base hover:border-primary hover:text-text transition-colors"
          >
            See how it works
          </a>
        </div>

        {/* Mock chat preview */}
        <div className="w-full max-w-lg bg-surface border border-border rounded-2xl overflow-hidden shadow-2xl text-left">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-panel">
            <div className="w-3 h-3 rounded-full bg-red-500/60" />
            <div className="w-3 h-3 rounded-full bg-yellow-500/60" />
            <div className="w-3 h-3 rounded-full bg-green-500/60" />
            <span className="ml-2 text-xs text-muted">NutriBot Chat</span>
          </div>
          <div className="p-4 space-y-3">
            <div className="flex gap-2">
              <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-primary text-xs font-bold flex-shrink-0">N</div>
              <div className="bg-panel border border-border rounded-xl rounded-tl-none px-3 py-2 text-sm text-text max-w-xs">
                Hi! I'm Nova 👋 I've analysed your profile. You need <span className="text-primary font-medium">2,105 kcal/day</span> to reach your fat-loss goal.
              </div>
            </div>
            <div className="flex justify-end">
              <div className="bg-primary text-background rounded-xl rounded-tr-none px-3 py-2 text-sm max-w-xs">
                Generate a 7-day meal plan for me
              </div>
            </div>
            <div className="flex gap-2">
              <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-primary text-xs font-bold flex-shrink-0">N</div>
              <div className="bg-panel border border-border rounded-xl rounded-tl-none px-3 py-2 text-sm text-text max-w-xs">
                Here's your personalised 7-day plan 🥗 Based on your <span className="text-primary font-medium">non-vegetarian, low-GI</span> preference and dairy allergy…
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Stats ── */}
      <section className="py-16 border-y border-border bg-surface/40">
        <div className="max-w-4xl mx-auto px-4 grid grid-cols-2 sm:grid-cols-4 gap-8 text-center">
          {STATS.map((s) => (
            <div key={s.label}>
              <p className="text-4xl font-extrabold text-primary">{s.value}</p>
              <p className="text-muted text-sm mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Features ── */}
      <section className="py-24 px-4">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold mb-4">Everything your nutritionist would know</h2>
            <p className="text-muted max-w-xl mx-auto">Built with a multi-agent architecture so each part of your query gets expert-level attention.</p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map((f) => (
              <div key={f.title}
                className="bg-surface border border-border rounded-2xl p-5 hover:border-primary/50 transition-colors group">
                <div className="text-3xl mb-3">{f.icon}</div>
                <h3 className="font-semibold text-text mb-2 group-hover:text-primary transition-colors">{f.title}</h3>
                <p className="text-muted text-sm leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How it works ── */}
      <section id="how-it-works" className="py-24 px-4 bg-surface/40 border-y border-border">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold mb-4">Up and running in minutes</h2>
            <p className="text-muted">No complicated setup. Just tell us about you and start chatting.</p>
          </div>
          <div className="space-y-8">
            {STEPS.map((step, i) => (
              <div key={step.n} className="flex gap-5 items-start">
                <div className="flex-shrink-0 w-12 h-12 rounded-2xl bg-primary/10 border border-primary/30 flex items-center justify-center">
                  <span className="text-primary font-bold text-sm">{step.n}</span>
                </div>
                <div className="flex-1 pt-1">
                  <h3 className="font-semibold text-text mb-1">{step.title}</h3>
                  <p className="text-muted text-sm leading-relaxed">{step.desc}</p>
                </div>
                {i < STEPS.length - 1 && (
                  <div className="absolute ml-6 mt-14 w-px h-8 bg-border" style={{ position: "relative", left: "-100%" }} />
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Tech stack ── */}
      <section className="py-20 px-4">
        <div className="max-w-4xl mx-auto text-center">
          <p className="text-muted text-sm uppercase tracking-widest mb-8">Built with</p>
          <div className="flex flex-wrap justify-center gap-3">
            {["LangGraph", "Groq LLM", "ChromaDB", "MongoDB Atlas", "FastAPI", "Next.js 15", "SendGrid", "JWT Auth"].map((t) => (
              <span key={t} className="bg-panel border border-border rounded-full px-4 py-1.5 text-sm text-muted">
                {t}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="py-24 px-4">
        <div className="max-w-2xl mx-auto text-center">
          <div className="bg-surface border border-border rounded-3xl p-10 relative overflow-hidden">
            <div className="absolute inset-0 opacity-5 pointer-events-none"
              style={{ background: "radial-gradient(circle at 50% 0%, #20c997 0%, transparent 60%)" }} />
            <div className="text-4xl mb-4">🥗</div>
            <h2 className="text-3xl font-bold mb-4">Ready to eat smarter?</h2>
            <p className="text-muted mb-8 leading-relaxed">
              Join NutriBot and get a nutrition plan tailored to your body, your goals,
              and your health — powered by real clinical guidelines.
            </p>
            <Link
              href="/login"
              className="inline-block px-10 py-4 bg-primary text-background font-bold rounded-2xl text-base hover:bg-primary/90 transition-all hover:scale-105 shadow-xl shadow-primary/20"
            >
              Get started — it's free →
            </Link>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-border py-8 px-4 text-center">
        <p className="text-muted text-sm">
          © 2026 NutriBot · Built with AI, backed by clinical nutrition science.
        </p>
      </footer>

    </div>
  );
}

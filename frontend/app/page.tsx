"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion, useScroll, useSpring } from "framer-motion";
import {
  Leaf, Brain, Calculator, BookOpen, Mic, ShieldCheck, FileText, ArrowRight,
} from "lucide-react";

import Reveal, { StaggerGroup, staggerItem } from "@/src/components/motion/Reveal";
import Magnetic from "@/src/components/motion/Magnetic";
import TiltCard from "@/src/components/motion/TiltCard";
import HeroOrbLoader from "@/src/components/three/HeroOrbLoader";
import Counter from "@/src/components/landing/Counter";
import Marquee from "@/src/components/landing/Marquee";
import LiveDemo from "@/src/components/landing/LiveDemo";
import {
  Apple, Carrot, Check, DoodleField, Droplet, Dumbbell, Heartbeat, Loop,
  Plus, Scribble, Sparkle, Squiggle, Star, Wave, Zigzag,
} from "@/src/components/landing/Doodles";

const HERO_DOODLES = [
  { icon: Sparkle, className: "top-[22%] left-[7%] w-10 h-10", rotate: -10, opacity: 0.55 },
  { icon: Squiggle, className: "top-[28%] right-[9%] w-20 h-7", rotate: 8, opacity: 0.5 },
  { icon: Heartbeat, className: "top-[13%] right-[22%] w-24 h-9", rotate: -3, opacity: 0.4 },
  { icon: Droplet, className: "bottom-[6%] left-[13%] w-7 h-9", rotate: 12, opacity: 0.45 },
  { icon: Plus, className: "top-[38%] left-[17%] w-5 h-5", rotate: 0, opacity: 0.4 },
  { icon: Carrot, className: "bottom-[12%] right-[11%] w-9 h-11", rotate: 18, opacity: 0.45 },
  { icon: Apple, className: "top-[10%] left-[22%] w-8 h-9", rotate: -14, opacity: 0.4 },
  { icon: Star, className: "bottom-[26%] right-[24%] w-7 h-7", rotate: 10, opacity: 0.4 },
  { icon: Zigzag, className: "top-[52%] left-[4%] w-16 h-5", rotate: -6, opacity: 0.35 },
  { icon: Dumbbell, className: "top-[8%] right-[6%] w-11 h-5", rotate: 12, opacity: 0.4 },
  { icon: Scribble, className: "bottom-[30%] left-[24%] w-10 h-10", rotate: 4, opacity: 0.3 },
  { icon: Wave, className: "top-[46%] right-[4%] w-16 h-5", rotate: 0, opacity: 0.35 },
];
const FEATURES_DOODLES = [
  { icon: Loop, className: "top-[3%] left-[3%] w-14 h-14", rotate: -6, opacity: 0.3 },
  { icon: Sparkle, className: "bottom-[5%] right-[4%] w-8 h-8", rotate: 12, opacity: 0.35 },
  { icon: Star, className: "top-[6%] right-[7%] w-7 h-7", rotate: -8, opacity: 0.3 },
  { icon: Zigzag, className: "bottom-[8%] left-[6%] w-16 h-5", rotate: 6, opacity: 0.3 },
];
const DEMO_DOODLES = [
  { icon: Squiggle, className: "top-[2%] left-[4%] w-16 h-6", rotate: -6, opacity: 0.35 },
  { icon: Plus, className: "bottom-[10%] right-[6%] w-5 h-5", rotate: 10, opacity: 0.35 },
  { icon: Apple, className: "top-[8%] right-[8%] w-8 h-9", rotate: 14, opacity: 0.3 },
];
const HOW_DOODLES = [
  { icon: Check, className: "top-[8%] right-[8%] w-7 h-6", rotate: -8, opacity: 0.35 },
  { icon: Dumbbell, className: "bottom-[10%] right-[14%] w-11 h-5", rotate: 8, opacity: 0.3 },
  { icon: Scribble, className: "bottom-[4%] left-[5%] w-10 h-10", rotate: -4, opacity: 0.28 },
];
const TRUST_DOODLES = [
  { icon: Sparkle, className: "top-[2%] left-[2%] w-8 h-8", rotate: 10, opacity: 0.35 },
  { icon: Wave, className: "bottom-[6%] left-[10%] w-16 h-5", rotate: 0, opacity: 0.3 },
];
const CTA_DOODLES = [
  { icon: Star, className: "top-[10%] left-[6%] w-7 h-7", rotate: -10, opacity: 0.45 },
  { icon: Squiggle, className: "bottom-[14%] right-[8%] w-16 h-6", rotate: 8, opacity: 0.4 },
  { icon: Droplet, className: "top-[14%] right-[10%] w-6 h-8", rotate: 12, opacity: 0.4 },
];

const FEATURES = [
  {
    icon: Brain,
    title: "10-Agent Pipeline",
    desc: "A LangGraph pipeline of specialised agents — safety, profile, memory, intent, calorie math, retrieval, food filtering, and generation — each doing one job well.",
  },
  {
    icon: Calculator,
    title: "Deterministic Nutrition Math",
    desc: "The model never invents a calorie or macro figure. Every number in your plan is computed in code from your profile and a curated food database — always correct.",
    highlight: true,
  },
  {
    icon: BookOpen,
    title: "Hybrid RAG Retrieval",
    desc: "Dense + keyword search over clinical guideline PDFs, fused and reranked, so condition-specific answers are grounded in real sources — not guesswork.",
  },
  {
    icon: Mic,
    title: "Voice & Multilingual",
    desc: "Speak instead of type, in the languages you choose. Messages translate to English for the pipeline and replies come back in your language — switch mid-chat, it just works.",
  },
  {
    icon: ShieldCheck,
    title: "Runtime Safety Guardrails",
    desc: "Every message is screened before generation and every response checked after — for allergens, diagnosis language, and unsupported claims — before you ever see it.",
    highlight: true,
  },
  {
    icon: FileText,
    title: "Structured PDF Export",
    desc: "Download any plan as a clean, correctly-formatted PDF — day-by-day tables, macro targets, and your routine — generated straight from the verified numbers.",
  },
];

const STATS = [
  { value: 10, suffix: "", label: "Specialised AI Agents" },
  { value: 100, suffix: "+", label: "Languages Understood" },
  { value: 0, suffix: "%", label: "Hallucinated Calories" },
  { value: 24, suffix: "/7", label: "Always Available" },
];

const STEPS = [
  {
    n: "01",
    title: "Build your profile",
    desc: "Tell us your age, weight, goals, medical conditions, and dietary preferences in a few quick steps — editable anytime.",
  },
  {
    n: "02",
    title: "Chat naturally, in your language",
    desc: "Type or speak. Ask for a meal plan, a calorie breakdown, or diet advice for a condition — in English, Hindi, French, or whatever you speak.",
  },
  {
    n: "03",
    title: "Get a plan you can trust",
    desc: "A structured 7-day plan with verified macros and timings — download it as a PDF or accept it and it lands in your inbox.",
  },
];

const TECH = [
  "Azure OpenAI", "LangGraph", "Pinecone", "MongoDB Atlas",
  "Azure Speech", "Azure Translator", "FastAPI", "Next.js 15",
  "ReportLab", "DeepEval",
];

function ScrollProgressBar() {
  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, { stiffness: 120, damping: 24, restDelta: 0.001 });
  return (
    <motion.div
      style={{ scaleX }}
      className="fixed top-0 inset-x-0 h-[3px] origin-left bg-primary border-b-2 border-ink z-[60]"
    />
  );
}

/** A nav link with a lime underline that wipes in from the left on hover,
 *  instead of a flat opacity fade -- ties the interaction back to the same
 *  accent color used everywhere else (badges, buttons, highlights). */
function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} className="relative py-0.5 group">
      {children}
      <span className="absolute left-0 -bottom-0.5 h-[3px] w-0 bg-primary rounded-full transition-all duration-300 ease-out group-hover:w-full" />
    </a>
  );
}

export default function LandingPage() {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

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
        <div className="w-6 h-6 border-2 border-ink border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen text-text overflow-x-hidden">
      <ScrollProgressBar />

      {/* ── Nav: floating white pill, matches the reference's card-style nav ── */}
      <nav className="fixed top-4 inset-x-4 z-50">
        <div className="max-w-5xl mx-auto bg-surface border-2 border-ink rounded-full px-5 py-3 flex items-center justify-between shadow-hard">
          <div className="flex items-center gap-2">
            <span className="w-8 h-8 rounded-full bg-primary border-2 border-ink flex items-center justify-center">
              <Leaf className="w-4 h-4 text-ink" strokeWidth={2.5} />
            </span>
            <span className="font-display font-extrabold text-text tracking-tight">NutriBot</span>
          </div>
          <div className="hidden sm:flex items-center gap-7 text-sm font-medium text-text">
            <NavLink href="#demo">Live Demo</NavLink>
            <NavLink href="#features">Features</NavLink>
            <NavLink href="#how-it-works">How it works</NavLink>
          </div>
          <Magnetic>
            <Link
              href="/login"
              className="text-sm font-semibold bg-ink text-white px-4 py-2 rounded-full hover:opacity-85 transition-opacity"
            >
              Get Started
            </Link>
          </Magnetic>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="relative flex flex-col items-center text-center px-4 pt-28 pb-8">
        <DoodleField items={HERO_DOODLES} />

        <Reveal from="scale" className="relative z-10">
          <div className="inline-flex items-center gap-2 bg-surface border-2 border-ink rounded-full px-4 py-1.5 text-sm font-medium mb-6 shadow-hard-sm">
            <span className="w-1.5 h-1.5 rounded-full bg-primary border border-ink" />
            Powered by Azure OpenAI · LangGraph · Pinecone
          </div>
        </Reveal>

        <Reveal delay={0.1} className="relative z-10">
          <h1 className="font-display text-5xl sm:text-7xl font-extrabold leading-[0.98] max-w-4xl mb-6 tracking-tight">
            Your personal <span className="highlight">AI nutrition</span> coach
          </h1>
        </Reveal>

        <Reveal delay={0.18} className="relative z-10">
          <p className="text-muted text-lg sm:text-xl max-w-2xl mb-10 leading-relaxed">
            Speak or type, in your own language. A multi-agent pipeline turns your profile and goals
            into a nutrition plan with numbers you can actually trust — never invented, always verified.
          </p>
        </Reveal>

        <Reveal delay={0.26} className="relative z-10 flex flex-col sm:flex-row gap-4">
          <Magnetic>
            <Link
              href="/login"
              className="inline-flex items-center gap-2 px-8 py-3.5 bg-primary text-ink border-2 border-ink font-bold rounded-2xl text-base hover:-translate-y-0.5 transition-transform shadow-hard"
            >
              Start for free <ArrowRight className="w-4 h-4" />
            </Link>
          </Magnetic>
          <Magnetic>
            <a
              href="#demo"
              className="inline-block px-8 py-3.5 bg-surface border-2 border-ink text-text rounded-2xl text-base font-semibold hover:-translate-y-0.5 transition-transform shadow-hard"
            >
              Watch it in action
            </a>
          </Magnetic>
        </Reveal>

        {/* In normal document flow below the buttons (not absolutely
            positioned over the copy) -- a fixed margin-top is the only way
            to *guarantee* zero overlap with the text above on any viewport
            height, rather than tuning a percentage-based offset and hoping. */}
        <Reveal delay={0.34} className="relative z-10 w-full max-w-[380px] mt-10">
          <div className="w-full h-[300px]">
            <HeroOrbLoader />
          </div>
        </Reveal>
      </section>

      {/* ── Live demo ── */}
      <section id="demo" className="relative py-24 px-4">
        <DoodleField items={DEMO_DOODLES} />
        <Reveal className="text-center mb-12">
          <h2 className="font-display text-3xl sm:text-4xl font-extrabold mb-4">See NutriBot in action</h2>
          <p className="text-muted max-w-xl mx-auto">
            A real conversation, scripted for the page — speak your request, switch languages mid-chat,
            get a verified plan back.
          </p>
        </Reveal>
        <Reveal delay={0.1}>
          <LiveDemo />
        </Reveal>
      </section>

      {/* ── Stats ── */}
      <section className="py-16 border-y-2 border-ink bg-surface">
        <StaggerGroup className="max-w-4xl mx-auto px-4 grid grid-cols-2 sm:grid-cols-4 gap-8 text-center">
          {STATS.map((s) => (
            <motion.div key={s.label} variants={staggerItem}>
              <p className="font-display text-4xl font-extrabold text-text">
                <Counter value={s.value} suffix={s.suffix} />
              </p>
              <p className="text-muted text-sm mt-1">{s.label}</p>
            </motion.div>
          ))}
        </StaggerGroup>
      </section>

      {/* ── Features ── */}
      <section id="features" className="relative py-24 px-4">
        <DoodleField items={FEATURES_DOODLES} />
        <div className="max-w-5xl mx-auto">
          <Reveal className="text-center mb-16">
            <h2 className="font-display text-3xl sm:text-4xl font-extrabold mb-4">Everything your nutritionist would know</h2>
            <p className="text-muted max-w-xl mx-auto">Built with a multi-agent architecture so each part of your query gets expert-level attention.</p>
          </Reveal>
          <StaggerGroup className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map((f) => (
              <motion.div key={f.title} variants={staggerItem}>
                <TiltCard
                  className={`h-full border-2 border-ink rounded-2xl p-5 shadow-hard transition-transform hover:-translate-y-1 overflow-hidden ${
                    f.highlight ? "bg-primary" : "bg-surface"
                  }`}
                >
                  <div className="w-11 h-11 rounded-xl bg-ink flex items-center justify-center mb-4">
                    <f.icon className="w-5 h-5 text-white" strokeWidth={2} />
                  </div>
                  <h3 className="font-display font-bold text-text mb-2">{f.title}</h3>
                  <p className="text-text/70 text-sm leading-relaxed">{f.desc}</p>
                </TiltCard>
              </motion.div>
            ))}
          </StaggerGroup>
        </div>
      </section>

      {/* ── How it works ── */}
      <section id="how-it-works" className="relative py-24 px-4 bg-surface border-y-2 border-ink">
        <DoodleField items={HOW_DOODLES} />
        <div className="max-w-3xl mx-auto">
          <Reveal className="text-center mb-16">
            <h2 className="font-display text-3xl sm:text-4xl font-extrabold mb-4">Up and running in minutes</h2>
            <p className="text-muted">No complicated setup. Just tell us about you and start chatting — or speaking.</p>
          </Reveal>
          <div className="relative">
            <div className="absolute left-6 top-6 bottom-6 w-0.5 bg-ink/15 hidden sm:block" />
            <div className="space-y-10">
              {STEPS.map((step, i) => (
                <Reveal key={step.n} delay={i * 0.06} from="left">
                  <div className="flex gap-5 items-start relative">
                    <div className="flex-shrink-0 w-12 h-12 rounded-2xl bg-ink border-2 border-ink flex items-center justify-center relative z-10">
                      <span className="text-primary font-bold text-sm font-mono">{step.n}</span>
                    </div>
                    <div className="flex-1 pt-1">
                      <h3 className="font-display font-bold text-text mb-1">{step.title}</h3>
                      <p className="text-muted text-sm leading-relaxed">{step.desc}</p>
                    </div>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Trust / accuracy ── */}
      <section className="relative py-24 px-4">
        <DoodleField items={TRUST_DOODLES} />
        <div className="max-w-5xl mx-auto grid md:grid-cols-2 gap-10 items-center">
          <Reveal from="left">
            <h2 className="font-display text-3xl sm:text-4xl font-extrabold mb-5 leading-tight">
              Built so the numbers are <span className="highlight">never a guess</span>
            </h2>
            <p className="text-muted leading-relaxed mb-6">
              Most AI meal planners let the model do arithmetic — and language models are not
              calculators. NutriBot's LLM never computes a calorie or macro figure. It picks foods;
              deterministic code looks up each one in a nutrition database, does the math, and
              rebalances any day that misses your target. What you see is what was actually computed.
            </p>
            <ul className="space-y-3 text-sm">
              {[
                "Calorie targets computed with the Mifflin-St Jeor equation, not estimated by the model",
                "Every meal-plan number traced back to a curated food database",
                "An allow-list enforced in code, not just a prompt instruction",
                "Output re-checked for allergens and unsupported medical claims before you see it",
              ].map((line) => (
                <li key={line} className="flex items-start gap-2.5 text-text">
                  <span className="w-5 h-5 rounded-full bg-primary border-2 border-ink flex items-center justify-center flex-shrink-0 mt-0.5 text-[10px] font-bold">
                    ✓
                  </span>
                  {line}
                </li>
              ))}
            </ul>
          </Reveal>
          <Reveal from="right" delay={0.1}>
            <TiltCard className="bg-ink text-white border-2 border-ink rounded-2xl p-6 font-mono text-xs leading-relaxed shadow-hard">
              <p className="text-white/50 mb-2">{"// plan_builder.py"}</p>
              <p><span className="text-primary">calories</span> = <span className="text-white">db_value</span> × grams ÷ serving</p>
              <p className="text-white/50 mt-3 mb-2">{"// if a day misses target:"}</p>
              <p><span className="text-primary">day</span>.rescale(<span className="text-white">clamp</span>(0.6, 1.75))</p>
              <p className="text-white/50 mt-3 mb-2">{"// invariant, enforced in code:"}</p>
              <p className="text-primary">assert model_never_does_math()</p>
            </TiltCard>
          </Reveal>
        </div>
      </section>

      {/* ── Tech stack ── */}
      <section className="py-20 px-4">
        <div className="max-w-4xl mx-auto text-center">
          <Reveal>
            <p className="text-muted text-sm uppercase tracking-widest mb-8 font-mono">Built with</p>
          </Reveal>
          <Marquee>
            {TECH.map((t) => (
              <span key={t} className="bg-surface border-2 border-ink rounded-full px-4 py-1.5 text-sm font-medium text-text whitespace-nowrap">
                {t}
              </span>
            ))}
          </Marquee>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="relative py-24 px-4">
        <DoodleField items={CTA_DOODLES} />
        <Reveal from="scale" className="max-w-2xl mx-auto text-center">
          <div className="bg-ink text-white border-2 border-ink rounded-3xl p-10 relative overflow-hidden shadow-hard">
            <span className="inline-flex w-14 h-14 rounded-full bg-primary border-2 border-ink items-center justify-center mb-5">
              <Leaf className="w-6 h-6 text-ink" strokeWidth={2.5} />
            </span>
            <h2 className="font-display text-3xl font-extrabold mb-4">Ready to eat smarter?</h2>
            <p className="text-white/70 mb-8 leading-relaxed">
              Join NutriBot and get a nutrition plan tailored to your body, your goals, your language,
              and your health — backed by verified numbers, not guesses.
            </p>
            <Magnetic className="inline-block">
              <Link
                href="/login"
                className="inline-flex items-center gap-2 px-10 py-4 bg-primary text-ink border-2 border-ink font-bold rounded-2xl text-base hover:-translate-y-0.5 transition-transform"
              >
                Get started — it's free <ArrowRight className="w-4 h-4" />
              </Link>
            </Magnetic>
          </div>
        </Reveal>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t-2 border-ink py-8 px-4 text-center">
        <p className="text-muted text-sm">
          © 2026 NutriBot · Built with AI, backed by verified nutrition math.
        </p>
      </footer>

    </div>
  );
}

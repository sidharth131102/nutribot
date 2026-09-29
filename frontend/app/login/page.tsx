"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import Link from "next/link";
import { ArrowLeft, Leaf } from "lucide-react";
import { login, register, getGoogleAuthUrl, type TokenResponse } from "@/src/services/api";
import Magnetic from "@/src/components/motion/Magnetic";
import {
  Apple, Carrot, Check, DoodleField, Droplet, Dumbbell, Heartbeat, Loop,
  Plus, Scribble, Sparkle, Squiggle, Star, Wave, Zigzag,
} from "@/src/components/landing/Doodles";

const LOGIN_DOODLES = [
  { icon: Sparkle, className: "top-[9%] left-[9%] w-9 h-9", rotate: -8, opacity: 0.5 },
  { icon: Squiggle, className: "top-[15%] right-[12%] w-16 h-6", rotate: 6, opacity: 0.5 },
  { icon: Heartbeat, className: "bottom-[22%] left-[6%] w-20 h-8", rotate: -4, opacity: 0.45 },
  { icon: Droplet, className: "top-[46%] right-[7%] w-6 h-8", rotate: 10, opacity: 0.45 },
  { icon: Loop, className: "bottom-[10%] right-[14%] w-12 h-12", rotate: 0, opacity: 0.4 },
  { icon: Plus, className: "bottom-[32%] right-[21%] w-5 h-5", rotate: 15, opacity: 0.4 },
  { icon: Carrot, className: "top-[34%] left-[5%] w-8 h-10", rotate: -20, opacity: 0.4 },
  { icon: Apple, className: "bottom-[6%] left-[20%] w-8 h-9", rotate: 12, opacity: 0.4 },
  { icon: Star, className: "top-[6%] right-[26%] w-6 h-6", rotate: 10, opacity: 0.4 },
  { icon: Zigzag, className: "bottom-[40%] left-[3%] w-14 h-5", rotate: -6, opacity: 0.35 },
  { icon: Dumbbell, className: "top-[24%] left-[20%] w-10 h-5", rotate: 8, opacity: 0.35 },
  { icon: Check, className: "top-[8%] left-[30%] w-6 h-5", rotate: -10, opacity: 0.35 },
  { icon: Scribble, className: "bottom-[4%] right-[6%] w-10 h-10", rotate: 6, opacity: 0.3 },
  { icon: Wave, className: "top-[58%] right-[4%] w-14 h-5", rotate: 0, opacity: 0.35 },
];

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function persist(data: TokenResponse) {
    localStorage.setItem("nutribot_token", data.access_token);
    localStorage.setItem("nutribot_user", JSON.stringify(data.user));
    if (!data.user.profile_complete) {
      router.push("/profile");
    } else {
      router.push("/chat");
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data =
        mode === "login"
          ? await login(email, password)
          : await register(email, password, fullName);
      persist(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  function handleGoogle() {
    window.location.href = getGoogleAuthUrl();
  }

  return (
    <main className="relative min-h-screen flex items-center justify-center px-4 overflow-hidden">
      {/* Ambient background glow, echoes the landing hero */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full opacity-[0.14] blur-3xl pointer-events-none"
        style={{ background: "radial-gradient(circle, #d6f83c 0%, transparent 70%)" }} />
      <div className="absolute bottom-0 right-0 w-72 h-72 rounded-full opacity-[0.08] blur-3xl pointer-events-none"
        style={{ background: "radial-gradient(circle, #ff6b4a 0%, transparent 70%)" }} />
      <DoodleField items={LOGIN_DOODLES} />

      <Link
        href="/"
        className="absolute top-6 left-6 z-10 inline-flex items-center gap-1.5 text-sm font-medium bg-surface border-2 border-ink rounded-full pl-3 pr-4 py-2 shadow-hard-sm hover:-translate-y-0.5 transition-transform"
      >
        <ArrowLeft className="w-4 h-4" strokeWidth={2.5} />
        Back to home
      </Link>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        className="relative w-full max-w-sm"
      >
        {/* Logo */}
        <div className="text-center mb-8">
          <motion.div
            initial={{ scale: 0.8, rotate: -8, opacity: 0 }}
            animate={{ scale: 1, rotate: 0, opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
            className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-primary border-2 border-ink mb-4 shadow-hard"
          >
            <Leaf className="w-6 h-6 text-ink" strokeWidth={2.5} />
          </motion.div>
          <h1 className="font-display text-2xl font-extrabold text-text tracking-tight">NutriBot</h1>
          <p className="text-muted text-sm mt-1">Your AI nutrition companion</p>
        </div>

        {/* Card */}
        <div className="bg-surface border-2 border-ink rounded-2xl p-6 shadow-hard">
          {/* Tab toggle */}
          <div className="flex rounded-xl bg-panel border-2 border-ink p-1 mb-6">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`flex-1 py-2 rounded-lg text-sm font-semibold transition-colors capitalize
                  ${mode === m ? "bg-primary text-ink" : "text-muted hover:text-text"}`}
              >
                {m}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "register" && (
              <div>
                <label className="block text-sm text-muted mb-1">Full Name</label>
                <input
                  type="text"
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Your full name"
                  className="w-full bg-panel border-2 border-ink rounded-xl px-4 py-2.5 text-text text-sm
                    placeholder:text-muted focus:outline-none focus:border-primary transition-colors"
                />
              </div>
            )}
            <div>
              <label className="block text-sm text-muted mb-1">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full bg-panel border-2 border-ink rounded-xl px-4 py-2.5 text-text text-sm
                  placeholder:text-muted focus:outline-none focus:border-primary transition-colors"
              />
            </div>
            <div>
              <label className="block text-sm text-muted mb-1">Password</label>
              <input
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-panel border-2 border-ink rounded-xl px-4 py-2.5 text-text text-sm
                  placeholder:text-muted focus:outline-none focus:border-primary transition-colors"
              />
            </div>

            {error && (
              <p className="text-sm text-red-700 bg-red-100 border-2 border-red-700 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <Magnetic strength={6}>
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-primary text-ink border-2 border-ink font-bold rounded-xl py-3 text-sm
                  shadow-hard-sm hover:-translate-y-0.5 transition-transform disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0"
              >
                {loading
                  ? mode === "login" ? "Signing in…" : "Creating account…"
                  : mode === "login" ? "Sign In" : "Create Account"}
              </button>
            </Magnetic>
          </form>

          {/* Divider */}
          <div className="flex items-center gap-3 my-4">
            <div className="flex-1 h-px bg-border/15" />
            <span className="text-xs text-muted">or</span>
            <div className="flex-1 h-px bg-border/15" />
          </div>

          {/* Google OAuth */}
          <button
            onClick={handleGoogle}
            className="w-full flex items-center justify-center gap-3 bg-surface border-2 border-ink
              rounded-xl py-3 text-sm font-medium text-text hover:bg-panel transition-colors"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            Continue with Google
          </button>
        </div>
      </motion.div>
    </main>
  );
}

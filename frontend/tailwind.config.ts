import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx,js,jsx}",
    "./src/**/*.{ts,tsx,js,jsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Light, warm, high-contrast -- black outlines as a deliberate design
        // element, one vivid lime accent, not a dark/moody palette.
        background: "#f7f6f0",
        surface: "#ffffff",
        panel: "#f0efe6",
        border: "#111111",
        primary: "#d6f83c",
        accent: "#ff6b4a",
        ink: "#111111",
        text: "#111111",
        muted: "#5c5c52"
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "-apple-system", "sans-serif"],
        display: ["var(--font-display)", "var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"]
      },
      backgroundImage: {
        "grid-fade": "linear-gradient(180deg, transparent, rgba(11,17,16,1) 85%)",
        "mesh-glow": "radial-gradient(ellipse 80% 50% at 50% -10%, rgba(32,201,151,0.25), transparent)",
        "dot-grid": "radial-gradient(rgba(237,247,244,0.5) 1px, transparent 1px)"
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-14px)" }
        },
        "spin-slow": {
          from: { transform: "rotate(0deg)" },
          to: { transform: "rotate(360deg)" }
        },
        marquee: {
          from: { transform: "translateX(0)" },
          to: { transform: "translateX(-50%)" }
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" }
        },
        "pulse-glow": {
          "0%, 100%": { opacity: "0.5", transform: "scale(1)" },
          "50%": { opacity: "0.9", transform: "scale(1.06)" }
        },
        "aurora-a": {
          "0%, 100%": { transform: "translate(-8%, -6%) scale(1)" },
          "33%": { transform: "translate(6%, 4%) scale(1.15)" },
          "66%": { transform: "translate(-4%, 8%) scale(0.95)" }
        },
        "aurora-b": {
          "0%, 100%": { transform: "translate(6%, 4%) scale(1.1)" },
          "50%": { transform: "translate(-10%, -8%) scale(0.9)" }
        },
        "aurora-c": {
          "0%, 100%": { transform: "translate(0%, 10%) scale(0.95)" },
          "50%": { transform: "translate(8%, -6%) scale(1.2)" }
        },
        "grid-pan": {
          from: { backgroundPosition: "0 0" },
          to: { backgroundPosition: "48px 48px" }
        }
      },
      animation: {
        float: "float 6s ease-in-out infinite",
        "spin-slow": "spin-slow 24s linear infinite",
        marquee: "marquee 32s linear infinite",
        shimmer: "shimmer 2.5s linear infinite",
        "pulse-glow": "pulse-glow 4s ease-in-out infinite",
        "aurora-a": "aurora-a 26s ease-in-out infinite",
        "aurora-b": "aurora-b 32s ease-in-out infinite",
        "aurora-c": "aurora-c 38s ease-in-out infinite",
        "grid-pan": "grid-pan 6s linear infinite"
      },
      boxShadow: {
        glow: "0 0 60px -15px rgba(214,248,60,0.5)",
        "glow-lg": "0 0 120px -20px rgba(214,248,60,0.45)"
      }
    }
  },
  plugins: [require("@tailwindcss/typography")]
};

export default config;

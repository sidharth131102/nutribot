import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "#0b1110",
        surface: "#101a18",
        panel: "#14211f",
        border: "#25413b",
        primary: "#20c997",
        text: "#edf7f4",
        muted: "#9fb8b1"
      }
    }
  },
  plugins: []
};

export default config;

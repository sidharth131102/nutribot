import type React from "react";
import type { Metadata } from "next";
import { Inter, Archivo, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import AuroraBackground from "@/src/components/landing/AuroraBackground";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
// A bold, high-personality grotesque for headlines -- distinct from the
// body sans (not just the same family at a heavier weight), matching a
// light, high-contrast, black-outlined visual language.
const display = Archivo({ subsets: ["latin"], variable: "--font-display", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "NutriBot — AI Nutrition Assistant",
  description: "Your personalized AI-powered nutrition companion",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${display.variable} ${mono.variable}`}>
      <body className="bg-background text-text antialiased font-sans" suppressHydrationWarning>
        <AuroraBackground />
        <div className="relative z-0">{children}</div>
      </body>
    </html>
  );
}

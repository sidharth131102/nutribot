import type React from "react";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NutriBot — AI Nutrition Assistant",
  description: "Your personalized AI-powered nutrition companion",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="bg-background text-text antialiased" suppressHydrationWarning>{children}</body>
    </html>
  );
}

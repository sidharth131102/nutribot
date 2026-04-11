"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("nutribot_token");
    const userData = localStorage.getItem("nutribot_user");

    if (!token) {
      router.replace("/login");
      return;
    }

    try {
      const user = JSON.parse(userData ?? "{}");
      if (!user.profile_complete) {
        router.replace("/profile");
      } else {
        router.replace("/chat");
      }
    } catch {
      router.replace("/login");
    }
  }, [router]);

  return (
    <div className="min-h-screen bg-background flex items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <span className="text-3xl">🥗</span>
        <p className="text-muted text-sm">Loading NutriBot…</p>
      </div>
    </div>
  );
}

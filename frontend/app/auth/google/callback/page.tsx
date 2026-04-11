"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

function GoogleCallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get("code");
    const errorParam = searchParams.get("error");

    if (errorParam) {
      setError("Google sign-in was cancelled or failed. Please try again.");
      setTimeout(() => router.push("/login"), 3000);
      return;
    }

    if (!code) {
      setError("No authorisation code received from Google.");
      setTimeout(() => router.push("/login"), 3000);
      return;
    }

    // Exchange the code via the backend
    fetch(`${API_BASE}/api/auth/google-callback?code=${encodeURIComponent(code)}`)
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail ?? "Google sign-in failed");
        return data;
      })
      .then((data) => {
        localStorage.setItem("nutribot_token", data.access_token);
        localStorage.setItem("nutribot_user", JSON.stringify(data.user));
        if (!data.user.profile_complete) {
          router.push("/profile");
        } else {
          router.push("/chat");
        }
      })
      .catch((err) => {
        setError(err.message ?? "Google sign-in failed. Please try again.");
        setTimeout(() => router.push("/login"), 3000);
      });
  }, [searchParams, router]);

  return (
    <main className="min-h-screen bg-background flex items-center justify-center">
      <div className="text-center space-y-4">
        {error ? (
          <>
            <p className="text-red-400 text-sm">{error}</p>
            <p className="text-muted text-xs">Redirecting to login…</p>
          </>
        ) : (
          <>
            <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-muted text-sm">Signing you in with Google…</p>
          </>
        )}
      </div>
    </main>
  );
}

export default function GoogleCallbackPage() {
  return (
    <Suspense fallback={
      <main className="min-h-screen bg-background flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </main>
    }>
      <GoogleCallbackInner />
    </Suspense>
  );
}

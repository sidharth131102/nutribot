"use client";

import dynamic from "next/dynamic";

/** Client-only, lazily-loaded wrapper around the WebGL scene. Keeps three.js
 *  and @react-three/* entirely out of every other route's bundle -- only
 *  the landing page pays for it, and only after first paint. */
const HeroOrb = dynamic(() => import("./HeroOrb"), {
  ssr: false,
  loading: () => (
    <div className="absolute inset-0 flex items-center justify-center">
      <div className="w-64 h-64 rounded-full bg-primary/10 blur-3xl animate-pulse-glow" />
    </div>
  ),
});

export default function HeroOrbLoader() {
  return <HeroOrb />;
}

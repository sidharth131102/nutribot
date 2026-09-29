"use client";

import type { ReactNode } from "react";

/** An infinite horizontal scroll strip -- the row is duplicated once and the
 *  pair is animated left by exactly 50%, so it loops seamlessly. Pure CSS
 *  (the `marquee` keyframe in tailwind.config.ts), no JS animation loop. */
export default function Marquee({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={`overflow-hidden relative ${className ?? ""}`}>
      <div className="absolute inset-y-0 left-0 w-16 bg-gradient-to-r from-background to-transparent z-10 pointer-events-none" />
      <div className="absolute inset-y-0 right-0 w-16 bg-gradient-to-l from-background to-transparent z-10 pointer-events-none" />
      <div className="flex w-max animate-marquee hover:[animation-play-state:paused]">
        <div className="flex items-center gap-3 pr-3">{children}</div>
        <div className="flex items-center gap-3 pr-3" aria-hidden>{children}</div>
      </div>
    </div>
  );
}

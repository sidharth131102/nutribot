/** Hand-drawn-style accent doodles -- the scattered stars/squiggles/shapes
 *  the reference design uses near its illustrations. Simple stroke-based
 *  SVGs (currentColor, round caps, no fill) rather than any icon library --
 *  these are decoration, not semantic icons, so a library would be the
 *  wrong tool. Each is small and self-contained; <DoodleField> scatters a
 *  chosen set of them absolutely within whatever `relative` container wraps
 *  it, so a section only needs one import + a list of placements.
 */
import type { CSSProperties } from "react";

type DoodleProps = { className?: string };

export function Sparkle({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 32 32" fill="none" className={className}>
      <path d="M16 2 L19 13 L30 16 L19 19 L16 30 L13 19 L2 16 L13 13 Z"
        stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

export function Squiggle({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 60 20" fill="none" className={className}>
      <path d="M2 14 Q10 2 18 14 T34 14 T50 14 T58 8"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function Leaf({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 32 32" fill="none" className={className}>
      <path d="M6 26C6 14 14 6 26 6c0 12-8 20-20 20Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M8 24C14 18 18 14 24 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export function Heartbeat({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 60 24" fill="none" className={className}>
      <path d="M2 12h12l4-9 6 18 4-13 3 4h27"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Droplet({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 24 30" fill="none" className={className}>
      <path d="M12 2C12 2 3 14 3 20a9 9 0 0018 0C21 14 12 2 12 2Z"
        stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

export function Loop({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 40 40" fill="none" className={className}>
      <path d="M20 4C10 4 4 11 6 19c1.6 6.4 9 9 13-1 3-7.5-3-12-9-9.5S1 19 8 25s17 5 24-1"
        stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function Plus({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className}>
      <path d="M12 3v18M3 12h18" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

export function Carrot({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 26 34" fill="none" className={className}>
      <path d="M14 12c4-2 8-8 10-10-2 2-8 6-10 10Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M7 11c6 6 4.5 12-1.3 17.8C4 30.4 1.6 28 3.2 26.3 9 20.5 1.4 19 7 11 9.5 7.5 13 9 13 13c0 6-6 10-6 10"
        stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Apple({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 28 30" fill="none" className={className}>
      <path d="M14 10c-5-4-11-1-11 6 0 7 5 12 9 12 1.4 0 2-0.6 3-0.6s1.6 0.6 3 0.6c4 0 9-6 9-12 0-6.5-6-9-9-6"
        stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M14 10c0-3 1-6 4-8-3 0.5-5 3-5 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export function Star({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 32 32" fill="none" className={className}>
      <path d="M16 3l3.5 8.5L28 14l-7 5.5L23 28l-7-4.8L9 28l2-8.5L4 14l8.5-2.5Z"
        stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

export function Zigzag({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 56 18" fill="none" className={className}>
      <path d="M2 16 L12 2 L21 16 L30 2 L39 16 L48 2 L54 8"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Check({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 28 22" fill="none" className={className}>
      <path d="M2 11 L10 19 L26 2" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Dumbbell({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 44 20" fill="none" className={className}>
      <path d="M4 6v8M8 2v16M36 2v16M40 6v8M8 10h28" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Scribble({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 40 40" fill="none" className={className}>
      <ellipse cx="20" cy="20" rx="15" ry="10" stroke="currentColor" strokeWidth="1.7"
        transform="rotate(-12 20 20)" />
      <ellipse cx="20" cy="20" rx="15" ry="10" stroke="currentColor" strokeWidth="1.4" opacity="0.6"
        transform="rotate(8 20 20)" />
    </svg>
  );
}

export function Wave({ className }: DoodleProps) {
  return (
    <svg viewBox="0 0 60 16" fill="none" className={className}>
      <path d="M1 8c4-6 8-6 12 0s8 6 12 0 8-6 12 0 8 6 12 0 8-6 11-1"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

type Placement = {
  icon: (props: DoodleProps) => React.ReactNode;
  className: string; // position + size, e.g. "top-6 left-8 w-8 h-8"
  rotate?: number;
  opacity?: number;
};

/** Scatters a set of doodles absolutely inside the nearest `relative`
 *  ancestor. Purely decorative (aria-hidden), never intercepts clicks. */
export function DoodleField({ items }: { items: Placement[] }) {
  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
      {items.map((item, i) => {
        const style: CSSProperties = {
          transform: item.rotate ? `rotate(${item.rotate}deg)` : undefined,
          opacity: item.opacity ?? 0.7,
        };
        return (
          <div key={i} className={`absolute text-ink ${item.className}`} style={style}>
            <item.icon className="w-full h-full" />
          </div>
        );
      })}
    </div>
  );
}

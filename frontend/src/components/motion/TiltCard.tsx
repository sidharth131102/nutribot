"use client";

import { motion, useMotionTemplate, useMotionValue, useSpring } from "framer-motion";
import { type ReactNode } from "react";

type Props = {
  children: ReactNode;
  className?: string;
  /** Max tilt in degrees. */
  max?: number;
};

/** A card that tilts in 3D toward the cursor (perspective transform) and
 *  carries a soft radial spotlight that follows the pointer -- the "hover a
 *  feature card and it feels alive" effect. */
export default function TiltCard({ children, className, max = 10 }: Props) {
  const rotateX = useSpring(useMotionValue(0), { stiffness: 220, damping: 20 });
  const rotateY = useSpring(useMotionValue(0), { stiffness: 220, damping: 20 });
  const mouseX = useMotionValue(50);
  const mouseY = useMotionValue(50);
  const spotlight = useMotionTemplate`radial-gradient(280px circle at ${mouseX}% ${mouseY}%, rgba(32,201,151,0.14), transparent 70%)`;

  function handleMove(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width;
    const py = (e.clientY - rect.top) / rect.height;
    rotateY.set((px - 0.5) * max * 2);
    rotateX.set(-(py - 0.5) * max * 2);
    mouseX.set(px * 100);
    mouseY.set(py * 100);
  }

  function handleLeave() {
    rotateX.set(0);
    rotateY.set(0);
  }

  return (
    <motion.div
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
      style={{ rotateX, rotateY, transformStyle: "preserve-3d", transformPerspective: 800 }}
      className={`relative ${className ?? ""}`}
    >
      <motion.div
        aria-hidden
        className="pointer-events-none absolute -inset-px rounded-[inherit]"
        style={{ background: spotlight }}
      />
      {children}
    </motion.div>
  );
}

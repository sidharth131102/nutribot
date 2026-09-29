"use client";

import { motion, type Variants } from "framer-motion";
import type { ReactNode } from "react";

type Props = {
  children: ReactNode;
  className?: string;
  delay?: number;
  /** Direction the element travels in from as it reveals. */
  from?: "up" | "down" | "left" | "right" | "scale" | "none";
  /** Re-play every time it scrolls into view instead of only once. */
  loop?: boolean;
};

const OFFSETS: Record<NonNullable<Props["from"]>, Record<string, number>> = {
  up: { y: 28 },
  down: { y: -28 },
  left: { x: 28 },
  right: { x: -28 },
  scale: { scale: 0.92 },
  none: {},
};

/** Fades + slides an element in the moment it scrolls into the viewport.
 *  The single primitive every landing-page section is built from. */
export default function Reveal({ children, className, delay = 0, from = "up", loop = false }: Props) {
  const offset = OFFSETS[from];
  const variants: Variants = {
    hidden: { opacity: 0, ...offset },
    visible: {
      opacity: 1,
      x: 0,
      y: 0,
      scale: 1,
      transition: { duration: 0.7, delay, ease: [0.16, 1, 0.3, 1] },
    },
  };

  return (
    <motion.div
      className={className}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: !loop, amount: 0.25 }}
      variants={variants}
    >
      {children}
    </motion.div>
  );
}

/** Wraps a list of children and staggers their entrance -- pass Reveal (or
 *  any motion element with the same variant names) as direct children. */
export function StaggerGroup({
  children,
  className,
  stagger = 0.09,
}: {
  children: ReactNode;
  className?: string;
  stagger?: number;
}) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, amount: 0.2 }}
      variants={{ visible: { transition: { staggerChildren: stagger } } }}
    >
      {children}
    </motion.div>
  );
}

export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 22 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: [0.16, 1, 0.3, 1] } },
};

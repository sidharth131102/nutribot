import type React from "react";

import { cn } from "@/lib/utils";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const { className, ...rest } = props;
  return (
    <input
      className={cn(
        "w-full rounded-lg border border-border bg-panel px-3 py-2 text-text outline-none focus:border-primary",
        className
      )}
      {...rest}
    />
  );
}

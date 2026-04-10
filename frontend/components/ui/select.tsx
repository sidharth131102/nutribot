import type React from "react";

import { cn } from "@/lib/utils";

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const { className, ...rest } = props;
  return (
    <select
      className={cn(
        "w-full rounded-lg border border-border bg-panel px-3 py-2 text-text outline-none focus:border-primary",
        className
      )}
      {...rest}
    />
  );
}

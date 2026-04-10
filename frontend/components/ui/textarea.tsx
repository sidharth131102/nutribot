import type React from "react";

import { cn } from "@/lib/utils";

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { className, ...rest } = props;
  return (
    <textarea
      className={cn(
        "min-h-24 w-full rounded-lg border border-border bg-panel px-3 py-2 text-text outline-none focus:border-primary",
        className
      )}
      {...rest}
    />
  );
}

import type React from "react";

import { cn } from "@/lib/utils";

export function Button(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const { className, ...rest } = props;
  return (
    <button
      className={cn(
        "rounded-lg bg-primary px-4 py-2 font-semibold text-[#06110f] transition hover:bg-[#36d6a9] disabled:cursor-not-allowed disabled:opacity-60",
        className
      )}
      {...rest}
    />
  );
}

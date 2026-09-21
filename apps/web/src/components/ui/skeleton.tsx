"use client";

import { cn } from "../../lib/utils";

/** Loading placeholder: pulsing block. Keyframes reserved for loading states. */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-lg bg-white/[0.06]", className)}
      {...props}
    />
  );
}

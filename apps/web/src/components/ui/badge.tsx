"use client";

import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium tabular-nums",
  {
    variants: {
      variant: {
        default: "bg-white/[0.07] text-zinc-300 outline-1 outline-white/10",
        emerald: "bg-emerald-400/10 text-emerald-300 outline-1 outline-emerald-400/20",
        sky: "bg-sky-400/10 text-sky-300 outline-1 outline-sky-400/20",
        amber: "bg-amber-400/10 text-amber-300 outline-1 outline-amber-400/20",
        red: "bg-red-400/10 text-red-300 outline-1 outline-red-400/20",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };

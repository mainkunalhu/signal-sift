"use client";

import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn, PRESS } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-xl text-sm font-medium outline-none transition-[background-color,color,opacity,scale] duration-150 ease-out focus-visible:outline-2 focus-visible:outline-white/60 disabled:pointer-events-none disabled:opacity-40 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-zinc-100 text-zinc-900 hover:bg-white",
        secondary: "bg-white/[0.07] text-zinc-200 outline-1 outline-white/10 hover:bg-white/[0.12]",
        ghost: "text-zinc-400 hover:bg-white/[0.06] hover:text-zinc-200",
        destructive: "text-red-300 hover:bg-red-500/10",
      },
      size: {
        sm: "h-8 px-3 text-[13px]",
        md: "h-10 px-4",
        icon: "h-10 w-10",
        "icon-sm": "h-8 w-8",
      },
    },
    defaultVariants: { variant: "default", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  static?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, static: isStatic, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), !isStatic && PRESS, className)}
      {...props}
    />
  ),
);
Button.displayName = "Button";

export { Button, buttonVariants };

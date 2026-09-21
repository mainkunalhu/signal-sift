import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const PRESS = "transition-transform duration-150 ease-out active:scale-[0.96]";

export const EASE: React.CSSProperties = {
  transitionTimingFunction: "cubic-bezier(0.2, 0, 0, 1)",
};

"use client";

import { ArrowUp, Loader2 } from "lucide-react";
import { useState } from "react";
import { cn, EASE, PRESS } from "../lib/utils";

export default function QueryBox({
  loading,
  onAsk,
  autoFocus,
}: {
  loading: boolean;
  onAsk: (query: string) => void;
  autoFocus?: boolean;
}) {
  const [value, setValue] = useState("");

  return (
    <form
      className="w-full"
      onSubmit={(e) => {
        e.preventDefault();
        const q = value.trim();
        if (q && !loading) {
          setValue("");
          onAsk(q);
        }
      }}
    >
      {/* Floating composer: elevation from shadow, not borders. */}
      <div
        className="rounded-[28px] bg-[#26262b]/95 shadow-[0_12px_40px_rgb(0,0,0,0.55)] backdrop-blur transition-[background-color] duration-150 focus-within:bg-[#2b2b31]/95"
        style={EASE}
      >
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ask anything"
          aria-label="Research question"
          disabled={loading}
          autoFocus={autoFocus}
          className="min-h-[52px] w-full bg-transparent px-5 pt-1 text-[15px] text-zinc-100 outline-none placeholder:text-zinc-500 disabled:opacity-60"
        />
        <div className="flex items-center px-3 pb-3">
          <span className="ml-2 hidden text-[11px] tracking-wide text-zinc-600 sm:inline">
            gpt-oss swarm · every claim cited
          </span>
          <span className="flex-1" />
          <button
            type="submit"
            disabled={loading || !value.trim()}
            aria-label={loading ? "Researching" : "Send"}
            className={cn(
              "relative grid h-9 w-9 place-items-center overflow-hidden rounded-full text-zinc-900 outline-none transition-[opacity,background-color,scale] duration-150 focus-visible:outline-2 focus-visible:outline-white/60 disabled:cursor-not-allowed",
              value.trim() && !loading
                ? "bg-zinc-100 hover:bg-white"
                : "bg-zinc-600 text-zinc-900 opacity-70",
              PRESS,
            )}
          >
            <ArrowUp
              aria-hidden
              strokeWidth={2.5}
              className={cn(
                "col-start-1 row-start-1 h-[18px] w-[18px] transition-[opacity,scale,filter] duration-200",
                loading ? "scale-[0.25] opacity-0 blur-[4px]" : "scale-100 opacity-100 blur-0",
              )}
              style={EASE}
            />
            <Loader2
              aria-hidden
              strokeWidth={2.5}
              className={cn(
                "col-start-1 row-start-1 h-[18px] w-[18px] animate-spin transition-[opacity,scale,filter] duration-200",
                loading ? "scale-100 opacity-100 blur-0" : "scale-[0.25] opacity-0 blur-[4px]",
              )}
              style={EASE}
            />
          </button>
        </div>
      </div>
    </form>
  );
}

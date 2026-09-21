"use client";

import { ArrowUp, Loader2 } from "lucide-react";
import { useState } from "react";
import { cn, EASE, PRESS } from "../lib/utils";
import { Badge } from "./ui/badge";

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
      <div
        className="rounded-2xl bg-white/[0.04] outline-1 outline-white/10 transition-[outline-color,background-color] duration-150 focus-within:bg-white/[0.06] focus-within:outline-white/25"
        style={EASE}
      >
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ask a hard question…"
          aria-label="Research question"
          disabled={loading}
          autoFocus={autoFocus}
          className="min-h-12 w-full bg-transparent px-4 pt-3 text-[15px] text-zinc-100 outline-none placeholder:text-zinc-500 disabled:opacity-60"
        />
        <div className="flex items-center gap-2 px-2.5 pb-2.5">
          <Badge variant="default" className="ml-1.5 hidden sm:inline-flex">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            gpt-oss swarm
          </Badge>
          <span className="flex-1" />
          <button
            type="submit"
            disabled={loading || !value.trim()}
            aria-label={loading ? "Researching" : "Start research"}
            className={cn(
              "relative grid h-9 w-9 place-items-center overflow-hidden rounded-xl bg-zinc-100 text-zinc-900 outline-none transition-[opacity,background-color,scale] duration-150 hover:bg-white focus-visible:outline-2 focus-visible:outline-white/60 disabled:cursor-not-allowed disabled:opacity-40",
              PRESS,
            )}
          >
            <ArrowUp
              aria-hidden
              strokeWidth={2.25}
              className={cn(
                "col-start-1 row-start-1 h-[18px] w-[18px] transition-[opacity,scale,filter] duration-200",
                loading ? "scale-[0.25] opacity-0 blur-[4px]" : "scale-100 opacity-100 blur-0",
              )}
              style={EASE}
            />
            <Loader2
              aria-hidden
              strokeWidth={2.25}
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

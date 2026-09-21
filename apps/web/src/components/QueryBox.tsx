"use client";

import { useState } from "react";

const PRESS = "transition-transform duration-150 ease-out active:scale-[0.96]";
const EASE = "cubic-bezier(0.2, 0, 0, 1)";

export default function QueryBox({
  loading,
  onAsk,
}: {
  loading: boolean;
  onAsk: (query: string) => void;
}) {
  const [value, setValue] = useState("");

  return (
    <form
      className="w-full"
      onSubmit={(e) => {
        e.preventDefault();
        const q = value.trim();
        if (q && !loading) onAsk(q);
      }}
    >
      <div
        className="flex items-center gap-2 rounded-2xl bg-white/[0.04] p-2 pl-4 outline-1 outline-white/10 transition-[outline-color,background-color] duration-150 focus-within:bg-white/[0.06] focus-within:outline-white/25"
        style={{ transitionTimingFunction: EASE }}
      >
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ask a hard question…"
          aria-label="Research question"
          disabled={loading}
          className="min-h-11 flex-1 bg-transparent text-[15px] text-zinc-100 outline-none placeholder:text-zinc-500 disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={loading || !value.trim()}
          aria-label={loading ? "Researching" : "Start research"}
          className={`relative grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-xl bg-zinc-100 text-zinc-900 outline-none transition-[opacity,background-color,scale] duration-150 hover:bg-white focus-visible:ring-2 focus-visible:ring-white/70 disabled:cursor-not-allowed disabled:opacity-40 ${PRESS}`}
        >
          {/* Idle icon */}
          <svg
            aria-hidden
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            className={`col-start-1 row-start-1 h-5 w-5 transition-[opacity,scale,filter] duration-200 ${
              loading ? "scale-[0.25] opacity-0 blur-[4px]" : "scale-100 opacity-100 blur-0"
            }`}
            style={{ transitionTimingFunction: EASE }}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14m-6-6 6 6-6 6" />
          </svg>
          {/* Loading icon (stays mounted for the cross-fade) */}
          <svg
            aria-hidden
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            className={`col-start-1 row-start-1 h-5 w-5 animate-spin ${
              loading ? "scale-100 opacity-100 blur-0" : "scale-[0.25] opacity-0 blur-[4px]"
            } transition-[opacity,scale,filter] duration-200`}
            style={{ transitionTimingFunction: EASE }}
          >
            <path strokeLinecap="round" d="M12 3a9 9 0 1 0 9 9" />
          </svg>
        </button>
      </div>
    </form>
  );
}

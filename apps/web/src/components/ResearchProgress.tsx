"use client";

import { memo } from "react";
import type { SubQuestion } from "../lib/events";

export interface LiveState {
  plan: SubQuestion[];
  progress: Record<string, { urls: string[]; claims: number }>;
  supported: number;
  dropped: number;
  tokens: number;
}

/** Live research activity inside the pending assistant message: plan
 *  checklist fills as sub-questions complete, then counts + streaming
 *  volume. Static labels carry state; motion is decoration only.
 */
function ResearchProgress({ live, running }: { live: LiveState; running: boolean }) {
  const doneCount = Object.keys(live.progress).length;
  const sources = Object.values(live.progress).reduce((a, p) => a + p.urls.length, 0);
  return (
    <div className="mb-3 rounded-xl bg-white/[0.03] p-3 outline-1 outline-white/[0.07]">
      <p className="mb-2 flex items-center gap-2 text-xs font-medium text-zinc-400">
        <span
          aria-hidden
          className={`h-2 w-2 rounded-full ${running ? "animate-pulse bg-sky-400" : "bg-emerald-400"}`}
        />
        {running
          ? `Researching · ${doneCount}/${live.plan.length || "…"} searches done`
          : "Research complete"}
        <span className="ml-auto tabular-nums text-zinc-500">
          {sources} sources · {live.supported} kept
          {live.dropped > 0 && ` · ${live.dropped} dropped`}
        </span>
      </p>
      {live.plan.length > 0 && (
        <ul className="flex flex-col gap-1">
          {live.plan.map((sq) => {
            const done = sq.id in live.progress;
            return (
              <li key={sq.id} className="flex items-start gap-2 text-[13px] leading-5">
                <span
                  aria-hidden
                  className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full transition-colors duration-150 ${
                    done ? "bg-emerald-400" : "bg-zinc-700"
                  }`}
                />
                <span className={done ? "text-zinc-300" : "text-zinc-500"}>
                  {sq.question}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default memo(ResearchProgress);

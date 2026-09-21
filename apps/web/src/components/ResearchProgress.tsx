"use client";

import { Check, Circle, Loader2 } from "lucide-react";
import { memo } from "react";
import type { SubQuestion } from "../lib/events";
import { cn } from "../lib/utils";
import { Skeleton } from "./ui/skeleton";

export interface LiveState {
  plan: SubQuestion[];
  progress: Record<string, { urls: string[]; claims: number }>;
  supported: number;
  dropped: number;
  tokens: number;
}

/** Live research activity: skeleton while planning, per-question steps with
 *  lucide status icons, counts as static text. Motion decorates; labels inform.
 */
function ResearchProgress({ live, running }: { live: LiveState; running: boolean }) {
  const doneIds = new Set(Object.keys(live.progress));
  const sources = Object.values(live.progress).reduce((a, p) => a + p.urls.length, 0);

  if (live.plan.length === 0) {
    return (
      <div className="mb-3 rounded-xl bg-white/[0.03] p-4 outline-1 outline-white/[0.07]" aria-live="polite">
        <p className="mb-3 flex items-center gap-2 text-[13px] font-medium text-zinc-300">
          <Loader2 aria-hidden strokeWidth={2} className="h-4 w-4 animate-spin text-sky-400" />
          Planning searches…
        </p>
        <div className="flex flex-col gap-2">
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-4 w-3/5" />
        </div>
      </div>
    );
  }

  const activeIdx = live.plan.findIndex((sq) => !doneIds.has(sq.id));
  return (
    <div className="mb-3 rounded-xl bg-white/[0.03] p-4 outline-1 outline-white/[0.07]" aria-live="polite">
      <p className="mb-2.5 flex items-center gap-2 text-[13px] font-medium text-zinc-300">
        {running ? (
          <Loader2 aria-hidden strokeWidth={2} className="h-4 w-4 animate-spin text-sky-400" />
        ) : (
          <Check aria-hidden strokeWidth={2.25} className="h-4 w-4 text-emerald-400" />
        )}
        {running
          ? `Researching · ${doneIds.size}/${live.plan.length} searches`
          : "Research complete"}
        <span className="ml-auto font-normal text-zinc-500 tabular-nums">
          {sources} sources · {live.supported} kept
          {live.dropped > 0 && ` · ${live.dropped} dropped`}
        </span>
      </p>
      <ul className="flex flex-col gap-1.5">
        {live.plan.map((sq, i) => {
          const done = doneIds.has(sq.id);
          const active = running && !done && i === activeIdx;
          return (
            <li key={sq.id} className="flex items-start gap-2.5 text-[13px] leading-5">
              {done ? (
                <Check aria-hidden strokeWidth={2.25} className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
              ) : active ? (
                <Loader2 aria-hidden strokeWidth={2} className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-sky-400" />
              ) : (
                <Circle aria-hidden strokeWidth={2} className="mt-1 h-3 w-3 shrink-0 text-zinc-700" />
              )}
              <span className={cn(done ? "text-zinc-200" : "text-zinc-500")}>{sq.question}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default memo(ResearchProgress);

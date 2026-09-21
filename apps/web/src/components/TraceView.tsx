"use client";

import { memo } from "react";
import type { SubQuestion } from "../lib/events";

export interface TraceState {
  route: string | null;
  plan: SubQuestion[];
  progress: Record<string, { urls: string[]; claims: number }>;
  supported: number;
  dropped: number;
  synth: { coverage: number; seconds: number } | null;
  latencyMs: number | null;
}

function Row({
  done,
  active,
  label,
  detail,
}: {
  done: boolean;
  active: boolean;
  label: string;
  detail: string;
}) {
  return (
    <li className="flex items-start gap-3">
      {/* Status dot: static color cue, never motion-only. */}
      <span
        aria-hidden
        className={`mt-1.5 h-2 w-2 shrink-0 rounded-full transition-colors duration-150 ${
          done ? "bg-emerald-400" : active ? "animate-pulse bg-sky-400" : "bg-zinc-700"
        }`}
      />
      <div className="min-w-0 flex-1">
        <p className={`text-[13px] font-medium ${done || active ? "text-zinc-200" : "text-zinc-500"}`}>
          {label}
        </p>
        <p className="truncate text-xs text-zinc-500 tabular-nums">{detail}</p>
      </div>
    </li>
  );
}

function TraceView({ trace, running }: { trace: TraceState; running: boolean }) {
  const planned = trace.plan.length > 0;
  const researched = Object.keys(trace.progress).length;
  const verified = trace.supported + trace.dropped > 0;
  return (
    <section aria-label="Run trace" className="min-w-0">
      <h2 className="mb-3 text-xs font-semibold tracking-widest text-zinc-500 uppercase">
        Trace
      </h2>
      <ol className="flex flex-col gap-2.5">
        <Row
          done={trace.route !== null}
          active={running && trace.route === null}
          label={`Router · ${trace.route ?? "…"}`}
          detail="fast-model gate"
        />
        <Row
          done={planned}
          active={running && trace.route !== null && !planned}
          label={`Planner · ${trace.plan.length} sub-questions`}
          detail={planned ? trace.plan.map((s) => s.id).join(" ") : "decomposing"}
        />
        <Row
          done={planned && researched >= trace.plan.length && trace.plan.length > 0}
          active={researched > 0 && researched < trace.plan.length}
          label={`Researchers · ${researched}/${trace.plan.length || "–"} done`}
          detail={
            researched > 0
              ? `${Object.values(trace.progress).reduce((a, p) => a + p.urls.length, 0)} sources`
              : "fan-out"
          }
        />
        <Row
          done={verified}
          active={researched >= trace.plan.length && trace.plan.length > 0 && !verified}
          label={`Verifier · ${trace.supported} kept / ${trace.dropped} dropped`}
          detail="grounding + NLI, max 3 tries"
        />
        <Row
          done={trace.synth !== null}
          active={verified && trace.synth === null}
          label="Synthesizer"
          detail={
            trace.synth
              ? `coverage ${trace.synth.coverage} · ${trace.synth.seconds}s`
              : "cited report"
          }
        />
      </ol>
      {trace.latencyMs !== null && (
        <p className="mt-3 text-xs text-zinc-500 tabular-nums">
          {(trace.latencyMs / 1000).toFixed(1)}s end-to-end
        </p>
      )}
    </section>
  );
}

export default memo(TraceView);
